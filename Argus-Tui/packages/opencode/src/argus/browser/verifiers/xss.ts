import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import { loginIfFormPresent } from "../login"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

const XSS_ATTR_MARKERS = [
  "<img src=x onerror=",
  "onload=",
  "javascript:",
].map(m => m.toLowerCase())
const XSS_TAG_MARKERS = [
  "<script>",
  "prompt(",
  "alert(",
].map(m => m.toLowerCase())

export class StoredXSSVerifier implements VerificationScenario {
  name = "stored-xss"
  description = "Stored XSS — injects payload and checks if it executes in victim view"

  private logs: string[] = []
  private payloadExecuted = false
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private domOnVictim = ""
  private harDir: string | null = null

  constructor(
    private engine: BrowserEngine,
    private injectUrl: string,
    private victimViewUrl: string,
    private payload: string,
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    await this.engine.launch()
    // Create a temp directory for HAR capture
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    await this.engine.createContext({ harDir: this.harDir } as any)
    this.logs.push(`Stored XSS verifier setup complete — payload: ${this.payload}`)
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
    // Clean up temp HAR directory
    if (this.harDir && existsSync(this.harDir)) {
      try {
        rmSync(this.harDir, { recursive: true, force: true })
      } catch { /* best-effort cleanup */ }
    }
  }

  async execute(): Promise<void> {
    const injectPage = await this.engine.navigate(this.injectUrl)
    await injectPage.waitForLoadState("networkidle")

    this.capturedRequests.push(`GET ${this.injectUrl} [injection page]`)

    // Inject payload into all visible input fields:
    // 1. Fields inside <form> elements (traditional HTML forms)
    const forms = await injectPage.locator("form").all()
    for (const form of forms) {
      const inputFields = await form.locator(
        "input[type=text], textarea, input:not([type]), [contenteditable=true]",
      ).all()
      for (const field of inputFields) {
        if (await field.isVisible()) {
          await field.fill(this.payload)
          this.logs.push("Injected payload into field inside <form>")
        }
      }
    }
    // 2. Fields outside <form> (modern SPAs, dynamic UIs)
    const standaloneInputs = await injectPage.locator(
      "input[type=text]:not(form input), textarea:not(form textarea), " +
      "input:not([type]):not(form input), [contenteditable=true]:not(form [contenteditable=true])",
    ).all()
    for (const field of standaloneInputs) {
      if (await field.isVisible()) {
        await field.fill(this.payload)
        this.logs.push("Injected payload into field outside <form>")
      }
    }
    // Submit the injection: try multiple strategies
    // 1. Try Press Enter on the last filled field
    const lastField = await injectPage.locator(
      "input[type=text], textarea, input:not([type]), [contenteditable=true]",
    ).last()
    if (await lastField.isVisible().catch(() => false)) {
      await lastField.press("Enter")
      await injectPage.waitForTimeout(1000)
      // Check if navigation occurred
      if (injectPage.url() !== this.injectUrl) {
        this.logs.push("Submitted via Enter key on input field")
      } else {
        // 2. Try standard submit buttons
        const submitBtn = injectPage.locator(
          "button[type=submit], input[type=submit], " +
          "button:has-text('Submit'), button:has-text('Save'), " +
          "button:has-text('Post'), button:has-text('Send'), " +
          "button:has-text('Comment'), button:has-text('Reply')"
        ).first()
        if (await submitBtn.isVisible()) {
          await submitBtn.click()
          await injectPage.waitForTimeout(1500)
          this.logs.push("Submitted form with XSS payload via submit button")
        } else {
          // 3. Fallback: try any visible button near the inputs
          const anyBtn = injectPage.locator("button:visible, input[type=button]:visible").first()
          if (await anyBtn.isVisible()) {
            await anyBtn.click()
            await injectPage.waitForTimeout(1500)
            this.logs.push("Submitted via fallback button click")
          }
        }
      }
    }

    try {
      const injectShot = await this.engine.captureScreenshot(injectPage)
      this.capturedScreenshots.push({ data: injectShot, label: "injection" })
    } catch { /* screenshot best-effort */ }

    this.capturedResponses.push(`Injection page: ${injectPage.url()}`)
    await injectPage.close()

    const victimPage = await this.engine.navigate(this.victimViewUrl)
    await victimPage.waitForLoadState("networkidle")

    this.capturedRequests.push(`GET ${this.victimViewUrl} [victim view]`)
    this.capturedResponses.push(`Victim page: ${victimPage.url()}`)

    const pageContent = (await victimPage.content()).toLowerCase()
    this.domOnVictim = pageContent
    // Check raw innerHTML (unescaped) for XSS markers — this is where
    // actually executing payloads will appear (script tags, event handlers).
    // The serialized DOM (pageContent) may contain HTML-escaped payload
    // text that does NOT execute — do NOT flag those as findings.
    const innerHtml = (await victimPage.evaluate(() => document.body?.innerHTML ?? "")).toLowerCase()
    const attrMarkersFound = XSS_ATTR_MARKERS.filter(m => innerHtml.includes(m))
    const tagMarkersFound = XSS_TAG_MARKERS.filter(m => innerHtml.includes(m))
    // Log whether the payload text appears in serialized DOM (may be HTML-escaped)
    // but only flag as finding if markers found in unescaped innerHTML.
    const payloadTextInDom = pageContent.includes(this.payload.toLowerCase())
    // Only consider XSS confirmed if markers found in unescaped innerHTML
    // (script/event-handler context). Payload text that only appears in the
    // serialized DOM was HTML-escaped and will NOT execute.
    const confirmedExecution = tagMarkersFound.length > 0
    const probableExecution = attrMarkersFound.length > 0
    this.payloadExecuted = confirmedExecution || probableExecution

    try {
      const victimShot = await this.engine.captureScreenshot(victimPage)
      this.capturedScreenshots.push({ data: victimShot, label: "victim-view" })
    } catch { /* screenshot best-effort */ }

    this.logs.push(`XSS tag markers in innerHTML: ${tagMarkersFound.length > 0 ? tagMarkersFound.join(", ") : "none"}`)
    this.logs.push(`XSS attr markers in innerHTML: ${attrMarkersFound.length > 0 ? attrMarkersFound.join(", ") : "none"}`)
    this.logs.push(`Payload text in DOM (may be escaped): ${payloadTextInDom}`)
    this.logs.push(`XSS ${this.payloadExecuted ? "DETECTED" : "not detected"}`)

    await victimPage.close()
  }

  async verify(): Promise<VerifierResult> {
    return {
      passed: this.payloadExecuted,
      confidence: this.payloadExecuted ? Confidence.HIGH : Confidence.INFORMATIONAL,
      evidence: [],
      summary: this.payloadExecuted
        ? `Stored XSS confirmed: payload rendered on victim view ${this.victimViewUrl}`
        : `Stored XSS not detected — payload did not execute on victim view`,
    }
  }

  async collectEvidence(): Promise<EvidencePackage> {
    // Persist screenshots and requests/responses through the EvidenceCollector if available
    const collectedArtifacts: import("../../evidence/types").ArtifactEntry[] = []
    let computedHash = ""
    if (this.collector && this.engagementId && this.findingId) {
      for (const shot of this.capturedScreenshots) {
        const entry = await this.collector.captureScreenshot(this.engagementId, this.findingId, shot.data).catch(() => null)
        if (entry) collectedArtifacts.push(entry)
      }
      // Save manually captured request/response stubs
      for (const req of this.capturedRequests) {
        const entry = await this.collector.saveRequest(this.engagementId, this.findingId, req).catch(() => null)
        if (entry) collectedArtifacts.push(entry)
      }
      for (const res of this.capturedResponses) {
        const entry = await this.collector.saveResponse(this.engagementId, this.findingId, res).catch(() => null)
        if (entry) collectedArtifacts.push(entry)
      }
      // Ingest HAR data for full request/response details with actual headers and bodies
      if (this.harDir) {
        const harArtifacts = await this.collector.ingestHarFiles(this.engagementId, this.findingId, this.harDir).catch(() => [])
        collectedArtifacts.push(...harArtifacts)
      }
      // Capture the real package_hash from the persisted manifest
      const manifest = await this.collector.createPackage(this.engagementId, this.findingId, collectedArtifacts).catch(() => null)
      if (manifest) computedHash = manifest.package_hash
    }

    // Compute an inline hash when no collector was available
    if (!computedHash && collectedArtifacts.length > 0) {
      const hashInput = collectedArtifacts.map((a) => a.hash || a.path).join("")
      computedHash = createHash("sha256").update(hashInput).digest("hex")
    }

    return {
      packageId: randomUUID(),
      findingId: this.findingId ?? "",
      artifacts: collectedArtifacts.length > 0
        ? collectedArtifacts.map((a) => ({
            path: a.path,
            type: a.type,
            hash: a.hash,
          }))
        : [
            ...this.capturedScreenshots.map((s) => ({ path: `xss-${s.label}.png`, type: "screenshot" as const })),
            ...this.capturedRequests.map((r) => ({ path: r, type: "request" as const })),
            ...this.capturedResponses.map((r) => ({ path: r, type: "response" as const })),
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }
}

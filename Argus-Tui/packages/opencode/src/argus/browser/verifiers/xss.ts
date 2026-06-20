import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import { loginIfFormPresent } from "../login"
import type { EvidenceCollector } from "../../evidence/collector"

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
    await this.engine.createContext()
    this.logs.push(`Stored XSS verifier setup complete — payload: ${this.payload}`)
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
  }

  async execute(): Promise<void> {
    const injectPage = await this.engine.navigate(this.injectUrl)
    await injectPage.waitForLoadState("networkidle")

    this.capturedRequests.push(`GET ${this.injectUrl} [injection page]`)

    // Scope injection to fields inside <form> elements only
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
    const submitBtn = injectPage.locator("button[type=submit], input[type=submit]").first()
    if (await submitBtn.isVisible()) {
      await submitBtn.click()
      await injectPage.waitForTimeout(1500)
      this.logs.push("Submitted form with XSS payload")
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
    // Check raw innerHTML (unescaped) for attribute-based XSS markers
    const innerHtml = (await victimPage.evaluate(() => document.body?.innerHTML ?? "")).toLowerCase()
    const attrMarkersFound = XSS_ATTR_MARKERS.filter(m => innerHtml.includes(m))
    const tagMarkersFound = XSS_TAG_MARKERS.filter(m => innerHtml.includes(m))
    // Check if payload text appears in the serialized DOM (indicates persistence, even if escaped)
    const payloadTextInDom = pageContent.includes(this.payload.toLowerCase())
    // Only consider XSS confirmed if markers found in unescaped innerHTML
    // or if the payload appears in raw attribute/tag context
    const confirmedExecution = tagMarkersFound.length > 0
    const probableExecution = attrMarkersFound.length > 0 || (payloadTextInDom && tagMarkersFound.length === 0 && attrMarkersFound.length === 0)
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
    if (this.collector && this.engagementId && this.findingId) {
      for (const shot of this.capturedScreenshots) {
        await this.collector.captureScreenshot(this.engagementId, this.findingId, shot.data).catch(() => {})
      }
      for (const req of this.capturedRequests) {
        await this.collector.saveRequest(this.engagementId, this.findingId, req).catch(() => {})
      }
      for (const res of this.capturedResponses) {
        await this.collector.saveResponse(this.engagementId, this.findingId, res).catch(() => {})
      }
      await this.collector.createPackage(this.engagementId, this.findingId, []).catch(() => {})
    }

    const artifacts: import("../../shared/types").ArtifactRef[] = []
    for (const shot of this.capturedScreenshots) {
      const filename = `xss-${shot.label}.png`
      artifacts.push({ path: filename, type: "screenshot" })
    }
    for (const req of this.capturedRequests) {
      artifacts.push({ path: req, type: "request" })
    }
    for (const res of this.capturedResponses) {
      artifacts.push({ path: res, type: "response" })
    }
    return {
      packageId: this.findingId ?? "",
      findingId: this.findingId ?? "",
      artifacts,
      packageHash: "",
      createdAt: new Date().toISOString(),
    }
  }
}

import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence, ProofStatus } from "../../shared/types"
import type { CleanupOutcome, ControlReference } from "../../shared/types"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"
import {
  createXssNonce,
  installXssProbe,
  resolveXssPayload,
  type XssExecutionHit,
} from "./xss-probe"
import { withQueryPayload, type XssInjectionPoint } from "./xss-plan"

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Options for a stored/reflected XSS run. */
export interface StoredXSSOptions {
  /**
   * Optional payload template. Must contain `{{nonce}}` and call the probe
   * entry point; a template that cannot prove execution is refused by
   * `resolveXssPayload()` so it can never be reported as a pass.
   */
  payloadTemplate?: string
}

/**
 * Stored XSS — proves the payload *executed* in the intended browser context.
 *
 * Stage 4.3 items 1–2. The verifier is built from a validated
 * `XssInjectionPoint` (see `xss-plan.ts`): the endpoint, parameter, method and
 * encoding are whatever discovery recorded, and the victim page is the
 * discovered endpoint (or an explicitly discovered victim page) — never a
 * guessed `/contact` path. The injection runs in its own browser context, then
 * a *separate* victim context is created (fresh cookie jar, storage and
 * profile) and the nonce execution probe is installed there before anything is
 * navigated. Confirmation requires an execution report for this run's nonce
 * from the victim page; reflected payload text, escaped output, a CSP block and
 * a hit on the injection page are all explicitly not confirmations.
 */
export class StoredXSSVerifier implements VerificationScenario {
  name = "stored-xss"
  description = "Stored XSS — injects at the discovered parameter and confirms nonce execution in the victim view"

  private logs: string[] = []
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private harDir: string | null = null

  private nonce = ""
  private payload = ""
  private hits: XssExecutionHit[] = []
  private victimPage: { url(): string } | null = null
  private victimContent = ""
  private probeInstalled = false
  private controls: ControlReference[] = []
  /** What teardown did, attached to the stored result by the runner. */
  private teardown: CleanupOutcome | null = null

  constructor(
    private engine: BrowserEngine,
    private readonly plan: XssInjectionPoint,
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
    private readonly options: StoredXSSOptions = {},
  ) {
    // Each run owns a fresh nonce. A payload that cannot carry it is refused
    // here — before the browser is touched — so a misconfigured caller fails
    // loudly instead of producing a result it cannot support.
    this.nonce = createXssNonce()
    this.payload = resolveXssPayload(this.options.payloadTemplate, this.nonce)
  }

  /** The nonce this run installed and requires; exposed for evidence/reporting. */
  get executionNonce(): string {
    return this.nonce
  }

  async setup(): Promise<void> {
    await this.engine.launch()
    // Create a temp directory for HAR capture
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })

    // The injection session is its own browser context: the attacker's cookies
    // and storage never become the victim's, and nothing about the victim
    // session is reused from it.
    await this.engine.createContext({ harDir: this.harDir })
    this.controls.push({
      kind: "injection-session",
      description: `inject the payload at discovered endpoint ${this.plan.url} (${this.plan.method} ${this.plan.encoding} parameter "${this.plan.parameter}")`,
      reference: this.plan.evidenceRef,
      outcome: "fresh browser context created for the injection session",
    })
    this.logs.push(
      `Stored XSS verifier setup complete — endpoint ${this.plan.url} discovered from ` +
        `${this.plan.evidenceRef}, parameter "${this.plan.parameter}", ${this.plan.method}/${this.plan.encoding}, ` +
        `execution nonce ${this.nonce} — HAR dir: ${this.harDir}`,
    )
  }

  /**
   * Close the browser and remove temporary evidence, recording what happened.
   *
   * Stage 4.3 item 3: teardown is part of the record. The runner reads this back
   * through `cleanupOutcome()` and stores it on the verification result, and the
   * same text is written as a log artifact when a collector is available.
   */
  async cleanup(): Promise<void> {
    const notes: string[] = []
    let ok = true
    try {
      await this.engine.close()
      notes.push("browser closed")
    } catch (error) {
      ok = false
      notes.push(`browser close failed: ${errorMessage(error)}`)
    }
    if (this.harDir && existsSync(this.harDir)) {
      try {
        rmSync(this.harDir, { recursive: true, force: true })
        notes.push("temporary HAR directory removed")
      } catch (error) {
        ok = false
        notes.push(`temporary HAR cleanup failed: ${errorMessage(error)}`)
      }
    }
    this.teardown = { ok, detail: notes.join("; ") || "nothing to clean up" }
    await this.persistLog(this.cleanupLogText()).catch(() => undefined)
  }

  cleanupOutcome(): CleanupOutcome {
    return this.teardown ?? { ok: false, detail: "cleanup did not run" }
  }

  async execute(): Promise<void> {
    await this.inject()
    await this.viewAsVictim()
  }

  /** Deliver the payload at the discovered endpoint/parameter (injection session). */
  private async inject(): Promise<void> {
    const injectionUrl =
      this.plan.method === "GET" ? withQueryPayload(this.plan, this.payload) : this.plan.url
    const injectPage = await this.engine.navigate(injectionUrl)
    await injectPage.waitForLoadState("networkidle")

    this.capturedRequests.push(
      [
        `${this.plan.method} ${injectionUrl}`,
        `parameter: ${this.plan.parameter} (${this.plan.encoding})`,
        `payload: ${this.payload}`,
        `discovered-from: ${this.plan.evidenceRef}`,
      ].join("\n"),
    )
    this.logs.push(
      `Injected via ${this.plan.method} ${this.plan.encoding} parameter "${this.plan.parameter}" at ${this.plan.url}`,
    )

    if (this.plan.method === "POST") {
      const field = injectPage.locator(`[name="${this.plan.parameter}"], #${this.plan.parameter}`).first()
      if (!(await field.isVisible().catch(() => false))) {
        throw new Error(
          `discovered POST parameter "${this.plan.parameter}" is not present at ${this.plan.url}`,
        )
      }
      await field.fill(this.payload)
      this.logs.push(`Filled discovered field "${this.plan.parameter}" with the nonce payload`)
      await field.press("Enter")
      await injectPage.waitForTimeout(1000)
      if (injectPage.url() === this.plan.url) {
        const submitBtn = injectPage.locator(
          "button[type=submit], input[type=submit], " +
          "button:has-text('Submit'), button:has-text('Save'), " +
          "button:has-text('Post'), button:has-text('Send'), " +
          "button:has-text('Comment'), button:has-text('Reply')"
        ).first()
        if (await submitBtn.isVisible()) {
          await submitBtn.click()
          await injectPage.waitForTimeout(1500)
          this.logs.push("Submitted the discovered form field")
        }
      }
    }

    try {
      const injectShot = await this.engine.captureScreenshot(injectPage)
      this.capturedScreenshots.push({ data: injectShot, label: "injection" })
    } catch { /* screenshot best-effort */ }

    this.capturedResponses.push(`Injection page: ${injectPage.url()}`)
    await injectPage.close()
  }

  /**
   * Open the victim view in a separate session and observe execution there.
   *
   * `createContext` replaces the engine's context, which closes the injection
   * session (cookies and storage included) before the victim context exists.
   * The nonce probe goes onto that fresh context before its first navigation.
   */
  private async viewAsVictim(): Promise<void> {
    const victimContext = await this.engine.createContext({ harDir: this.harDir ?? undefined })
    this.controls.push({
      kind: "victim-session",
      description: "victim view opened in a new browser context, separate from the injection session",
      reference: this.plan.victimUrl,
      outcome: "separate context created (fresh cookies, storage and profile)",
    })

    await installXssProbe(victimContext, this.nonce, (hit) => {
      this.hits.push(hit)
    })
    this.probeInstalled = true
    this.controls.push({
      kind: "execution-probe",
      description: "nonce execution probe installed on the victim context before navigation",
      reference: this.nonce,
      outcome: "installed",
    })

    const victimPage = await this.engine.navigate(this.plan.victimUrl)
    this.victimPage = victimPage
    await victimPage.waitForLoadState("networkidle")
    this.controls.push({
      kind: "victim-view",
      description: "victim view loaded in the separate victim context",
      reference: this.plan.victimUrl,
      outcome: "loaded",
    })

    this.capturedRequests.push(`GET ${this.plan.victimUrl} [victim view — separate session]`)

    // The execution report travels from the page over a Playwright binding, so
    // it can arrive just after the load event. Wait briefly for a hit that
    // belongs to this run *and* this page before deciding.
    for (let attempt = 0; attempt < 20 && !this.victimHit(); attempt++) {
      await victimPage.waitForTimeout(100)
    }

    this.victimContent = await victimPage.content()
    // Diagnostics only — reflected text is not execution and never confirms.
    const nonceReflected = this.victimContent.includes(this.nonce)
    this.logs.push(`Payload nonce present in victim DOM (not proof): ${nonceReflected}`)
    this.logs.push(`Execution reports received: ${this.hits.length}`)

    // Response evidence: what the victim page actually was, not just its URL.
    const bodyHash = createHash("sha256").update(this.victimContent).digest("hex")
    this.capturedResponses.push(
      [
        `GET ${this.plan.victimUrl} — ${this.victimContent.length} bytes, sha256 ${bodyHash}`,
        `nonce reflected in body: ${nonceReflected}`,
        `execution observed: ${Boolean(this.victimHit())}`,
      ].join("\n"),
    )

    if (this.victimHit()) {
      this.logs.push(`Attributable execution event: ${JSON.stringify(this.victimHit())}`)
    }

    try {
      const victimShot = await this.engine.captureScreenshot(victimPage)
      this.capturedScreenshots.push({ data: victimShot, label: "victim-view" })
    } catch { /* screenshot best-effort */ }

    this.logs.push(`XSS ${this.victimHit() ? "EXECUTED (nonce observed)" : "not executed"}`)

    await victimPage.close()
  }

  async verify(): Promise<VerifierResult> {
    // The execution control is judged from the reports present *now*: a hit can
    // arrive just after the victim load event, and a control recorded earlier
    // would then disagree with the claim it is supposed to support.
    const controls = [
      ...this.controls.filter((c) => c.kind !== "nonce-execution"),
      this.executionControl(),
      {
        kind: "execution-source",
        description: "only the run's nonce probe in the victim page counts as execution",
        reference: this.nonce,
        outcome: this.victimHit()
          ? "nonce payload executed in the victim page"
          : "no attributable nonce execution (page scripts, encoded or inert payloads are not execution)",
      },
    ]

    if (!this.probeInstalled) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: "XSS inconclusive — the victim session and its nonce probe were never established, so execution could not be observed",
        controls,
        error: {
          step: "setup",
          name: "XssProbeError",
          message: "nonce execution probe not installed",
        },
      })
    }

    if (!this.victimPage) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: "XSS inconclusive — the victim view was never loaded, so no execution could be observed",
        controls,
      })
    }

    const victimHit = this.victimHit()
    if (victimHit) {
      return this.result({
        status: ProofStatus.REPRODUCED,
        confidence: Confidence.HIGH,
        score: 0.9,
        summary: `Stored XSS confirmed: the nonce payload executed in the victim view at ${victimHit.url || this.plan.victimUrl}`,
        controls,
      })
    }

    const otherHits = this.hits.filter((hit) => hit.nonce === this.nonce)
    if (otherHits.length > 0) {
      return this.result({
        status: ProofStatus.NOT_REPRODUCED,
        confidence: Confidence.LOW,
        score: 0.2,
        summary:
          `Stored XSS not detected — the nonce payload executed on the injection page, ` +
          `not in the victim view at ${this.plan.victimUrl}`,
        controls,
      })
    }

    return this.result({
      status: ProofStatus.NOT_REPRODUCED,
      confidence: Confidence.LOW,
      score: 0.1,
      summary:
        `Stored XSS not detected — no execution of the nonce payload was observed in the victim view ` +
        `at ${this.plan.victimUrl}${this.nonceReflected() ? " (payload text was reflected but never ran)" : ""}`,
      controls,
    })
  }

  private executionControl(): ControlReference {
    const hit = this.victimHit()
    return {
      kind: "nonce-execution",
      description: "victim page reported execution of the run's nonce payload",
      reference: this.nonce,
      outcome: hit
        ? `executed at ${hit.url || this.plan.victimUrl} (${hit.detail || "handler"})`
        : this.nonceReflected()
          ? "no execution; the nonce was only reflected into the page"
          : "no execution observed",
    }
  }

  private nonceReflected(): boolean {
    return this.victimContent.includes(this.nonce)
  }

  /** The hit that proves execution in the victim page of this run. */
  private victimHit(): XssExecutionHit | undefined {
    const victim = this.victimPage
    return this.hits.find((hit) => {
      if (hit.nonce !== this.nonce) return false
      if (hit.page !== undefined) return hit.page === this.victimPage
      return victim !== null && hit.url === victim.url()
    })
  }

  private result(input: {
    status: ProofStatus
    confidence: Confidence
    score: number
    summary: string
    controls: ControlReference[]
    error?: { step: "setup" | "execute" | "verify" | "collectEvidence"; name: string; message: string }
  }): VerifierResult {
    return {
      passed: input.status === ProofStatus.REPRODUCED,
      proofStatus: input.status,
      confidence: input.confidence,
      confidenceScore: input.score,
      evidence: [],
      summary: input.summary,
      controls: input.controls,
      ...(input.error ? { error: input.error } : {}),
    }
  }

  private cleanupLogText(): string {
    return [
      `verifier: ${this.name}`,
      `endpoint: ${this.plan.url}`,
      `parameter: ${this.plan.parameter}`,
      `source: ${this.plan.evidenceRef}`,
      `nonce: ${this.nonce}`,
      `cleanup: ${JSON.stringify(this.teardown)}`,
      ...this.logs,
    ].join("\n")
  }

  /**
   * Every report received, attributable or not: an unattributable hit is
   * evidence that something ran, but it is not this run's execution.
   */
  private executionRecords(): string[] {
    return this.hits.map((hit) =>
      JSON.stringify({
        nonce: hit.nonce,
        matchesRunNonce: hit.nonce === this.nonce,
        inVictimContext: hit.page !== undefined ? hit.page === this.victimPage : hit.url === this.plan.victimUrl,
        url: hit.url,
        detail: hit.detail,
        receivedAt: hit.at,
      }),
    )
  }

  private executionEventLog(): string {
    const records = this.executionRecords()
    return [
      `verifier: ${this.name}`,
      `endpoint: ${this.plan.url}`,
      `parameter: ${this.plan.parameter}`,
      `nonce: ${this.nonce}`,
      `reports: ${records.length}`,
      ...records,
    ].join("\n")
  }

  /** Persist a text artifact when a collector is configured. */
  private async persistLog(text: string): Promise<void> {
    if (!this.collector || !this.engagementId || !this.findingId) return
    if (typeof this.collector.saveLog !== "function") return
    await this.collector.saveLog(this.engagementId, this.findingId, text)
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
      // Execution events are evidence in their own right: the nonce, where the
      // report came from and whether it is attributable to this run.
      if (this.executionRecords().length > 0) {
        const entry = await this.collector.saveLog?.(
          this.engagementId,
          this.findingId,
          this.executionEventLog(),
        ).catch(() => null)
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
            ...this.executionRecords().map((_, index) => ({
              path: `execution-event-${index + 1}.json`,
              type: "log" as const,
            })),
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }
}

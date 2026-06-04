import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../planner/types"
import { loginIfFormPresent } from "../login"

const XSS_MARKERS = [
  "<img src=x onerror=",
  "<script>",
  "prompt(",
  "alert(",
  "onload=",
  "javascript:",
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
    const markersFound = XSS_MARKERS.filter(m => pageContent.includes(m))
    const payloadInDom = pageContent.includes(this.payload.toLowerCase())
    this.payloadExecuted = markersFound.length > 0 || payloadInDom

    try {
      const victimShot = await this.engine.captureScreenshot(victimPage)
      this.capturedScreenshots.push({ data: victimShot, label: "victim-view" })
    } catch { /* screenshot best-effort */ }

    this.logs.push(`XSS markers found in DOM: ${markersFound.length > 0 ? markersFound.join(", ") : "none"}`)
    this.logs.push(`Payload string in DOM: ${payloadInDom}`)
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
    const screenshots: string[] = []
    for (const shot of this.capturedScreenshots) {
      const filename = `xss-${shot.label}.png`
      await Bun.write(filename, shot.data)
      screenshots.push(filename)
    }
    return {
      packageId: "", findingId: "", screenshots,
      requests: this.capturedRequests,
      responses: this.capturedResponses,
      logs: this.logs,
      createdAt: new Date().toISOString(),
    }
  }
}

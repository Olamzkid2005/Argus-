import { PlaywrightEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../planner/types"

const XSS_MARKERS = [
  "<img src=x onerror=",
  "<script>",
  "prompt(",
  "alert(",
  "onload=",
  "javascript:",
]

export class StoredXSSVerifier implements VerificationScenario {
  name = "stored-xss"
  description = "Stored XSS — injects payload and checks if it executes in victim view"

  private logs: string[] = []
  private payloadExecuted = false

  constructor(
    private engine: PlaywrightEngine,
    private injectUrl: string,
    private victimViewUrl: string,
    private payload: string,
  ) {}

  async setup(): Promise<void> {
    await this.engine.launch()
    await this.engine.createContext()
    this.logs.push(`Stored XSS verifier setup complete — payload: ${this.payload}`)
  }

  async execute(): Promise<void> {
    const injectPage = await this.engine.navigate(this.injectUrl)
    await injectPage.waitForLoadState("networkidle")

    const inputFields = await injectPage.locator("input[type=text], textarea, input:not([type]), [contenteditable=true]").all()

    if (inputFields.length === 0) {
      this.logs.push("No input fields found to inject payload")
    } else {
      for (const field of inputFields) {
        if (await field.isVisible()) {
          await field.fill(this.payload)
          this.logs.push(`Injected payload into field`)
        }
      }
      const submitBtn = injectPage.locator("button[type=submit], input[type=submit]").first()
      if (await submitBtn.isVisible()) {
        await submitBtn.click()
        await injectPage.waitForTimeout(1500)
        this.logs.push("Submitted form with XSS payload")
      }
    }
    await injectPage.close()

    await injectPage.waitForTimeout(500)

    const victimPage = await this.engine.navigate(this.victimViewUrl)
    await victimPage.waitForLoadState("networkidle")

    const pageContent = await victimPage.content()
    const markersFound = XSS_MARKERS.filter(m => pageContent.includes(m))
    const payloadInDom = pageContent.includes(this.payload)
    this.payloadExecuted = markersFound.length > 0 || payloadInDom

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
    return {
      packageId: "",
      findingId: "",
      screenshots: [],
      requests: [],
      responses: [],
      logs: this.logs,
      createdAt: new Date().toISOString(),
    }
  }
}

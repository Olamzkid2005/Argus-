import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../planner/types"
import { loginIfFormPresent, isAccessDenied } from "../login"

export class PrivilegeEscalationVerifier implements VerificationScenario {
  name = "privilege-escalation"
  description = "Privilege Escalation — verifies access controls on high-privilege endpoints"

  private logs: string[] = []
  private highPrivAccessible = false
  private httpStatus = 0

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private highPrivEndpoint: string,
    private lowPrivCreds: { username: string; password: string },
  ) {}

  async setup(): Promise<void> {
    await this.engine.launch()
    await this.engine.createContext()
    this.logs.push("Privilege escalation verifier setup complete")
  }

  async execute(): Promise<void> {
    const endpointUrl = `${this.targetUrl.replace(/\/+$/, "")}/${this.highPrivEndpoint.replace(/^\//, "")}`

    const page = await this.engine.navigate(this.targetUrl)
    await loginIfFormPresent(page, this.lowPrivCreds)
    if (this.lowPrivCreds.username) this.logs.push(`Logged in as low-priv user ${this.lowPrivCreds.username}`)

    const response = await page.goto(endpointUrl, { waitUntil: "networkidle" })
    this.httpStatus = response?.status() ?? 0

    try {
      const bodyText = await page.locator("body").innerText()
      this.highPrivAccessible = !isAccessDenied(bodyText) && this.httpStatus !== 403 && this.httpStatus !== 401
    } catch {
      this.highPrivAccessible = false
    }

    this.logs.push(`High-priv endpoint ${endpointUrl}: HTTP ${this.httpStatus}, accessible: ${this.highPrivAccessible}`)
    this.logs.push(`Privilege escalation ${this.highPrivAccessible ? "POSSIBLE" : "not detected"}`)

    await page.close()
  }

  async verify(): Promise<VerifierResult> {
    return {
      passed: this.highPrivAccessible,
      confidence: this.highPrivAccessible && this.httpStatus === 200 ? Confidence.HIGH : Confidence.LOW,
      evidence: [],
      summary: this.highPrivAccessible
        ? `Privilege escalation: low-priv user accessed ${this.highPrivEndpoint} (HTTP ${this.httpStatus})`
        : `Access control enforced for ${this.highPrivEndpoint} (HTTP ${this.httpStatus})`,
    }
  }

  async collectEvidence(): Promise<EvidencePackage> {
    return {
      packageId: "", findingId: "", screenshots: [], requests: [], responses: [],
      logs: this.logs,
      createdAt: new Date().toISOString(),
    }
  }
}

import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../planner/types"
import { loginIfFormPresent, isAccessDenied } from "../login"

export class BOLAVerifier implements VerificationScenario {
  name = "bola"
  description = "Broken Object Level Authorization — verifies resource access between different users"

  private logs: string[] = []
  private userAResourceAccessible = false
  private userBResourceAccessible = false

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private resourcePath: string,
    private userACreds: { username: string; password: string },
    private userBCreds: { username: string; password: string },
  ) {}

  async setup(): Promise<void> {
    await this.engine.launch()
    await this.engine.createContext()
    this.logs.push("BOLA verifier setup complete")
  }

  async execute(): Promise<void> {
    const resourceUrl = `${this.targetUrl.replace(/\/+$/, "")}/${this.resourcePath.replace(/^\//, "")}`

    this.userAResourceAccessible = await this.checkAccess(resourceUrl, this.userACreds, "User A")
    this.userBResourceAccessible = await this.checkAccess(resourceUrl, this.userBCreds, "User B")
    this.logs.push(`User A access: ${this.userAResourceAccessible}, User B access: ${this.userBResourceAccessible}`)
  }

  async verify(): Promise<VerifierResult> {
    const passed = this.userAResourceAccessible && this.userBResourceAccessible

    return {
      passed,
      confidence: passed ? Confidence.HIGH : Confidence.LOW,
      evidence: [],
      summary: passed
        ? `BOLA confirmed: User B could access User A's resource at ${this.resourcePath}`
        : `BOLA not detected for ${this.resourcePath}`,
    }
  }

  async collectEvidence(): Promise<EvidencePackage> {
    return {
      packageId: "", findingId: "", screenshots: [], requests: [], responses: [],
      logs: this.logs,
      createdAt: new Date().toISOString(),
    }
  }

  private async checkAccess(resourceUrl: string, creds: { username: string; password: string }, label: string): Promise<boolean> {
    this.logs.push(`Attempting to access ${resourceUrl} as ${label} (${creds.username})`)
    const page = await this.engine.navigate(this.targetUrl)
    await loginIfFormPresent(page, creds)
    await page.goto(resourceUrl, { waitUntil: "networkidle" })

    let accessible: boolean
    try {
      const body = await page.locator("body").innerText()
      accessible = page.url() === resourceUrl || !isAccessDenied(body)
    } catch {
      accessible = false
    }

    await page.close()
    return accessible
  }
}

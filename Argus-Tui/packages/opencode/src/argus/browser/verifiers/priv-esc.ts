import { PlaywrightEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../planner/types"

const FORBIDDEN_PATTERNS = [
  "403", "401", "forbidden", "access denied", "unauthorized",
  "not authorized", "insufficient permissions", "access denied",
]

export class PrivilegeEscalationVerifier implements VerificationScenario {
  name = "privilege-escalation"
  description = "Privilege Escalation — verifies access controls on high-privilege endpoints"

  private logs: string[] = []
  private highPrivAccessible = false
  private httpStatus = 0

  constructor(
    private engine: PlaywrightEngine,
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
    await this.loginAsLowPriv(page)

    const response = await page.goto(endpointUrl, { waitUntil: "networkidle" })
    this.httpStatus = response?.status() ?? 0

    const bodyText = await page.locator("body").innerText().catch(() => "")
    const denied = FORBIDDEN_PATTERNS.some(p => bodyText.toLowerCase().includes(p)) || this.httpStatus === 403 || this.httpStatus === 401

    this.highPrivAccessible = !denied

    this.logs.push(`High-priv endpoint ${endpointUrl}: HTTP ${this.httpStatus}, body denied pattern: ${denied}`)
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
      packageId: "",
      findingId: "",
      screenshots: [],
      requests: [],
      responses: [],
      logs: this.logs,
      createdAt: new Date().toISOString(),
    }
  }

  private async loginAsLowPriv(page: Awaited<ReturnType<PlaywrightEngine["navigate"]>>): Promise<void> {
    const content = await page.content()
    if (!content.includes("password") && !content.includes("login") && !content.includes("sign in")) return

    const inputs = await page.locator("input[type=password]").count()
    if (inputs === 0) return

    const usernameInput = page.locator("input[type=text], input[name=username], input[name=email], input[type=email]").first()
    const passwordInput = page.locator("input[type=password]").first()

    if (await usernameInput.isVisible()) await usernameInput.fill(this.lowPrivCreds.username)
    if (await passwordInput.isVisible()) {
      await passwordInput.fill(this.lowPrivCreds.password)
      await passwordInput.press("Enter")
    }

    await page.waitForTimeout(1000)
    this.logs.push(`Logged in as low-priv user ${this.lowPrivCreds.username}`)
  }
}

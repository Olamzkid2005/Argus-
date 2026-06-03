import { PlaywrightEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../planner/types"

export class BOLAVerifier implements VerificationScenario {
  name = "bola"
  description = "Broken Object Level Authorization — verifies resource access between different users"

  private logs: string[] = []
  private userAResourceAccessible = false
  private userBResourceAccessible = false

  constructor(
    private engine: PlaywrightEngine,
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

    this.logs.push(`Attempting to access ${resourceUrl} as User A (${this.userACreds.username})`)
    const pageA = await this.engine.navigate(this.targetUrl)
    await this.loginIfRequired(pageA, this.userACreds)
    await pageA.goto(resourceUrl, { waitUntil: "networkidle" })
    this.userAResourceAccessible = pageA.url() === resourceUrl || await pageA.locator("body").innerText().then(t => !t.includes("403") && !t.includes("401") && !t.includes("access denied")).catch(() => false)
    await pageA.close()

    this.logs.push(`Attempting to access ${resourceUrl} as User B (${this.userBCreds.username})`)
    const pageB = await this.engine.navigate(this.targetUrl)
    await this.loginIfRequired(pageB, this.userBCreds)
    await pageB.goto(resourceUrl, { waitUntil: "networkidle" })
    this.userBResourceAccessible = pageB.url() === resourceUrl || await pageB.locator("body").innerText().then(t => !t.includes("403") && !t.includes("401") && !t.includes("access denied")).catch(() => false)
    await pageB.close()

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
      packageId: "",
      findingId: "",
      screenshots: [],
      requests: [],
      responses: [],
      logs: this.logs,
      createdAt: new Date().toISOString(),
    }
  }

  private async loginIfRequired(page: Awaited<ReturnType<PlaywrightEngine["navigate"]>>, creds: { username: string; password: string }): Promise<void> {
    const content = await page.content()
    if (!content.includes("password") && !content.includes("login") && !content.includes("sign in")) return

    const inputs = await page.locator("input[type=password]").count()
    if (inputs === 0) return

    const usernameInput = page.locator("input[type=text], input[name=username], input[name=email], input[type=email]").first()
    const passwordInput = page.locator("input[type=password]").first()
    const submitButton = page.locator("button[type=submit], input[type=submit]").first()

    if (await usernameInput.isVisible()) await usernameInput.fill(creds.username)
    if (await passwordInput.isVisible()) {
      await passwordInput.fill(creds.password)
      await passwordInput.press("Enter")
    } else if (await submitButton.isVisible()) {
      await submitButton.click()
    }

    await page.waitForTimeout(1000)
    this.logs.push(`Logged in as ${creds.username}`)
  }
}

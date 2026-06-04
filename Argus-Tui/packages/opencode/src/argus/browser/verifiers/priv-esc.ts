import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import { loginIfFormPresent, isAccessDenied } from "../login"

export class PrivilegeEscalationVerifier implements VerificationScenario {
  name = "privilege-escalation"
  description = "Privilege Escalation — verifies access controls on high-privilege endpoints"

  private logs: string[] = []
  private accessibleEndpoints: { endpoint: string; status: number; accessible: boolean }[] = []
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private highPrivEndpoints: string[],
    private lowPrivCreds: { username: string; password: string },
  ) {}

  async setup(): Promise<void> {
    if (!this.lowPrivCreds.username || !this.lowPrivCreds.password) {
      this.logs.push("WARNING: Low-privilege credentials are empty — authentication may fail")
    }
    await this.engine.launch()
    await this.engine.createContext()
    this.logs.push("Privilege escalation verifier setup complete")
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
  }

  async execute(): Promise<void> {
    for (const ep of this.highPrivEndpoints) {
      const endpointUrl = `${this.targetUrl.replace(/\/+$/, "")}/${ep.replace(/^\//, "")}`
      const page = await this.engine.navigate(this.targetUrl)
      await loginIfFormPresent(page, this.lowPrivCreds)
      if (this.lowPrivCreds.username) this.logs.push(`Logged in as low-priv user ${this.lowPrivCreds.username}`)

      this.capturedRequests.push(`GET ${endpointUrl} [low-priv as ${this.lowPrivCreds.username}]`)

      const response = await page.goto(endpointUrl, { waitUntil: "networkidle" })
      const httpStatus = response?.status() ?? 0
      this.capturedResponses.push(`Endpoint ${ep}: HTTP ${httpStatus}`)

      try {
        const shot = await this.engine.captureScreenshot(page)
        this.capturedScreenshots.push({ data: shot, label: `endpoint-${ep.replace(/[^a-zA-Z0-9]/g, "-")}` })
      } catch { /* screenshot best-effort */ }

      let accessible: boolean
      try {
        const bodyText = await page.locator("body").innerText()
        accessible = !isAccessDenied(bodyText) && httpStatus !== 403 && httpStatus !== 401
      } catch {
        accessible = false
      }

      this.accessibleEndpoints.push({ endpoint: ep, status: httpStatus, accessible })
      this.logs.push(`High-priv endpoint ${endpointUrl}: HTTP ${httpStatus}, accessible: ${accessible}`)

      await page.close()
    }

    const anyAccessible = this.accessibleEndpoints.some(e => e.accessible)
    this.logs.push(`Privilege escalation ${anyAccessible ? "POSSIBLE" : "not detected"}`)
  }

  async verify(): Promise<VerifierResult> {
    const anyAccessible = this.accessibleEndpoints.some(e => e.accessible)
    const some200 = this.accessibleEndpoints.some(e => e.status === 200 && e.accessible)
    const summary = anyAccessible
      ? `Privilege escalation: low-priv user accessed ${this.accessibleEndpoints.filter(e => e.accessible).map(e => e.endpoint).join(", ")}`
      : `Access control enforced for all ${this.highPrivEndpoints.length} endpoint(s)`

    return {
      passed: anyAccessible,
      confidence: anyAccessible && some200 ? Confidence.HIGH : Confidence.LOW,
      evidence: [],
      summary,
    }
  }

  async collectEvidence(): Promise<EvidencePackage> {
    const artifacts: import("../../shared/types").ArtifactRef[] = []
    for (const shot of this.capturedScreenshots) {
      const filename = `priv-esc-${shot.label}.png`
      await Bun.write(filename, shot.data)
      artifacts.push({ path: filename, type: "screenshot" })
    }
    for (const req of this.capturedRequests) {
      artifacts.push({ path: req, type: "request" })
    }
    for (const res of this.capturedResponses) {
      artifacts.push({ path: res, type: "response" })
    }
    return {
      packageId: "", findingId: "",
      artifacts,
      packageHash: "",
      createdAt: new Date().toISOString(),
    }
  }
}

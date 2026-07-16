import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import { authenticateSession, isAccessDenied, detectAuthChallenge, logAuthChallenge } from "../login"
import type { AuthTokens } from "../login"
import type { EvidenceCollector } from "../../evidence/collector"
import type { CredentialEntry } from "../../engagement/credentials"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

export class PrivilegeEscalationVerifier implements VerificationScenario {
  name = "privilege-escalation"
  description = "Privilege Escalation — verifies access controls on high-privilege endpoints"

  private logs: string[] = []
  private accessibleEndpoints: { endpoint: string; status: number; accessible: boolean; baselineDenied: boolean }[] = []
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private harDir: string | null = null
  private loginFailed = false

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private highPrivEndpoints: string[],
    private lowPrivCreds: CredentialEntry,
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    if (!this.lowPrivCreds.username || !this.lowPrivCreds.password) {
      this.logs.push("WARNING: Low-privilege credentials are empty — authentication may fail")
    }
    await this.engine.launch()
    // Create a temp directory for HAR capture
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    await this.engine.createContext({ harDir: this.harDir } as any)
    this.logs.push("Privilege escalation verifier setup complete")
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

  /** Check endpoint access without auth as a baseline */
  private async checkBaseline(endpointUrl: string): Promise<boolean> {
    const context = await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await context.newPage()
    try {
      const response = await page.goto(endpointUrl, { waitUntil: "networkidle", timeout: 30000 })
      const httpStatus = response?.status() ?? 0
      if (httpStatus === 401 || httpStatus === 403) return false
      const bodyText = await page.locator("body").innerText()
      return !isAccessDenied(bodyText)
    } catch {
      return false
    } finally {
      await page.close()
      await context.close()
    }
  }

  async execute(): Promise<void> {
    // Step 1: Baseline checks — each endpoint without auth
    // Step 2: Login once, then check all endpoints with session shared
    const page = await this.engine.navigate(this.targetUrl)
    // Build AuthTokens from the full CredentialEntry for OAuth/SSO fallback.
    // Gap 2.6: When the credential file includes authToken or authCookies,
    // they are passed to authenticateSession() so it can fall through to
    // token/cookie injection when form-based login hits an OAuth/SSO page.
    const authTokens: AuthTokens | undefined =
      this.lowPrivCreds.authToken || (this.lowPrivCreds.authCookies && this.lowPrivCreds.authCookies.length > 0)
        ? {
            bearerToken: this.lowPrivCreds.authToken,
            cookies: this.lowPrivCreds.authCookies,
          }
        : undefined

    // Phase 3.4.2: Capture auth challenges during login.
    // Uses authenticateSession() which tries form login first, then falls
    // back to token/cookie injection for OAuth/SSO pages (Gap 2.6).
    const loginSuccess = await authenticateSession(
      page,
      this.lowPrivCreds,
      authTokens,
      undefined, // context — passed when cookies are available
      (challenge) => {
        logAuthChallenge(challenge, (line) => this.logs.push(line))
      },
    )
    if (loginSuccess) {
      if (this.lowPrivCreds.username) this.logs.push(`Logged in as low-priv user ${this.lowPrivCreds.username}`)
    } else {
      const challenge = await detectAuthChallenge(page)
      if (challenge) {
        logAuthChallenge(challenge, (line) => this.logs.push(line))
      }
      this.logs.push(`Login failed for ${this.lowPrivCreds.username} — aborting privilege escalation check (fail-closed)`)
      this.loginFailed = true
      await page.close()
      return
    }

    for (const ep of this.highPrivEndpoints) {
      const endpointUrl = `${this.targetUrl.replace(/\/+$/, "")}/${ep.replace(/^\//, "")}`

      // Baseline: check without auth first
      const baselineDenied = !(await this.checkBaseline(endpointUrl))
      this.logs.push(`Baseline for ${ep}: auth required = ${baselineDenied}`)

      this.capturedRequests.push(`GET ${endpointUrl} [low-priv as ${this.lowPrivCreds.username}]`)

      const response = await page.goto(endpointUrl, { waitUntil: "networkidle", timeout: 30000 })
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

      this.accessibleEndpoints.push({ endpoint: ep, status: httpStatus, accessible, baselineDenied })
      this.logs.push(`High-priv endpoint ${endpointUrl}: HTTP ${httpStatus}, accessible: ${accessible}, baseline denied: ${baselineDenied}`)
    }

    await page.close()

    const anyEscalation = this.accessibleEndpoints.some(e => e.accessible && e.baselineDenied)
    this.logs.push(`Privilege escalation ${anyEscalation ? "POSSIBLE" : "not detected"}`)
  }

  async verify(): Promise<VerifierResult> {
    // If login failed, report as skipped (not a clean "access control enforced" result)
    if (this.loginFailed) {
      return {
        passed: false,
        confidence: Confidence.INFORMATIONAL,
        evidence: [],
        summary: `Privilege escalation skipped — login failed, endpoint access checks could not be performed`,
      }
    }

    const escalationEndpoints = this.accessibleEndpoints.filter(e => e.accessible && e.baselineDenied)
    const hasEscalation = escalationEndpoints.length > 0
    const some200 = escalationEndpoints.some(e => e.status === 200)
    const summary = hasEscalation
      ? `Privilege escalation: low-priv user accessed ${escalationEndpoints.map(e => e.endpoint).join(", ")}`
      : `Access control enforced for all ${this.highPrivEndpoints.length} endpoint(s)`

    return {
      passed: hasEscalation,
      confidence: hasEscalation && some200 ? Confidence.HIGH : Confidence.LOW,
      evidence: [],
      summary,
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
      const { createHash } = await import("crypto")
      const hashInput = collectedArtifacts.map((a) => a.hash || a.path).join("")
      computedHash = createHash("sha256").update(hashInput).digest("hex")
    }

    const artifacts: import("../../shared/types").ArtifactRef[] = []
    for (const shot of this.capturedScreenshots) {
      const filename = `priv-esc-${shot.label}.png`
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
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }
}

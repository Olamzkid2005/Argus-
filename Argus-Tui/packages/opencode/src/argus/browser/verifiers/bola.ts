import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import { authenticateSession, isAccessDenied, detectAuthChallenge, logAuthChallenge } from "../login"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

export class BOLAVerifier implements VerificationScenario {
  name = "bola"
  description = "Broken Object Level Authorization — verifies resource access between different users"

  private logs: string[] = []
  private userAResourceAccessible = false
  private userBResourceAccessible = false
  private resourceRequiresAuth = false
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private resourceUrl = ""
  private harDir: string | null = null
  private loginFailed = false

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private resourcePath: string,
    private userACreds: { username: string; password: string },
    private userBCreds: { username: string; password: string },
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    if (!this.userACreds.username || !this.userACreds.password) {
      this.logs.push("WARNING: User A credentials are empty — authentication may fail")
    }
    if (!this.userBCreds.username || !this.userBCreds.password) {
      this.logs.push("WARNING: User B credentials are empty — authentication may fail")
    }
    if (this.resourcePath === this.targetUrl.replace(/\/+$/, "")) {
      this.logs.push("WARNING: resourcePath and targetUrl are identical — BOLA check will be ineffective")
    }
    this.resourceUrl = `${this.targetUrl.replace(/\/+$/, "")}/${this.resourcePath.replace(/^\//, "")}`
    await this.engine.launch()
    // Create a temp directory for HAR capture
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    this.logs.push(`BOLA verifier setup complete — HAR dir: ${this.harDir}`)
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

  async execute(): Promise<void> {
    // Baseline: check if the resource is accessible without auth
    this.resourceRequiresAuth = !(await this.checkAccessUnauthenticated(this.resourceUrl))
    this.logs.push(`Resource requires auth: ${this.resourceRequiresAuth}`)

    this.userAResourceAccessible = await this.checkAccess(this.resourceUrl, this.userACreds, "User A")
    this.userBResourceAccessible = await this.checkAccess(this.resourceUrl, this.userBCreds, "User B")
    this.logs.push(`User A access: ${this.userAResourceAccessible}, User B access: ${this.userBResourceAccessible}`)
  }

  async verify(): Promise<VerifierResult> {
    // If login failed, report as skipped (not a clean "not vulnerable" result)
    if (this.loginFailed) {
      return {
        passed: false,
        confidence: Confidence.INFORMATIONAL,
        evidence: [],
        summary: `BOLA skipped — login failed for one or both users, access check could not complete`,
      }
    }

    // BOLA only meaningful if the resource is actually access-controlled
    const passed = this.resourceRequiresAuth && this.userAResourceAccessible && this.userBResourceAccessible

    return {
      passed,
      confidence: passed ? Confidence.HIGH : this.resourceRequiresAuth ? Confidence.LOW : Confidence.INFORMATIONAL,
      evidence: [],
      summary: !this.resourceRequiresAuth
        ? `BOLA skipped — ${this.resourcePath} is publicly accessible (no auth required)`
        : passed
          ? `BOLA confirmed: User B could access User A's resource at ${this.resourcePath}`
          : `BOLA not detected for ${this.resourcePath} (resource requires auth and User B denied)`,
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
            ...this.capturedScreenshots.map((s) => ({ path: s.label, type: "screenshot" as const })),
            ...this.capturedRequests.map((r) => ({ path: r, type: "request" as const })),
            ...this.capturedResponses.map((r) => ({ path: r, type: "response" as const })),
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }

  /** Expose captured screenshot buffers for EvidenceCollector persistence */
  getScreenshotBuffers(): { label: string; data: Buffer }[] {
    return this.capturedScreenshots
  }

  /** Check resource access without authentication as a baseline */
  private async checkAccessUnauthenticated(resourceUrl: string): Promise<boolean> {
    const context = await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await context.newPage()
    try {
      this.capturedRequests.push(`GET ${resourceUrl} [unauthenticated baseline]`)
      const response = await page.goto(resourceUrl, { waitUntil: "networkidle", timeout: 30000 })
      const httpStatus = response?.status() ?? 0
      this.capturedResponses.push(`[unauthenticated baseline] ${resourceUrl}: HTTP ${httpStatus}`)
      try {
        const shot = await this.engine.captureScreenshot(page)
        this.capturedScreenshots.push({ data: shot, label: "unauthenticated-baseline" })
      } catch { /* screenshot best-effort */ }
      if (httpStatus === 401 || httpStatus === 403) return false
      const bodyText = await page.locator("body").innerText().catch(() => "")
      if (isAccessDenied(bodyText)) return false
      return true
    } catch {
      return false
    } finally {
      await page.close()
      await context.close()
    }
  }

  private async checkAccess(resourceUrl: string, creds: { username: string; password: string }, label: string): Promise<boolean> {
    this.logs.push(`Attempting to access ${resourceUrl} as ${label} (${creds.username})`)
    const context = await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await context.newPage()
    try {
      await page.goto(this.targetUrl, { waitUntil: "networkidle", timeout: 30000 })
      this.capturedRequests.push(`GET ${this.targetUrl} [${label} login]`)

      // Phase 3.4.2: Capture auth challenges during login.
      // Uses authenticateSession() which tries form login first, then falls
      // back to token/cookie injection for OAuth/SSO pages (Gap 2.6).
      const loginSuccess = await authenticateSession(
        page,
        creds,
        undefined, // authTokens — injected from CredentialStore when available
        context,
        (challenge) => {
          logAuthChallenge(challenge, (line) => this.logs.push(line))
        },
      )
      if (!loginSuccess) {
        const challenge = await detectAuthChallenge(page)
        if (challenge) {
          logAuthChallenge(challenge, (line) => this.logs.push(line))
        }
        this.logs.push(`Login failed for ${creds.username} — aborting access check (fail-closed)`)
        this.loginFailed = true
        return false
      }

      // Navigate directly to the resource page after login.
      // Do NOT re-navigate to targetUrl first — that would reload the login page
      // and potentially invalidate the freshly-set session.
      const resourceResponse = await page.goto(resourceUrl, { waitUntil: "networkidle", timeout: 30000 })
      this.capturedRequests.push(`GET ${resourceUrl} [${label}]`)
      this.capturedResponses.push(`[${label}] Resource page status: ${resourceResponse?.status() ?? "unknown"}`)

      try {
        const shot = await this.engine.captureScreenshot(page)
        this.capturedScreenshots.push({ data: shot, label: `${label}-resource` })
      } catch { /* screenshot best-effort */ }

      let accessible: boolean
      try {
        const body = await page.locator("body").innerText()
        accessible = page.url() === resourceUrl || !isAccessDenied(body)
      } catch {
        accessible = false
      }

      return accessible
    } finally {
      await page.close()
      await context.close()
    }
  }
}

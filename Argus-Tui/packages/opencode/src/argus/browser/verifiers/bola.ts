import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence, ProofStatus } from "../../shared/types"
import type { ControlReference } from "../../shared/types"
import { authenticateSession, isAccessDenied, detectAuthChallenge, logAuthChallenge } from "../login"
import type { AuthTokens } from "../login"
import type { EvidenceCollector } from "../../evidence/collector"
import type { CredentialEntry } from "../../engagement/credentials"
import { ObjectAccessPlanError } from "../bola-plan"
import type { ObjectAccessIdentity, ObjectAccessPlan } from "../bola-plan"
import { createHash, randomUUID } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

/** One request made as one identity, with everything needed to judge it. */
interface ResourceFetch {
  loginSucceeded: boolean
  accessible: boolean
  httpStatus: number
  body: string
  bodySignature: string
  denialText: boolean
}

/**
 * Broken Object Level Authorization — proves that a second real identity can
 * read a resource that belongs to the first.
 *
 * Stage 4.2. The verifier no longer accepts a path string plus any two
 * credential objects: it is constructed from the validated `ObjectAccessPlan`
 * from `objectAccessPlan()`, so fabricated or missing identities cannot reach
 * it. Before the cross-user attempt it establishes the controls the plan
 * requires — the resource is protected (unauthenticated request denied), the
 * login mechanism rejects a wrong password, the owner really can read the
 * resource — and it only confirms when the accessor receives the owner's
 * unique data. A secure twin (accessor denied) is explicitly not confirmed,
 * and a 200 that returns someone else's/another page is inconclusive, not a
 * finding.
 */
export class BOLAVerifier implements VerificationScenario {
  name = "bola"
  description = "Broken Object Level Authorization — verifies resource access between different users"

  private logs: string[] = []
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private resourceUrl = ""
  private harDir: string | null = null

  private unauthenticatedBlocked = false
  private invalidCredentialsRejected = false
  private loginFailedFor: string | null = null

  private ownerFetch: ResourceFetch | null = null
  private accessorFetch: ResourceFetch | null = null

  private controls: ControlReference[] = []

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private plan: ObjectAccessPlan,
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {
    this.resourceUrl = plan.resource.url
  }

  async setup(): Promise<void> {
    if (!this.resourceUrl) {
      throw new ObjectAccessPlanError(
        "unstructured-resource",
        "BOLA verifier requires a discovered resource URL",
      )
    }
    await this.engine.launch()
    // Create a temp directory for HAR capture
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    this.logs.push(
      `BOLA verifier setup complete — ${this.plan.owner.role} owns ${this.resourceUrl}, ` +
        `${this.plan.accessor.role} attempts access — HAR dir: ${this.harDir}`,
    )
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
    // Control 1: the resource must actually be protected. A public page has no
    // object-level policy to violate, so it cannot be used as a BOLA proof.
    const anonymous = await this.fetchUnauthenticated(this.resourceUrl)
    this.unauthenticatedBlocked = !anonymous.accessible
    this.controls.push({
      kind: "unauthenticated-baseline",
      description: `GET ${this.resourceUrl} without a session`,
      reference: this.resourceUrl,
      outcome: this.unauthenticatedBlocked
        ? `denied (HTTP ${anonymous.httpStatus || "no response"}${anonymous.denialText ? ", denial page" : ""})`
        : `served without authentication (HTTP ${anonymous.httpStatus || "no response"})`,
    })
    this.logs.push(`Unauthenticated access blocked: ${this.unauthenticatedBlocked}`)

    // Control 2: the login mechanism must reject a wrong password. Otherwise a
    // "successful" login proves nothing about the identity we think we used.
    this.invalidCredentialsRejected = await this.invalidCredentialControl(this.plan.owner)
    this.controls.push({
      kind: "invalid-credentials",
      description: `login as ${this.plan.owner.credentials.username} with a wrong password`,
      reference: this.plan.owner.role,
      outcome: this.invalidCredentialsRejected ? "rejected" : "accepted a wrong password",
    })

    // Control 3: the owner can read their own resource (ownership established).
    this.ownerFetch = await this.fetchAs(this.resourceUrl, this.plan.owner, "owner")
    if (!this.ownerFetch.loginSucceeded) {
      this.loginFailedFor = this.plan.owner.credentials.username
    }
    const ownerMarkerSeen = this.markerSeen(this.ownerFetch)
    this.controls.push({
      kind: "owner-resource-access",
      description: `${this.plan.owner.role} reads their own resource`,
      reference: this.resourceUrl,
      outcome: !this.ownerFetch.loginSucceeded
        ? "login failed"
        : this.ownerFetch.accessible
          ? ownerMarkerSeen
            ? "received owner data"
            : "reached the resource (no owner marker seen)"
          : "denied",
    })

    // The cross-user attempt comes last, after every control above.
    this.accessorFetch = await this.fetchAs(this.resourceUrl, this.plan.accessor, "accessor")
    if (!this.accessorFetch.loginSucceeded) {
      this.loginFailedFor = this.plan.accessor.credentials.username
    }
    this.controls.push({
      kind: "accessor-resource-access",
      description: `${this.plan.accessor.role} requests the owner's resource`,
      reference: this.resourceUrl,
      outcome: !this.accessorFetch.loginSucceeded
        ? "login failed"
        : this.accessorFetch.accessible
          ? `served (HTTP ${this.accessorFetch.httpStatus || "no response"})`
          : `denied (HTTP ${this.accessorFetch.httpStatus || "no response"})`,
    })

    this.logs.push(
      `Owner access: ${this.ownerFetch.accessible}${ownerMarkerSeen ? " (marker seen)" : ""}; ` +
        `accessor access: ${this.accessorFetch.accessible}`,
    )
  }

  async verify(): Promise<VerifierResult> {
    const controls = this.controls

    // A check that could not run is inconclusive — not a clean "not vulnerable".
    if (this.loginFailedFor) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: `BOLA inconclusive — login failed for ${this.loginFailedFor}, access check could not complete`,
        controls,
        error: {
          step: "execute",
          name: "LoginFailed",
          message: `authentication failed for ${this.loginFailedFor}`,
        },
      })
    }

    if (!this.unauthenticatedBlocked) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: `BOLA inconclusive — ${this.resourceUrl} is served without authentication, so there is no access-control policy to test`,
        controls,
      })
    }

    if (!this.invalidCredentialsRejected) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: "BOLA inconclusive — the login form accepted an invalid password, so the sessions cannot be trusted",
        controls,
      })
    }

    if (!this.ownerFetch?.accessible) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: `BOLA inconclusive — ${this.plan.owner.role} could not read their own resource, so ownership was not established`,
        controls,
      })
    }

    if (!this.markerSeen(this.ownerFetch)) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0,
        summary: `BOLA inconclusive — the owner's page did not contain the expected unique data, so the resource was not identified`,
        controls,
      })
    }

    const accessor = this.accessorFetch!
    if (!accessor.accessible) {
      // The secure twin: the second identity is denied. Never confirmed.
      return this.result({
        status: ProofStatus.NOT_REPRODUCED,
        confidence: Confidence.LOW,
        score: 0.3,
        summary: `BOLA not detected for ${this.resourceUrl} — ${this.plan.accessor.role} was denied access to ${this.plan.owner.role}'s resource`,
        controls,
      })
    }

    // A 200 is not proof: the accessor must receive the *owner's* data.
    if (!this.accessorSawOwnerData()) {
      return this.result({
        status: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        score: 0.1,
        summary: `BOLA inconclusive — ${this.plan.accessor.role} received a different response than ${this.plan.owner.role}; object access was not demonstrated`,
        controls,
      })
    }

    return this.result({
      status: ProofStatus.REPRODUCED,
      confidence: Confidence.HIGH,
      score: 0.9,
      summary: `BOLA confirmed: ${this.plan.accessor.role} received ${this.plan.owner.role}'s protected data at ${this.resourceUrl}`,
      controls,
    })
  }

  private result(input: {
    status: ProofStatus
    confidence: Confidence
    score: number
    summary: string
    controls: ControlReference[]
    error?: { step: "setup" | "execute" | "verify" | "collectEvidence"; name: string; message: string }
  }): VerifierResult {
    return {
      passed: input.status === ProofStatus.REPRODUCED,
      proofStatus: input.status,
      confidence: input.confidence,
      confidenceScore: input.score,
      evidence: [],
      summary: input.summary,
      controls: input.controls,
      ...(input.error ? { error: input.error } : {}),
    }
  }

  private markerSeen(fetch: ResourceFetch | null): boolean {
    if (!fetch?.accessible) return false
    const marker = this.plan.resource.ownerMarker
    if (marker) return fetch.body.includes(marker)
    // Without an explicit marker, "owner data" means a non-trivial resource
    // page — an empty body establishes nothing.
    return fetch.body.trim().length >= 20
  }

  /**
   * The accessor must have received the owner's unique data: the same resource
   * content, or a page containing the owner's marker.
   */
  private accessorSawOwnerData(): boolean {
    const owner = this.ownerFetch!
    const accessor = this.accessorFetch!
    if (!accessor.accessible) return false
    const marker = this.plan.resource.ownerMarker
    if (marker) return accessor.body.includes(marker)
    return (
      accessor.bodySignature !== "" &&
      accessor.bodySignature === owner.bodySignature &&
      accessor.body.trim().length >= 20
    )
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

  /** GET the resource with no session at all. */
  private async fetchUnauthenticated(resourceUrl: string): Promise<ResourceFetch> {
    const context = await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await context.newPage()
    try {
      this.capturedRequests.push(`GET ${resourceUrl} [unauthenticated baseline]`)
      const response = await page.goto(resourceUrl, { waitUntil: "networkidle", timeout: 30000 })
      const httpStatus = response?.status() ?? 0
      this.capturedResponses.push(`[unauthenticated baseline] ${resourceUrl}: HTTP ${httpStatus}`)
      const body = await page.locator("body").innerText().catch(() => "")
      const denialText = isAccessDenied(body)
      const denied = httpStatus === 401 || httpStatus === 403 || denialText
      await this.screenshot(page, "unauthenticated-baseline")
      return {
        loginSucceeded: true,
        accessible: !denied,
        httpStatus,
        body,
        bodySignature: bodySignature(body),
        denialText,
      }
    } catch {
      // A resource that cannot be fetched anonymously is not accessible.
      return { loginSucceeded: true, accessible: false, httpStatus: 0, body: "", bodySignature: "", denialText: false }
    } finally {
      await page.close()
      await context.close()
    }
  }

  /**
   * Attempt a login with a deliberately wrong password. It must fail; if the
   * form accepts it, no later session can be attributed to a real identity.
   */
  private async invalidCredentialControl(identity: ObjectAccessIdentity): Promise<boolean> {
    if (!identity.credentials.password && !identity.credentials.authToken) {
      // Token/cookie-only identities have no password to corrupt.
      return true
    }
    const context = await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await context.newPage()
    try {
      await page.goto(this.targetUrl, { waitUntil: "networkidle", timeout: 30000 })
      const bogus: CredentialEntry = {
        ...identity.credentials,
        password: `${identity.credentials.password}-argus-invalid-${Date.now()}`,
        authToken: undefined,
        authCookies: undefined,
      }
      this.capturedRequests.push(`POST login as ${identity.credentials.username} [invalid-credential control]`)
      const accepted = await authenticateSession(page, bogus, undefined, context, () => {})
      this.capturedResponses.push(
        `[invalid-credential control] ${identity.credentials.username}: ${accepted ? "ACCEPTED" : "rejected"}`,
      )
      return !accepted
    } catch {
      // An error during the bogus login means it did not authenticate.
      return true
    } finally {
      await page.close()
      await context.close()
    }
  }

  /** Log in as one identity in its own context and fetch the resource. */
  private async fetchAs(
    resourceUrl: string,
    identity: ObjectAccessIdentity,
    label: string,
  ): Promise<ResourceFetch> {
    const creds = identity.credentials
    this.logs.push(`Attempting to access ${resourceUrl} as ${label} (${creds.username})`)
    const context = await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await context.newPage()
    try {
      await page.goto(this.targetUrl, { waitUntil: "networkidle", timeout: 30000 })
      this.capturedRequests.push(`GET ${this.targetUrl} [${label} login]`)

      const authTokens: AuthTokens | undefined =
        creds.authToken || (creds.authCookies && creds.authCookies.length > 0)
          ? {
              bearerToken: creds.authToken,
              cookies: creds.authCookies,
            }
          : undefined

      const loginSuccess = await authenticateSession(
        page,
        creds,
        authTokens,
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
        return { loginSucceeded: false, accessible: false, httpStatus: 0, body: "", bodySignature: "", denialText: false }
      }

      const resourceResponse = await page.goto(resourceUrl, { waitUntil: "networkidle", timeout: 30000 })
      const httpStatus = resourceResponse?.status() ?? 0
      this.capturedRequests.push(`GET ${resourceUrl} [${label}]`)
      this.capturedResponses.push(`[${label}] Resource page status: ${httpStatus}`)

      const body = await page.locator("body").innerText().catch(() => "")
      const denialText = isAccessDenied(body)
      await this.screenshot(page, `${label}-resource`)

      let accessible: boolean
      if (httpStatus === 401 || httpStatus === 403) {
        accessible = false
      } else if (denialText) {
        accessible = false
      } else if (page.url() !== resourceUrl) {
        // Redirected away from the resource (usually to the login page).
        accessible = false
      } else {
        accessible = true
      }

      return { loginSucceeded: true, accessible, httpStatus, body, bodySignature: bodySignature(body), denialText }
    } catch {
      return { loginSucceeded: false, accessible: false, httpStatus: 0, body: "", bodySignature: "", denialText: false }
    } finally {
      await page.close()
      await context.close()
    }
  }

  private async screenshot(page: unknown, label: string): Promise<void> {
    try {
      const shot = await this.engine.captureScreenshot(page as Parameters<BrowserEngine["captureScreenshot"]>[0])
      this.capturedScreenshots.push({ data: shot, label })
    } catch { /* screenshot best-effort */ }
  }
}

/** Stable fingerprint of a page body, ignoring whitespace noise. */
function bodySignature(body: string): string {
  const normalized = body.replace(/\s+/g, " ").trim()
  if (!normalized) return ""
  return createHash("sha256").update(normalized).digest("hex")
}

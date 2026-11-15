import { PlaywrightEngine } from "../browser/engine"
import { scopeEntriesFor } from "../browser/scope-guard"
import { BOLAVerifier } from "../browser/verifiers/bola"
import {
  ObjectAccessPlanError,
  discoveredResourceForFinding,
  objectAccessPlan,
} from "../browser/bola-plan"
import { StoredXSSVerifier } from "../browser/verifiers/xss"
import { XssPlanError, xssInjectionPointForFinding } from "../browser/verifiers/xss-plan"
import { PrivilegeEscalationVerifier } from "../browser/verifiers/priv-esc"
import { SSRFVerifier } from "../browser/verifiers/ssrf"
import { LFIVerifier } from "../browser/verifiers/lfi"
import { JWTVerifier } from "../browser/verifiers/jwt"
import { SecretsExposureVerifier } from "../browser/verifiers/secrets"
import { VerificationRunner } from "../browser/verifiers/runner"
import { EngagementStore } from "../engagement/store"
import type { IEngagementStore } from "../engagement/types"
import { CredentialStore } from "../engagement/credentials"
import { EvidenceCollector } from "../evidence/collector"
import { ConfidenceEngine } from "../engagement/confidence"
import { homedir } from "os"
import { join } from "path"
import { StoragePaths } from "../storage/paths"

export async function verifyCommand(
  findingId: string,
  options?: {
    targetUrl?: string
    credsPath?: string
    storeOverride?: IEngagementStore
    engineOverride?: PlaywrightEngine
    credStoreOverride?: CredentialStore
    collectorOverride?: EvidenceCollector
    confidenceOverride?: ConfidenceEngine
    runnerOverride?: VerificationRunner
  },
): Promise<string> {
  const store = options?.storeOverride ?? new EngagementStore()

  // Find finding by ID using direct DB lookup — replaces O(N×M) scan
  const engagementId = store.getFindingEngagementId(findingId)
  const finding = engagementId ? store.getFinding(findingId) : null

  if (!finding || !engagementId) {
    return `Finding not found: ${findingId}`
  }

  const eng = store.getEngagement(engagementId)
  const engagementTarget = eng?.target ?? "unknown"

  // Load credentials
  const credStore = options?.credStoreOverride ?? new CredentialStore()
  const creds = options?.credsPath ? credStore.load(options.credsPath) : credStore.load()
  const allRoles = credStore.getAllCredentials()
  credStore.clear()

  const targetUrl = options?.targetUrl ?? engagementTarget
  // The browser run is authorized for this engagement's target origin only: the
  // context carries a logged-in session, so a navigation built from
  // target-controlled text (a finding's URL, a redirect) must not inherit it.
  const engine =
    options?.engineOverride ?? new PlaywrightEngine({ allowedTargets: scopeEntriesFor(targetUrl) })
  const evidenceBaseDir = StoragePaths.engagementsDir
  const evidenceCollector = options?.collectorOverride ?? new EvidenceCollector(evidenceBaseDir)
  const confidenceEngine = options?.confidenceOverride ?? new ConfidenceEngine()
  const runner = options?.runnerOverride ?? new VerificationRunner()

  const lines: string[] = []
  lines.push(`[Argus] Re-running verification for finding: ${finding.id}`)
  lines.push(`[Argus] Tool: ${finding.tool}, Target: ${targetUrl}`)

  // NOTE: Verifiers are purpose-built for four role archetypes:
  // attacker, victim, user, admin. Custom role names that don't
  // match one of these (even via substring) will silently skip
  // verification. Add new verifiers in browser/verifiers/ for
  // custom role archetypes.
  // Match roles flexibly: try exact match first, then case-insensitive, then substring
  // This ensures verifiers work with arbitrary role names (e.g. "Attacker", "victim1",
  // "regular-user", "admin_role") rather than only exact lowercase "attacker"/"victim".
  const matchRole = (name: string): { username: string; password: string } | undefined => {
    // 1. Exact case-insensitive match
    const exactMatch = Object.entries(allRoles).find(
      ([key]) => key.toLowerCase() === name.toLowerCase(),
    )
    if (exactMatch) return exactMatch[1] as { username: string; password: string }
    // 2. Substring match (e.g. "attacker1" matches "attacker")
    const substringMatch = Object.entries(allRoles).find(
      ([key]) => key.toLowerCase().includes(name.toLowerCase()),
    )
    if (substringMatch) return substringMatch[1] as { username: string; password: string }
    return undefined
  }

  const attackerRole = matchRole("attacker")
  const victimRole = matchRole("victim")
  const userRole = matchRole("user")
  const adminRole = matchRole("admin")

  // Determine which verifier to run based on finding tool
  try {
    if (finding.tool?.includes("bola") || finding.subtype === "bola" || finding.subtype === "idor") {
      // Stage 4.2: no hard-coded path and no borrowed role. The plan requires
      // the finding's discovered endpoint plus two real, distinct identities;
      // otherwise the check is reported unsupported rather than skipped.
      try {
        // Role names stay flexible ("Attacker", "victim_role", …), but the
        // plan still requires both accounts to exist and be distinct.
        const roleName = (want: string) =>
          Object.keys(allRoles).find((key) => key.toLowerCase().includes(want))
        const plan = objectAccessPlan(
          allRoles,
          discoveredResourceForFinding(finding, targetUrl, {
            ownerRole: roleName("victim"),
            accessorRole: roleName("attacker"),
          }),
        )
        const verifier = new BOLAVerifier(engine, targetUrl, plan, evidenceCollector, engagementId, findingId)
        const result = await runner.run(verifier)
        lines.push(`[BOLA] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
      } catch (error) {
        if (error instanceof ObjectAccessPlanError) {
          lines.push(`[BOLA] unsupported: ${error.message}`)
        } else {
          throw error
        }
      }
    } else if ((finding.tool?.includes("xss") || finding.subtype === "xss" || finding.subtype === "xss_stored" || finding.subtype === "xss_reflected") && (userRole || adminRole)) {
      // Stage 4.3: the victim view is the discovered endpoint/parameter (in a
      // separate victim session), never a guessed page. The verifier builds its
      // own nonce-bearing payload and confirms only an execution report from
      // the victim page.
      try {
        const plan = xssInjectionPointForFinding(finding, targetUrl)
        const verifier = new StoredXSSVerifier(engine, plan, evidenceCollector, engagementId, findingId)
        const result = await runner.run(verifier)
        lines.push(`[XSS] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
      } catch (error) {
        if (error instanceof XssPlanError) {
          lines.push(`[XSS] unsupported: ${error.message}`)
        } else {
          throw error
        }
      }
    } else if ((finding.tool?.includes("priv-esc") || finding.subtype === "privilege_escalation" || finding.subtype === "privesc") && userRole) {
      const verifier = new PrivilegeEscalationVerifier(engine, targetUrl, ["/admin"], userRole, evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[PrivEsc] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
    } else if ((finding.tool?.includes("ssrf") || finding.subtype === "ssrf") && targetUrl) {
      const ssrfEndpoint = finding.description?.match(/\/\S+/)?.[0] ?? "/"
      const verifier = new SSRFVerifier(engine, targetUrl, ssrfEndpoint, evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[SSRF] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
    } else if ((finding.tool?.includes("lfi") || finding.tool?.includes("path_traversal") || finding.subtype === "lfi" || finding.subtype === "path_traversal") && targetUrl) {
      const lfiParam = finding.description?.match(/(?:file|page|include|path|template|load|read|document|folder|root|preview|view|dir|show|url|lang|cat)\s*[:=]\s*\S+/i)?.[0] ?? finding.description?.match(/(\/[^\s,]+)/)?.[1] ?? "file"
      const verifier = new LFIVerifier(engine, targetUrl, lfiParam.startsWith("/") ? lfiParam : `?${lfiParam}=`, evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[LFI] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
    } else if ((finding.tool?.includes("jwt") || finding.subtype === "jwt" || finding.subtype === "jwt_tampering" || finding.subtype === "jwt_none_algorithm") && targetUrl) {
      const protectedEndpoint = finding.description?.match(/(\/[^\s,]+)/)?.[1] ?? "/admin"
      const jwtMatch = finding.description?.match(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/)
      const verifier = new JWTVerifier(engine, targetUrl, protectedEndpoint, jwtMatch?.[0], evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[JWT] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
    } else if ((finding.tool?.includes("secrets") || finding.subtype === "secrets" || finding.subtype === "exposed_secrets" || finding.subtype === "exposed_credentials") && targetUrl) {
      const scanEndpoint = finding.description?.match(/(\/[^\s,]+)/)?.[1] ?? "/"
      const verifier = new SecretsExposureVerifier(engine, targetUrl, scanEndpoint, evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[Secrets] ${result.summary} (proof: ${result.proofStatus}, confidence: ${result.confidence})`)
    } else {
      lines.push(`[Argus] No matching verifier found for tool: ${finding.tool}`)
      lines.push(`[Argus] Available roles: ${Object.keys(allRoles).join(", ") || "none"}`)
    }
  } catch (error) {
    lines.push(`[Argus] Verification failed: ${(error as Error).message}`)
  }

  // Capture evidence screenshot
  try {
    const ctx = await engine.createContext()
    const page = await ctx.newPage()
    await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 30000 })
    const shot = await engine.captureScreenshot(page)
    const screenshotArtifact = await evidenceCollector.captureScreenshot(engagementId, findingId, shot)
    await evidenceCollector.createPackage(engagementId, findingId, screenshotArtifact ? [screenshotArtifact] : [])
    await page.close()
    await ctx.close()
    lines.push(`[Argus] Evidence captured for ${findingId}`)
  } catch { console.warn("[verify] evidence screenshot failed") }

  await engine.close()
  return lines.join("\n")
}

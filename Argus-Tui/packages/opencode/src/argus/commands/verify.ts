import { PlaywrightEngine } from "../browser/engine"
import { BOLAVerifier } from "../browser/verifiers/bola"
import { StoredXSSVerifier } from "../browser/verifiers/xss"
import { PrivilegeEscalationVerifier } from "../browser/verifiers/priv-esc"
import { VerificationRunner } from "../browser/verifiers/runner"
import { EngagementStore } from "../engagement/store"
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
    storeOverride?: EngagementStore
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
  const engine = options?.engineOverride ?? new PlaywrightEngine()
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
    if (finding.tool?.includes("bola") && attackerRole && victimRole) {
      const verifier = new BOLAVerifier(engine, targetUrl, "/api/resource", attackerRole, victimRole, evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[BOLA] ${result.summary} (confidence: ${result.confidence})`)
    } else if (finding.tool?.includes("xss") && (userRole || adminRole)) {
      const creds = userRole ?? adminRole!
      const verifier = new StoredXSSVerifier(engine, targetUrl, targetUrl, "<script>alert('xss')</script>", evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[XSS] ${result.summary} (confidence: ${result.confidence})`)
    } else if (finding.tool?.includes("priv-esc") && userRole) {
      const verifier = new PrivilegeEscalationVerifier(engine, targetUrl, ["/admin"], userRole, evidenceCollector, engagementId, findingId)
      const result = await runner.run(verifier)
      lines.push(`[PrivEsc] ${result.summary} (confidence: ${result.confidence})`)
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

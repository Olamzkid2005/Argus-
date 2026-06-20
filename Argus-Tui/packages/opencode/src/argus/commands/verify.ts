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

  // Find which engagement this finding belongs to
  const allEngagements = store.listEngagements()
  let engagementId: string | null = null
  let finding = null

  for (const eng of allEngagements) {
    const findings = store.getFindings(eng.id)
    const found = findings.find((f) => f.id === findingId)
    if (found) {
      engagementId = eng.id
      finding = found
      break
    }
  }

  if (!finding || !engagementId) {
    return `Finding not found: ${findingId}`
  }

  // Load credentials
  const credStore = options?.credStoreOverride ?? new CredentialStore()
  const creds = options?.credsPath ? credStore.load(options.credsPath) : credStore.load()
  const allRoles = credStore.getAllCredentials()
  credStore.clear()

  const targetUrl = options?.targetUrl ?? finding.description ?? finding.title
  const engine = options?.engineOverride ?? new PlaywrightEngine()
  const evidenceBaseDir = join(homedir(), ".argus", "engagements")
  const evidenceCollector = options?.collectorOverride ?? new EvidenceCollector(evidenceBaseDir)
  const confidenceEngine = options?.confidenceOverride ?? new ConfidenceEngine()
  const runner = options?.runnerOverride ?? new VerificationRunner()

  const lines: string[] = []
  lines.push(`[Argus] Re-running verification for finding: ${finding.id}`)
  lines.push(`[Argus] Tool: ${finding.tool}, Target: ${targetUrl}`)

  // Determine which verifier to run based on finding tool
  try {
    if (finding.tool?.includes("bola") && allRoles.attacker && allRoles.victim) {
      const verifier = new BOLAVerifier(engine, targetUrl, "/api/resource", allRoles.attacker, allRoles.victim)
      const result = await runner.run(verifier)
      lines.push(`[BOLA] ${result.summary} (confidence: ${result.confidence})`)
    } else if (finding.tool?.includes("xss") && (allRoles.user || allRoles.admin)) {
      const creds = allRoles.user ?? allRoles.admin!
      const verifier = new StoredXSSVerifier(engine, targetUrl, targetUrl, "<script>alert('xss')</script>")
      const result = await runner.run(verifier)
      lines.push(`[XSS] ${result.summary} (confidence: ${result.confidence})`)
    } else if (finding.tool?.includes("priv-esc") && allRoles.user) {
      const verifier = new PrivilegeEscalationVerifier(engine, targetUrl, ["/admin"], allRoles.user)
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
    await page.goto(targetUrl, { waitUntil: "networkidle" })
    const shot = await engine.captureScreenshot(page)
    await evidenceCollector.captureScreenshot(engagementId, findingId, shot)
    await evidenceCollector.createPackage(engagementId, findingId, [])
    await page.close()
    await ctx.close()
    lines.push(`[Argus] Evidence captured for ${findingId}`)
  } catch { console.warn("[verify] evidence screenshot failed") }

  await engine.close()
  return lines.join("\n")
}

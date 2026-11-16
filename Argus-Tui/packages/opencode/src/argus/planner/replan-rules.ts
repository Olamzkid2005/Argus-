import type { PlannerContext, NormalizedFinding, Hypothesis, AttackChain } from "./types"
import { Capability } from "./capabilities"

/**
 * Chain-to-capability reference table — matches attack_graph.py CHAIN_RULES.
 *
 * NOTE: The actual chain→capability mapping happens server-side in
 * attack_graph.py's generate_plan_from_graph() via CHAIN_TO_CAPABILITIES.
 * This TypeScript map is kept as documentation of the expected chain IDs
 * and their associated capabilities. It is NOT directly consumed by the
 * planner — the planner reads `chainPlans` from the Python response.
 *
 * Chain IDs from attack_graph.py CHAIN_RULES mapped to exploitation capabilities.
 */
export const REPLAN_CHAINS: Record<string, Capability[]> = {
  chain_1: [Capability.PHISHING_CHAIN],                       // Open Redirect → OAuth Theft → ATO
  chain_2: [Capability.SESSION_HIJACK_ATTEMPT],               // XSS + CSRF → ATO
  chain_3: [Capability.CLOUD_METADATA_PROBE, Capability.POST_EXPLOITATION], // SSRF → Cloud Metadata → AWS Compromise
  chain_4: [Capability.LATERAL_MOVEMENT],                     // LFI + File Upload → RCE
  chain_5: [Capability.CREDENTIAL_REPLAY],                    // Subdomain Takeover + CORS → Credential Theft
  chain_6: [Capability.SESSION_HIJACK_ATTEMPT],               // XSS → Session Token Theft → ATO
  chain_7: [Capability.POST_EXPLOITATION],                    // IDOR + Mass Assignment → PrivEsc
  chain_8: [Capability.PHISHING_CHAIN],                       // Open Redirect + Phishing
}

export const REPLAN_INSERTABLE: Record<string, Capability> = {
  graphql: Capability.GRAPHQL_ASSESSMENT,
  // expressjs subtype → VULNERABILITY_SCANNING: no dedicated Express CVE scanner exists.
  // Replan will re-run generic vulnerability scanners to catch Express-specific CVEs.
  expressjs: Capability.VULNERABILITY_SCANNING,
  swagger: Capability.API_DOCS_ANALYSIS,
  openapi: Capability.API_DOCS_ANALYSIS,
  jwt: Capability.JWT_ANALYSIS,
  ssrf_parameters: Capability.SSRF_CHECK,
  // A parameter arjun proved the server accepts widens the API surface; the
  // executedCapabilities guard keeps it from re-running api_probing.
  parameter_discovery: Capability.API_PROBING,
  sqli_reflective: Capability.SQLI_DETECTION,
  sqli_blind: Capability.SQLI_DETECTION,

  // Confirmed-vulnerability chains that turn scanner output into red team actions.
  sqli_confirmed: Capability.POST_EXPLOITATION,
  ssrf_confirmed: Capability.CLOUD_METADATA_PROBE,
  xss_confirmed: Capability.SESSION_HIJACK_ATTEMPT,
  rce_confirmed: Capability.LATERAL_MOVEMENT,
  open_redirect: Capability.PHISHING_CHAIN,
  exposed_secret: Capability.CREDENTIAL_REPLAY,
  // Bucket permission findings map back to the S3 capability that found them;
  // it is already executed, so no duplicate scan is queued.
  s3_public_bucket_listing: Capability.S3_SCANNING,
  s3_public_object: Capability.S3_SCANNING,
  s3_anonymous_write: Capability.S3_SCANNING,
  url_discovery: Capability.CONTENT_DISCOVERY,
  subdomain_discovery: Capability.WEB_RECON,
}

/**
 * Finding subtypes that describe an observation, not a vulnerability.
 *
 * Every recon phase emits these (`OPEN_PORT`, `HTTP_ENDPOINT`,
 * `CRAWLED_ENDPOINT`, `technology_detection`, `raw_output`, `port_open`,
 * `web_vulnerability`), so they can never map to a replan capability and
 * logging them buried the subtypes that genuinely have no mapping. Listed
 * explicitly rather than pattern-matched so a new vulnerability subtype cannot
 * slip in silently.
 */
const INFORMATIONAL_SUBTYPES = new Set([
  "open_port",
  "port_open",
  "http_endpoint",
  "crawled_endpoint",
  "endpoint",
  "technology_detection",
  "technology",
  "raw_output",
  "web_vulnerability",
  // Clean negatives from the discovery shims: the check executed and found
  // nothing, so there is no new capability to add.
  "parameter_discovery_negative",
  "sql_injection_not_found",
  "vulnerability_scan_negative",
  "s3_permissions_negative",
  "url_discovery_negative",
  "subdomain_discovery_negative",
  "subdomain_permutation",
  "waf_detected",
  "waf_detection_negative",
  "info",
  "informational",
  "observation",
])

/**
 * Subtypes already reported as unmapped in this process.
 *
 * `determineNewCapabilities()` runs after every phase, over every finding, so
 * a single unmapped subtype printed its warning dozens of times per run.
 */
const reportedUnmappedSubtypes = new Set<string>()

/** Confidence threshold for hypotheses to trigger replanning. */
const HYPOTHESIS_CONFIDENCE_THRESHOLD = 0.6

/** Map hypothesis description keywords to verification capabilities. */
const HYPOTHESIS_KEYWORD_CAPABILITIES: Array<{ keywords: string[]; capability: Capability }> = [
  { keywords: ["sql", "sqli", "sql injection", "blind sql"], capability: Capability.SQLI_DETECTION },
  { keywords: ["xss", "cross-site scripting", "reflected xss", "stored xss", "dom xss"], capability: Capability.VULNERABILITY_SCANNING },
  { keywords: ["jwt", "token", "auth bypass", "authentication"], capability: Capability.JWT_ANALYSIS },
  { keywords: ["bola", "idor", "broken access", "privilege"], capability: Capability.POST_EXPLOITATION },
  { keywords: ["ssrf", "server-side request"], capability: Capability.SSRF_CHECK },
  { keywords: ["rce", "command injection", "remote code"], capability: Capability.COMMAND_INJECTION },
  { keywords: ["secret", "credential", "api key", "token exposed"], capability: Capability.CREDENTIAL_REPLAY },
  { keywords: ["redirect", "open redirect"], capability: Capability.PHISHING_CHAIN },
]

function capabilitiesFromHypotheses(hypotheses: Hypothesis[]): Set<Capability> {
  const result = new Set<Capability>()
  for (const h of hypotheses) {
    if (h.status !== "UNVERIFIED" || h.confidence < HYPOTHESIS_CONFIDENCE_THRESHOLD) {
      continue
    }
    const desc = h.description.toLowerCase()
    for (const { keywords, capability } of HYPOTHESIS_KEYWORD_CAPABILITIES) {
      if (keywords.some((kw) => desc.includes(kw))) {
        result.add(capability)
      }
    }
  }
  return result
}

export function determineNewCapabilities(context: PlannerContext): Set<Capability> {
  const result = new Set<Capability>()

  for (const finding of context.findings) {
    const subtype = finding.subtype
    if (subtype) {
      // Parsers disagree on casing: some emit "sqli_reflective", the discovery
      // shims emit "PARAMETER_DISCOVERY". The tables are lowercase, so look up
      // the normalised key — otherwise a real subtype logs as unknown.
      const subtypeKey = subtype.toLowerCase()
      if (REPLAN_INSERTABLE[subtypeKey]) {
        const cap = REPLAN_INSERTABLE[subtypeKey]
        if (finding.negative) {
          // Negative findings trigger capability insertion even if the
          // capability was already executed — the absence of a finding
          // suggests a different tool/approach is needed.
          result.add(cap)
        } else if (!context.executedCapabilities.has(cap)) {
          result.add(cap)
        }
      } else if (!INFORMATIONAL_SUBTYPES.has(subtypeKey)) {
        // Deduplicated: one line per subtype per process instead of one per
        // finding per phase. Informational recon subtypes are skipped entirely
        // — they have no capability to map to by design.
        if (!reportedUnmappedSubtypes.has(subtype)) {
          reportedUnmappedSubtypes.add(subtype)
          console.debug(`[replan-rules] Unknown subtype "${subtype}" — no capability mapping (add to REPLAN_INSERTABLE if needed)`)
        }
      }
    }
  }

  // Hypothesis-driven capabilities: unverified hypotheses with sufficient
  // confidence can trigger replanning even when no finding subtype maps to them.
  if (context.hypotheses && context.hypotheses.length > 0) {
    const hypCaps = capabilitiesFromHypotheses(context.hypotheses)
    for (const cap of hypCaps) {
      if (!context.executedCapabilities.has(cap)) {
        result.add(cap)
      }
    }
  }

  return result
}

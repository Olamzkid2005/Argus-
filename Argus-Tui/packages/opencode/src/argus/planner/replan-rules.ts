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
  sqli_reflective: Capability.SQLI_DETECTION,
  sqli_blind: Capability.SQLI_DETECTION,

  // Confirmed-vulnerability chains that turn scanner output into red team actions.
  sqli_confirmed: Capability.POST_EXPLOITATION,
  ssrf_confirmed: Capability.CLOUD_METADATA_PROBE,
  xss_confirmed: Capability.SESSION_HIJACK_ATTEMPT,
  rce_confirmed: Capability.LATERAL_MOVEMENT,
  open_redirect: Capability.PHISHING_CHAIN,
  exposed_secret: Capability.CREDENTIAL_REPLAY,
}

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
      if (REPLAN_INSERTABLE[subtype]) {
        const cap = REPLAN_INSERTABLE[subtype]
        if (finding.negative) {
          // Negative findings trigger capability insertion even if the
          // capability was already executed — the absence of a finding
          // suggests a different tool/approach is needed.
          result.add(cap)
        } else if (!context.executedCapabilities.has(cap)) {
          result.add(cap)
        }
      } else {
        console.debug(`[replan-rules] Unknown subtype "${subtype}" — no capability mapping (add to REPLAN_INSERTABLE if needed)`)
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

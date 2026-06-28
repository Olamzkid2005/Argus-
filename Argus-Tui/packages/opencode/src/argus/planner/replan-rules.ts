import type { PlannerContext, NormalizedFinding } from "./types"
import { Capability } from "./capabilities"

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

  return result
}

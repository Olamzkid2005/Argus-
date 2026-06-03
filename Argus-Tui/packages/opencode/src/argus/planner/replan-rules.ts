import { PlannerContext, NormalizedFinding } from "./types"
import { Capability } from "./capabilities"

const REPLAN_INSERTABLE: Record<string, Capability> = {
  graphql: Capability.GRAPHQL_ASSESSMENT,
  expressjs: Capability.EXPRESS_CVE_SCAN,
  swagger: Capability.API_DOCS_ANALYSIS,
  openapi: Capability.API_DOCS_ANALYSIS,
  jwt: Capability.JWT_ANALYSIS,
  ssrf_parameters: Capability.SSRF_CHECK,
  sqli_reflective: Capability.SQLI_DETECTION,
  sqli_blind: Capability.SQLI_DETECTION,
}

export function determineNewCapabilities(context: PlannerContext): Set<Capability> {
  const result = new Set<Capability>()

  for (const finding of context.findings) {
    const subtype = finding.subtype
    if (subtype && REPLAN_INSERTABLE[subtype]) {
      const cap = REPLAN_INSERTABLE[subtype]
      if (!context.executedCapabilities.has(cap)) {
        result.add(cap)
      }
    }
  }

  return result
}

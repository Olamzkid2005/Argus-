import { Confidence } from "../planner/types"
import type { NormalizedFinding } from "../planner/types"

const PROMOTION_RULES: Array<{ from: Confidence; to: Confidence; condition: (finding: NormalizedFinding) => boolean }> = [
  {
    from: Confidence.INFORMATIONAL,
    to: Confidence.LOW,
    condition: () => true,
  },
  {
    from: Confidence.LOW,
    to: Confidence.MEDIUM,
    condition: (f) => !!f.tool && f.severity >= 2,
  },
  {
    from: Confidence.MEDIUM,
    to: Confidence.HIGH,
    condition: (f) => f.owasp !== undefined || f.cwe !== undefined,
  },
  {
    from: Confidence.HIGH,
    to: Confidence.VERIFIED,
    condition: (f) => f.evidence !== undefined && f.evidence.length > 0,
  },
  {
    from: Confidence.VERIFIED,
    to: Confidence.CONFIRMED,
    condition: () => false,
  },
]

export class ConfidenceEngine {
  promote(finding: NormalizedFinding): Confidence {
    let current = finding.confidence

    for (const rule of PROMOTION_RULES) {
      if (current === rule.from && rule.condition(finding)) {
        current = rule.to
      }
    }

    return current
  }

  shouldFinalize(finding: NormalizedFinding): boolean {
    return finding.status === "CONFIRMED" || finding.confidence >= Confidence.VERIFIED
  }
}

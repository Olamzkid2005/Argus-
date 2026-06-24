import { Confidence } from "../shared/types"
import type { NormalizedFinding } from "../shared/types"

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
    condition: (f) =>
      (f.owasp !== undefined || f.cwe !== undefined) ||
      // 2xx on an auth check endpoint is a strong signal
      (f.statusCode !== undefined && f.statusCode >= 200 && f.statusCode < 300),
  },
  {
    from: Confidence.HIGH,
    to: Confidence.VERIFIED,
    condition: (f) => f.evidence !== undefined && f.evidence.length > 0,
  },
  {
    // CONFIRMED is set externally by the verification runner, not by the promotion engine.
    from: Confidence.VERIFIED,
    to: Confidence.CONFIRMED,
    condition: () => false,
  },
]

export class ConfidenceEngine {
  promote(finding: NormalizedFinding): Confidence {
    // Only promote one tier per call — prevents cascade from e.g.
    // INFORMATIONAL to VERIFIED in a single pass based on metadata alone.
    // The executor or workflow runner should call promote() again after
    // independent re-verification (e.g. browser confirmation) to advance
    // further tiers.
    for (const rule of PROMOTION_RULES) {
      if (finding.confidence === rule.from && rule.condition(finding)) {
        return rule.to
      }
    }

    return finding.confidence
  }

  shouldFinalize(finding: NormalizedFinding): boolean {
    if (finding.status === "REJECTED") return false
    return finding.status === "CONFIRMED" || finding.confidence >= Confidence.VERIFIED
  }
}

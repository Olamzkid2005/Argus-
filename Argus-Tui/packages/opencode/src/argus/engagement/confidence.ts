import { Confidence } from "../shared/types"
import type { NormalizedFinding } from "../shared/types"
import { proofSupportsVerifiedClaim } from "../browser/proof"

/**
 * Whether this finding holds proof strong enough for a verified/confirmed
 * claim: an explicit `reproduced` verification plus a real artifact or control.
 *
 * This is the only thing that can raise confidence above HIGH. Metadata
 * (owasp/cwe/status code) stops at HIGH, a bare `passed: true` is only
 * `suspected`, and a failed/inconclusive/unsupported verification can never be
 * promoted — which is what makes repeated promotion calls harmless.
 */
function hasProofForVerifiedClaim(finding: NormalizedFinding): boolean {
  const artifacts = (finding.evidence ?? []).reduce(
    (count, pkg) => count + (pkg.artifacts?.length ?? 0),
    0,
  )
  return proofSupportsVerifiedClaim(finding.verificationResult, {
    evidenceArtifacts: artifacts,
  })
}

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
    // VERIFIED is a proof claim: it needs a reproduced verification with real
    // evidence or a control comparison. Evidence packages alone are not proof
    // (an empty or error-only package used to be enough), and neither is a
    // verifier's bare pass.
    from: Confidence.HIGH,
    to: Confidence.VERIFIED,
    condition: (f) => hasProofForVerifiedClaim(f),
  },
  {
    // CONFIRMED needs the same proof, reached from VERIFIED. A failed,
    // inconclusive or unsupported verification never satisfies it, so the
    // caller's cascading promote() loop stops at HIGH.
    from: Confidence.VERIFIED,
    to: Confidence.CONFIRMED,
    condition: (f) => hasProofForVerifiedClaim(f),
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

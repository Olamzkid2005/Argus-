/**
 * Proof status — the one place a verification outcome becomes a claim.
 *
 * Stage 4.1 item 1. A verification used to be reported as `passed: boolean`
 * plus a confidence score, which conflated three different things: a
 * reproduction we observed, a check that produced nothing, and a check that
 * could not run. Downstream code (confidence promotion, reports) then had no
 * honest input to work from.
 *
 * `ProofStatus` names the five outcomes the plan requires:
 *   - `suspected`        — evidence points at the issue, but no reproduction
 *   - `reproduced`       — the verifier observed the exploit itself
 *   - `not_reproduced`   — the verifier ran and produced a negative
 *   - `inconclusive`     — the verifier could not complete (error preserved)
 *   - `unsupported`      — no real verification exists for this issue type yet
 *
 * Only a verifier that actually observed the exploit may return `reproduced`.
 * `proofStatusFor()` therefore maps a bare `passed: true` to `suspected` and
 * never upgrades it from confidence — confidence describes how strongly the
 * finding is believed, not that it was proven.
 */

import {
  ProofStatus,
  type ControlReference,
  type VerificationResult,
  type VerifierErrorDetail,
} from "../shared/types"
import type { VerifierResult } from "./types"

/** What real proof the finding holds, beyond the verifier's own claim. */
export interface ProofArtifacts {
  /** Count of collected artifacts across the finding's evidence packages. */
  evidenceArtifacts?: number
}

/**
 * Whether a stored verification justifies a verified/confirmed confidence.
 *
 * Stage 4.1 item 2. Confidence above HIGH is a proof claim, so it needs proof:
 * an explicit `reproduced` status **and** something to show for it — a control
 * comparison or at least one captured artifact. Everything else is refused:
 *
 *   - `suspected` (including a bare `passed: true`) is not a reproduction;
 *   - `not_reproduced`, `inconclusive` and `unsupported` can never promote, so
 *     repeated promotion calls cannot walk a failed check up to `confirmed`;
 *   - an evidence package with no artifacts is an empty claim, not evidence.
 */
export function proofSupportsVerifiedClaim(
  verification: VerificationResult | undefined,
  artifacts: ProofArtifacts = {},
): boolean {
  if (!verification) return false
  if (verification.proofStatus !== ProofStatus.REPRODUCED) return false
  const controls = verification.controls?.length ?? 0
  const evidenceArtifacts = artifacts.evidenceArtifacts ?? 0
  return controls > 0 || evidenceArtifacts > 0
}

/** The status a verifier result claims, or the honest default for its outcome. */
export function proofStatusFor(
  result: Pick<VerifierResult, "passed" | "proofStatus">,
): ProofStatus {
  if (result.proofStatus) return result.proofStatus
  return result.passed ? ProofStatus.SUSPECTED : ProofStatus.NOT_REPRODUCED
}

/**
 * Aggregate the proof status of a multi-stage (chained) verification.
 *
 * Stage 4.1 item 3. A chain used to report `passed: anyPassed`, so one stage
 * that happened to return true made the whole attack path look verified even
 * when the other stages failed or never ran. A chain is only `reproduced`
 * when **every** stage reproduced; a single unsupported stage makes the chain
 * unsupported, an incomplete stage makes it inconclusive, and a negative stage
 * makes it not reproduced. With no stages at all there is nothing to verify.
 */
export function chainProofStatus(
  stageResults: Array<Pick<VerifierResult, "passed" | "proofStatus">>,
): ProofStatus {
  if (stageResults.length === 0) return ProofStatus.UNSUPPORTED
  const statuses = stageResults.map(proofStatusFor)
  if (statuses.includes(ProofStatus.UNSUPPORTED)) return ProofStatus.UNSUPPORTED
  if (statuses.includes(ProofStatus.INCONCLUSIVE)) return ProofStatus.INCONCLUSIVE
  if (statuses.includes(ProofStatus.NOT_REPRODUCED)) return ProofStatus.NOT_REPRODUCED
  if (statuses.every((status) => status === ProofStatus.REPRODUCED)) {
    return ProofStatus.REPRODUCED
  }
  return ProofStatus.SUSPECTED
}

/**
 * Build the stored `VerificationResult` for a completed verifier run.
 *
 * This is the single conversion from a verifier's result to the artifact that
 * lives on a finding, so every stored result carries a status, its controls and
 * (when the run failed) the verifier's error detail.
 */
export function verificationResultFrom(input: {
  verifier: string
  result: VerifierResult
  verifiedAt?: Date
}): VerificationResult {
  const { verifier, result } = input
  const controls: ControlReference[] = result.controls ?? []
  const error: VerifierErrorDetail | undefined = result.error

  return {
    passed: result.passed,
    proofStatus: proofStatusFor(result),
    confidence: result.confidenceScore ?? 0,
    summary: result.summary,
    verifier,
    verifiedAt: (input.verifiedAt ?? new Date()).toISOString(),
    controls,
    ...(error ? { error } : {}),
    ...(result.cleanup ? { cleanup: result.cleanup } : {}),
  }
}

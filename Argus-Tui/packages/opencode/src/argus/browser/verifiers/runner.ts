import type { VerificationScenario, VerifierResult } from "../types"
import { Confidence, ProofStatus } from "../../shared/types"
import type { CleanupOutcome, VerifierErrorDetail } from "../../shared/types"
import { proofStatusFor } from "../proof"

/**
 * Default timeout per step in milliseconds.
 * Each step (setup/execute/verify/collectEvidence) is given this
 * much wall-clock time before the runner moves on to the next.
 * Tools like playwright-bola with multiple access checks may need more,
 * so a generous default is used.
 */
const STEP_TIMEOUT_MS = 120_000 // 2 minutes per step

type StepName = VerifierErrorDetail["step"]

/**
 * Run a promise with a timeout. Rejects if the promise does not settle
 * within the given time.
 */
function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms),
    ),
  ])
}

function errorDetail(step: StepName, error: unknown): VerifierErrorDetail {
  const err = error as Error | undefined
  return {
    step,
    name: err?.name ?? "Error",
    message: err?.message ?? String(error),
  }
}

export class VerificationRunner {
  async run(scenario: VerificationScenario): Promise<VerifierResult> {
    // The failing step is part of the result: "could not run" and "ran and
    // found nothing" are different claims, and only the step tells them apart.
    let step: StepName = "setup"
    // Kept outside the try so the teardown outcome can be attached to whichever
    // result is returned — including a failed one — before the caller sees it.
    let outcome: VerifierResult | undefined
    try {
      await withTimeout(scenario.setup(), STEP_TIMEOUT_MS, `Verifier ${scenario.name} setup`)
      step = "execute"
      await withTimeout(scenario.execute(), STEP_TIMEOUT_MS, `Verifier ${scenario.name} execute`)
      step = "verify"
      const result = await withTimeout(scenario.verify(), STEP_TIMEOUT_MS, `Verifier ${scenario.name} verify`)
      step = "collectEvidence"
      const evidence = await withTimeout(
        scenario.collectEvidence(),
        STEP_TIMEOUT_MS,
        `Verifier ${scenario.name} collectEvidence`,
      )

      outcome = {
        ...result,
        evidence: [evidence],
        // A completed run's own claim stands; a bare `passed: true` is only
        // `suspected`, never `reproduced`.
        proofStatus: proofStatusFor(result),
        controls: result.controls ?? [],
      }
      return outcome
    } catch (error) {
      const detail = errorDetail(step, error)
      outcome = {
        passed: false,
        proofStatus: ProofStatus.INCONCLUSIVE,
        confidence: Confidence.INFORMATIONAL,
        confidenceScore: 0,
        evidence: [],
        controls: [],
        summary: `Verification failed during ${detail.step}: ${detail.message}`,
        error: detail,
      }
      return outcome
    } finally {
      // Teardown is part of the record: a verifier that leaves a browser or a
      // temp HAR behind is not a clean reproduction, and the caller needs to
      // see which it was (Stage 4.3 item 3).
      let cleanup: CleanupOutcome = { ok: true, detail: "cleanup completed" }
      try {
        await scenario.cleanup?.()
        cleanup = scenario.cleanupOutcome?.() ?? cleanup
      } catch (error) {
        const detail = errorDetail("cleanup", error)
        cleanup = { ok: false, detail: `cleanup failed: ${detail.message}` }
      }
      if (outcome) {
        outcome.cleanup = cleanup
        outcome.controls = [
          ...(outcome.controls ?? []),
          {
            kind: "cleanup",
            description: "browser session and temporary evidence teardown",
            outcome: cleanup.detail,
          },
        ]
      }
    }
  }
}

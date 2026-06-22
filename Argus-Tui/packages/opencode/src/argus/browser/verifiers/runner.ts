import type { VerificationScenario, VerifierResult } from "../types"
import { Confidence } from "../../shared/types"

/**
 * Default timeout per step in milliseconds.
 * Each step (setup/execute/verify/collectEvidence/cleanup) is given this
 * much wall-clock time before the runner moves on to the next step.
 * Tools like playwright-bola with multiple access checks may need more,
 * so a generous default is used.
 */
const STEP_TIMEOUT_MS = 120_000 // 2 minutes per step

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

export class VerificationRunner {
  async run(scenario: VerificationScenario): Promise<VerifierResult> {
    try {
      await withTimeout(scenario.setup(), STEP_TIMEOUT_MS, `Verifier ${scenario.name} setup`)
      await withTimeout(scenario.execute(), STEP_TIMEOUT_MS, `Verifier ${scenario.name} execute`)
      const result = await withTimeout(scenario.verify(), STEP_TIMEOUT_MS, `Verifier ${scenario.name} verify`)
      const evidence = await withTimeout(
        scenario.collectEvidence(),
        STEP_TIMEOUT_MS,
        `Verifier ${scenario.name} collectEvidence`,
      )

      return {
        ...result,
        evidence: [evidence],
      }
    } catch (error) {
      return {
        passed: false,
        confidence: Confidence.INFORMATIONAL,
        evidence: [],
        summary: `Verification failed: ${(error as Error).message}`,
      }
    } finally {
      await scenario.cleanup?.()
    }
  }
}

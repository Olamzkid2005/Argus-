import type { VerificationScenario, VerifierResult } from "../types"
import { Confidence } from "../../planner/types"

export class VerificationRunner {
  async run(scenario: VerificationScenario): Promise<VerifierResult> {
    try {
      await scenario.setup()
      await scenario.execute()
      const result = await scenario.verify()
      const evidence = await scenario.collectEvidence()

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

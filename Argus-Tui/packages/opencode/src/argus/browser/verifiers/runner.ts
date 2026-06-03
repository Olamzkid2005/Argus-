import type { VerificationScenario, VerifierResult } from "../types"

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
        confidence: 0,
        evidence: [],
        summary: `Verification failed: ${(error as Error).message}`,
      }
    }
  }
}

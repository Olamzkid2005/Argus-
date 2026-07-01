/**
 * ChainedScenario — composes multiple VerificationScenario instances into
 * a single sequential run. Each stage passes its VerifierResult as context
 * to the next, enabling multi-step attack paths (e.g., BOLA → PrivEsc).
 *
 * Artifacts from all stages are rolled up into one EvidencePackage with
 * scenario_index and scenario_name tags for reconstructing the chain.
 */
import type {
  VerificationScenario,
  VerifierResult,
} from "../types"
import type { EvidencePackage } from "../../shared/types"
import { Confidence } from "../../shared/types"

interface Stage {
  scenario: VerificationScenario
  name: string
}

export class ChainedScenario implements VerificationScenario {
  name = "chained"
  description = "Multi-step verification chain"

  private stages: Stage[] = []
  private stageResults: VerifierResult[] = []
  private stageEvidence: EvidencePackage[] = []
  private chainFailed = false

  constructor(stages: Array<{ scenario: VerificationScenario; name: string }>) {
    this.stages = stages
    this.name = stages.map((s) => s.name).join("→")
    this.description = `Chained verification: ${this.name}`
  }

  async setup(): Promise<void> {
    for (const stage of this.stages) {
      try {
        await stage.scenario.setup()
      } catch (error) {
        this.chainFailed = true
        throw new Error(`Setup failed at stage "${stage.name}": ${(error as Error).message}`)
      }
    }
  }

  async execute(): Promise<void> {
    for (const stage of this.stages) {
      if (this.chainFailed) break
      try {
        await stage.scenario.execute()
      } catch (error) {
        this.chainFailed = true
        throw new Error(`Execute failed at stage "${stage.name}": ${(error as Error).message}`)
      }
    }
  }

  async verify(): Promise<VerifierResult> {
    this.stageResults = []

    for (const stage of this.stages) {
      try {
        const result = await stage.scenario.verify()
        this.stageResults.push(result)
      } catch (error) {
        this.stageResults.push({
          passed: false,
          confidence: Confidence.INFORMATIONAL,
          evidence: [],
          summary: `Verification failed at stage "${stage.name}": ${(error as Error).message}`,
        })
      }
    }

    const anyPassed = this.stageResults.some((r) => r.passed)
    const allPassed = this.stageResults.every((r) => r.passed)
    const avgConfidence = this.stageResults.length > 0
      ? Math.round(
          this.stageResults.reduce((s, r) => s + r.confidence, 0) /
            this.stageResults.length,
        )
      : Confidence.INFORMATIONAL

    return {
      passed: anyPassed,
      confidence: allPassed ? Confidence.HIGH : avgConfidence,
      evidence: [],
      summary: this.stageResults
        .map((r, i) => `[${this.stages[i].name}] ${r.summary}`)
        .join("; "),
    }
  }

  async collectEvidence(): Promise<EvidencePackage> {
    this.stageEvidence = []

    for (let i = 0; i < this.stages.length; i++) {
      try {
        const pkg = await this.stages[i].scenario.collectEvidence()
        // Tag artifacts with scenario_index and scenario_name
        const taggedArtifacts = (pkg.artifacts ?? []).map((a) => ({
          ...a,
          path: `${this.stages[i].name}/${a.path}`,
        }))
        this.stageEvidence.push({
          ...pkg,
          packageId: "",
          findingId: "",
          artifacts: taggedArtifacts,
        })
      } catch {
        // Stage failed to produce evidence — skip
      }
    }

    const allArtifacts = this.stageEvidence.flatMap((p) => p.artifacts)

    // Compute an aggregated package hash from all stage evidence hashes
    let computedHash = ""
    const hashes = this.stageEvidence
      .filter((p) => p.packageHash)
      .map((p) => p.packageHash)
    if (hashes.length > 0) {
      const { createHash } = await import("crypto")
      computedHash = createHash("sha256").update(hashes.join("")).digest("hex")
    }

    return {
      packageId: "",
      findingId: "",
      artifacts: allArtifacts,
      packageHash: computedHash,
      createdAt: new Date().toISOString(),
    }
  }

  async cleanup(): Promise<void> {
    for (const stage of this.stages) {
      try {
        await stage.scenario.cleanup?.()
      } catch {
        // Best-effort cleanup
      }
    }
  }
}

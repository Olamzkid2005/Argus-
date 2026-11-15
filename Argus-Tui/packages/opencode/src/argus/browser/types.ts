import { Confidence } from "../shared/types"
import type {
  CleanupOutcome,
  ControlReference,
  EvidencePackage,
  ProofStatus,
  VerifierErrorDetail,
} from "../shared/types"

export interface VerificationScenario {
  name: string
  description: string
  setup(): Promise<void>
  execute(): Promise<void>
  verify(): Promise<VerifierResult>
  collectEvidence(): Promise<EvidencePackage>
  cleanup?(): Promise<void>
  /**
   * What the cleanup actually did, read by the runner after `cleanup()` so the
   * stored result keeps the teardown outcome even though evidence is collected
   * before the browser is closed (Stage 4.3 item 3).
   */
  cleanupOutcome?(): CleanupOutcome
}

export interface VerifierResult {
  passed: boolean
  /**
   * What the verifier actually established. Optional so existing verifiers keep
   * compiling; absent means "derive from `passed`" (a bare pass is only ever
   * `suspected`, see `../browser/proof.ts`).
   */
  proofStatus?: ProofStatus
  confidence: Confidence
  confidenceScore: number  // 0.0-1.0 float — graded confidence (survives downstream into VerificationResult)
  evidence: EvidencePackage[]
  summary: string
  /** Comparisons held fixed while testing (baseline, secure twin, second identity). */
  controls?: ControlReference[]
  /** Set by the runner when a step throws; makes the outcome `inconclusive`. */
  error?: VerifierErrorDetail
  /** Teardown outcome, attached by the runner after `cleanup()`. */
  cleanup?: CleanupOutcome
}

export interface Observation {
  url: string
  domSnapshot: string
  responseHeaders: Record<string, string>
  statusCode: number
  timestamp: string
}

export interface DiffResult {
  changed: boolean
  additions: string[]
  removals: string[]
}

export type { EvidencePackage }

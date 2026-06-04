import { Confidence } from "../shared/types"
import type { EvidencePackage } from "../shared/types"

export interface VerificationScenario {
  name: string
  description: string
  setup(): Promise<void>
  execute(): Promise<void>
  verify(): Promise<VerifierResult>
  collectEvidence(): Promise<EvidencePackage>
  cleanup?(): Promise<void>
}

export interface VerifierResult {
  passed: boolean
  confidence: Confidence
  evidence: EvidencePackage[]
  summary: string
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

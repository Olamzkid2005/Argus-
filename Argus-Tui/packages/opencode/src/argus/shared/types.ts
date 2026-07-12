export type TargetType = "web_app" | "api" | "spa" | "unknown"
export type AuthState = "none" | "basic" | "session" | "oauth" | "jwt"
export type ExecutionMode = "parallel" | "sequential" | "llm_driven"
export type ErrorRecovery = "retry_once_then_skip" | "skip_and_continue" | "fail_fast"

export interface CredentialRef {
  role: string
  credentialType: string
}

export interface NormalizedFinding {
  id: string
  title: string
  severity: Severity
  confidence: Confidence
  status: "PENDING" | "CONFIRMED" | "REJECTED" | "FINALIZED" | "DISMISSED"
  description: string
  subtype?: string
  evidence?: EvidencePackage[]
  cve?: string
  cwe?: string
  owasp?: string
  remediation?: string
  tool: string
  phase: string
  created_at: string
  updated_at: string
  finalized_at?: string
  /** HTTP status code observed during finding (e.g., 200, 403, 500) */
  statusCode?: number
  /** The URL/endpoint where this finding was discovered. */
  url?: string
  /** Source tool that generated this finding (e.g., "nuclei", "sqlmap"). */
  source?: string
  /** If true, this finding represents the absence of a finding (negative evidence).
   *  Used by replan to trigger capability insertion on scan misses.
   *  Negative findings are exempt from MAX_REPLANS on first consideration. */
  negative?: boolean
  /** Result from an autonomous browser verification run. */
  verificationResult?: VerificationResult
}

export interface VerificationResult {
  passed: boolean
  summary: string
  verifier: string
  verifiedAt: string
}

// Note: This file uses camelCase for in-memory/API transfer.
// The snake_case equivalents are in evidence/types.ts for disk persistence.
// See evidence/types.ts for EvidenceManifest and ArtifactEntry.
export interface ArtifactRef {
  path: string
  type: ArtifactType
  hash?: string
}

export interface EvidencePackage {
  packageId: string
  findingId: string
  artifacts: ArtifactRef[]
  packageHash: string
  createdAt: string
}

export type ArtifactType = "screenshot" | "request" | "response" | "har" | "log"

export enum Severity {
  INFO = 0,
  LOW = 1,
  MEDIUM = 2,
  HIGH = 3,
  CRITICAL = 4,
}

export enum Confidence {
  INFORMATIONAL = 0,
  LOW = 1,
  MEDIUM = 2,
  HIGH = 3,
  VERIFIED = 4,
  CONFIRMED = 5,
}

export interface FindingAnalysis {
  findingId: string
  explanation: string
  impact: string[]
  remediation: string[]
  references?: string[]
  model: string
  generatedAt: number
  findingUpdatedAt: number
}

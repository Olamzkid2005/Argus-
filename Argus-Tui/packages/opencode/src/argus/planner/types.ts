import { Capability } from "./capabilities"

export type TargetType = "web_app" | "api" | "spa" | "unknown"
export type AuthState = "none" | "basic" | "session" | "oauth" | "jwt"
export type ExecutionMode = "parallel" | "sequential"
export type ErrorRecovery = "retry_once_then_skip" | "skip_and_continue" | "fail_fast"

export interface WorkflowDefinition {
  name: string
  label: string
  version: number
  phases: PhaseDefinition[]
  approval_required?: Record<string, boolean>
}

export interface PhaseDefinition {
  name: string
  required_capabilities: Capability[]
  execution: ExecutionMode
  error_recovery: ErrorRecovery
  approval_gate?: string
}

export interface CredentialRef {
  role: string
  credentialType: string
}

export interface PhaseExecutionRequest {
  phaseId: string
  workflowName: string
  target: string
  requiredCapabilities: Capability[]
  credentials?: CredentialRef[]
  config: Record<string, unknown>
  previousPhaseResults: PhaseExecutionResult[]
}

export interface PhaseExecutionResult {
  phaseId: string
  status: "completed" | "failed" | "skipped" | "partial"
  findings: NormalizedFinding[]
  artifacts: ArtifactRef[]
  errors: string[]
  durationMs: number
}

export interface AssessmentPlan {
  workflow: string
  phases: PhaseExecutionRequest[]
  errorRecovery: Record<string, ErrorRecovery>
  planCreatedAt: string
}

export interface PlannerContext {
  target: string
  targetType: TargetType
  authState: AuthState
  techStack?: string[]
  findings: NormalizedFinding[]
  executedCapabilities: Set<Capability>
  insertedPhases: Set<string>
  replanCount: number
}

export interface NormalizedFinding {
  id: string
  title: string
  severity: Severity
  confidence: Confidence
  status: "PENDING" | "CONFIRMED" | "REJECTED" | "FINALIZED"
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
}

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

export interface ErrorRecoveryPolicy {
  maxRetries: number
  backoffMs: number
  fallbackBehavior: "skip" | "degrade" | "abort"
}

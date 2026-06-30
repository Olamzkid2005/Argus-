import { Capability } from "./capabilities"
import { Severity, Confidence } from "../shared/types"
import type {
  TargetType,
  AuthState,
  ExecutionMode,
  ErrorRecovery,
  CredentialRef,
  NormalizedFinding,
  EvidencePackage,
  ArtifactRef,
  ArtifactType,
} from "../shared/types"

export { Severity, Confidence }
export type {
  TargetType,
  AuthState,
  ExecutionMode,
  ErrorRecovery,
  CredentialRef,
  NormalizedFinding,
  EvidencePackage,
  ArtifactRef,
  ArtifactType,
}

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

export interface PhaseExecutionRequest {
  phaseId: string
  name: string
  workflowName: string
  target: string
  requiredCapabilities: Capability[]
  credentials?: CredentialRef[]
  config: Record<string, unknown>
  previousPhaseResults: PhaseExecutionResult[]
  approvalGateName?: string
  execution?: "deterministic" | "llm_driven"
  /** Whether tools in this phase execute in parallel or sequentially.
   *  Drawn from the workflow YAML `execution` property. */
  toolExecution?: "parallel" | "sequential" | "llm_driven"
  replanCycle?: boolean
}

export interface PhaseExecutionResult {
  phaseId: string
  status: "completed" | "failed" | "skipped" | "partial"
  findings: NormalizedFinding[]
  artifacts: ArtifactRef[]
  errors: string[]
  durationMs: number
  hypotheses?: Hypothesis[]
}

export interface AssessmentPlan {
  workflow: string
  phases: PhaseExecutionRequest[]
  errorRecovery: Record<string, ErrorRecovery>
  planCreatedAt: string
}

export interface Hypothesis {
  id: string
  description: string
  confidence: number
  status: string
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
  maxReplans?: number
  hypotheses?: Hypothesis[]
}

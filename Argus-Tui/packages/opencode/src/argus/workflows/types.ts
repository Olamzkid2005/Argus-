import { Capability } from "../shared/capabilities"
import type { ExecutionMode, ErrorRecovery } from "../shared/types"

// WorkflowDefinition is shared with the planner — import it from there to avoid duplication
export type { WorkflowDefinition } from "../planner/types"

export interface PhaseDefinition {
  name: string
  required_capabilities: Capability[]
  execution: ExecutionMode
  error_recovery: ErrorRecovery
  approval_gate?: string
}

export interface ToolRequirement {
  name: string
  capabilities: Capability[]
  requires_auth: boolean
  destructive: boolean
  timeout_seconds: number
  scoring?: {
    confidence_score: number
    coverage_score: number
  }
}

export interface ApprovalGate {
  name: string
  label: string
  require_confirmation: boolean
  destructive: boolean
  auth_testing: boolean
  privilege_escalation: boolean
}

import { Capability } from "../planner/capabilities"
import type { ExecutionMode, ErrorRecovery } from "../planner/types"

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

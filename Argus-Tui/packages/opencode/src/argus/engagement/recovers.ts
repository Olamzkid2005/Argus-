import type { EngagementState, PhaseStatus } from "./types"

export function validateWorkflowVersion(engagement: EngagementState, currentVersion: number): boolean {
  return engagement.workflowVersion === currentVersion
}

export function canResume(engagement: EngagementState): boolean {
  return engagement.status === "RUNNING" || engagement.status === "PAUSED"
}

export function canRetryPhase(status: PhaseStatus): boolean {
  return status === "FAILED" || status === "SKIPPED"
}

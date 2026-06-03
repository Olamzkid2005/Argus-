import type { EngagementState } from "./types"

export function validateWorkflowVersion(engagement: EngagementState, currentVersion: number): boolean {
  return engagement.workflowVersion === currentVersion
}

export function canResume(engagement: EngagementState): boolean {
  return engagement.status === "RUNNING" || engagement.status === "PAUSED"
}

export function canRetryPhase(status: string): boolean {
  return status === "FAILED" || status === "SKIPPED"
}

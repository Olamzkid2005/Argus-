import type { EngagementState, PhaseStatus } from "./types"

export function validateWorkflowVersion(engagement: EngagementState, currentVersion: number): boolean {
  return engagement.workflowVersion === currentVersion
}

export function canResume(engagement: EngagementState): boolean {
  // Stage 6.2 item 4: an interrupted or partially-completed run is resumable;
  // COMPLETED and FAILED are terminal, and CREATED was never started.
  return (
    engagement.status === "RUNNING" ||
    engagement.status === "PAUSED" ||
    engagement.status === "INTERRUPTED" ||
    engagement.status === "PARTIAL"
  )
}

export function canRetryPhase(status: PhaseStatus): boolean {
  return status === "FAILED" || status === "SKIPPED"
}

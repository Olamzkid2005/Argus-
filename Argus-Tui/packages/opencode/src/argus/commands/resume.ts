import { EngagementStore } from "../engagement/store"
import { canResume } from "../engagement/recovers"

export async function resumeCommand(engagementId: string): Promise<string> {
  const store = new EngagementStore()
  const engagement = store.getEngagement(engagementId)

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  if (!canResume(engagement)) {
    return `Engagement ${engagementId} cannot be resumed (status: ${engagement.status})`
  }

  // TODO: Resume is not fully implemented yet. It should re-connect to bridge,
  // re-load the plan, skip completed phases, and continue from the first
  // incomplete phase. Currently it only validates that the engagement can be resumed.
  return `Resuming engagement ${engagementId}`
}

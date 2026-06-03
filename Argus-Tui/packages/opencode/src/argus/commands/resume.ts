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

  return `Resuming engagement ${engagementId}`
}

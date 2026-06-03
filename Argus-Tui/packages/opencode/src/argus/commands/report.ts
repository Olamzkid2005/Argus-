import { ReportGenerator } from "../reporting/generator"
import { EngagementStore } from "../engagement/store"

export async function reportCommand(engagementId: string, format: "markdown" | "json" | "sarif" = "markdown"): Promise<string> {
  const store = new EngagementStore()
  const engagement = store.getEngagement(engagementId)

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  const generator = new ReportGenerator()

  switch (format) {
    case "json":
      return generator.generateJSON([], engagementId, engagement.target, engagement.workflow)
    case "sarif":
      return generator.generateSARIF([], engagementId, engagement.target)
    default:
      return generator.generateMarkdown([], engagementId, engagement.target, engagement.workflow)
  }
}

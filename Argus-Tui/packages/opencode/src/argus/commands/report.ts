import { ReportGenerator } from "../reporting/generator"
import { EngagementStore } from "../engagement/store"

export async function reportCommand(engagementId: string, format: "markdown" | "json" | "sarif" | "html" = "markdown"): Promise<string> {
  const store = new EngagementStore()
  const engagement = store.getEngagement(engagementId)

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  const findings = store.getFindings(engagementId)
  const generator = new ReportGenerator()

  switch (format) {
    case "json":
      return generator.generateJSON(findings, engagementId, engagement.target, engagement.workflow)
    case "sarif":
      return generator.generateSARIF(findings, engagementId, engagement.target, engagement.workflow)
    case "html":
      return generator.generateHTML(findings, engagementId, engagement.target, engagement.workflow)
    default:
      return generator.generateMarkdown(findings, engagementId, engagement.target, engagement.workflow)
  }
}

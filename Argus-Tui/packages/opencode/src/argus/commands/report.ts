import { ReportGenerator } from "../reporting/generator"
import { EngagementStore } from "../engagement/store"
import { Feature, getFeatureFlags } from "../config/feature-flags"
import type { FindingAnalysis } from "../shared/types"

async function enhanceReportWithAnalysis(engagementId: string): Promise<FindingAnalysis[]> {
  const store = new EngagementStore()
  const findings = store.getFindings(engagementId)
  const { FindingAnalyzer } = await import("../engagement/finding-analyzer")
  const analyzer = new FindingAnalyzer(store)
  const CONCURRENCY = 3
  const results: FindingAnalysis[] = []

  for (let i = 0; i < findings.length; i += CONCURRENCY) {
    const batch = findings.slice(i, i + CONCURRENCY)
    const batchResults = await Promise.allSettled(
      batch.map((f) => analyzer.analyze(f, []))
    )
    for (const r of batchResults) {
      if (r.status === "fulfilled" && r.value) results.push(r.value)
      else if (r.status === "rejected") console.warn("Analysis failed for finding:", r.reason)
    }
    if (i + CONCURRENCY < findings.length) {
      await new Promise((r) => setTimeout(r, 1000))
    }
  }

  return results
}

export async function reportCommand(engagementId: string, format: "markdown" | "json" | "sarif" | "html" = "markdown", store?: EngagementStore): Promise<string> {
  const db = store ?? new EngagementStore()
  const engagement = db.getEngagement(engagementId)

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  const findings = db.getFindings(engagementId)
  const generator = new ReportGenerator()

  if (getFeatureFlags().isEnabled(Feature.LLM_FINDING_ANALYSIS)) {
    const analyses = await enhanceReportWithAnalysis(engagementId)
    generator.setAnalyses(analyses)
  }

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

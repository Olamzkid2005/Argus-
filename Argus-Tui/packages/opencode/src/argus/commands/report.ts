import { ReportGenerator } from "../reporting/generator"
import { EngagementStore } from "../engagement/store"
import { FindingAnalyzer } from "../engagement/finding-analyzer"
import { getLlmClient } from "../engagement/llm-client"
import { Feature, getFeatureFlags } from "../config/feature-flags"
import type { FindingAnalysis } from "../shared/types"
import type { ProgressCallback } from "../shared/progress"

export async function enhanceReportWithAnalysis(
  engagementId: string,
  onProgress?: ProgressCallback,
  injectedAnalyzer?: FindingAnalyzer,
  store?: EngagementStore,
): Promise<FindingAnalysis[]> {
  const db = store ?? new EngagementStore()
  const findings = db.getFindings(engagementId)
  const analyzer = injectedAnalyzer ?? await (async () => {
    const { FindingAnalyzer: FA } = await import("../engagement/finding-analyzer")
    const { getLlmClient: getLLM } = await import("../engagement/llm-client")
    const llmClient = getLLM()
    return new FA(db, llmClient.isConfigured() ? llmClient : undefined)
  })()
  const CONCURRENCY = 3
  const results: FindingAnalysis[] = []
  let processed = 0

  for (let i = 0; i < findings.length; i += CONCURRENCY) {
    const batch = findings.slice(i, i + CONCURRENCY)

    // Emit progress before batch processing
    onProgress?.({
      type: "analysis_progress",
      current: processed,
      total: findings.length,
    })

    const batchResults = await Promise.allSettled(
      batch.map((f) => analyzer.analyze(f, []))
    )
    for (const r of batchResults) {
      if (r.status === "fulfilled" && r.value) {
        results.push(r.value)
      } else if (r.status === "fulfilled" && !r.value) {
        console.warn("Analysis returned null for finding — LLM client may not be configured")
      } else if (r.status === "rejected") {
        console.warn("Analysis failed for finding:", r.reason)
      }
      processed++
    }

    // Rate-limit gap between batches
    if (i + CONCURRENCY < findings.length) {
      await new Promise((r) => setTimeout(r, 1000))
    }
  }

  // Final progress emission
  onProgress?.({ type: "analysis_progress", current: findings.length, total: findings.length })

  return results
}

export async function reportCommand(
  engagementId: string,
  format: "markdown" | "json" | "sarif" | "html" = "markdown",
  store?: EngagementStore,
  onProgress?: ProgressCallback,
  useLLM?: boolean,
): Promise<string> {
  const db = store ?? new EngagementStore()
  const engagement = db.getEngagement(engagementId)

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  const findings = db.getFindings(engagementId)
  const generator = new ReportGenerator()

  const llmEnabled = useLLM ?? getFeatureFlags().isEnabled(Feature.LLM_FINDING_ANALYSIS)
  if (llmEnabled) {
    const llmClient = getLlmClient()
    const analyzer = new FindingAnalyzer(db, llmClient.isConfigured() ? llmClient : undefined)
    const analyses = await enhanceReportWithAnalysis(engagementId, onProgress, analyzer)
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

import type { FindingAnalysis, NormalizedFinding } from "../shared/types"

export type ReportFormat = "markdown" | "sarif" | "json" | "html"

export interface Report {
  engagementId: string
  target: string
  workflow: string
  createdAt: string
  findings: NormalizedFinding[]
  analyses?: FindingAnalysis[]
  summary: ReportSummary
}

export interface ReportSummary {
  totalFindings: number
  analyzedCount?: number
  bySeverity: Record<string, number>
  byConfidence: Record<string, number>
  byStatus: Record<string, number>
}

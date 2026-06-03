import type { NormalizedFinding } from "../planner/types"

export type ReportFormat = "markdown" | "html" | "sarif" | "json"

export interface Report {
  engagementId: string
  target: string
  workflow: string
  createdAt: string
  findings: NormalizedFinding[]
  summary: ReportSummary
}

export interface ReportSummary {
  totalFindings: number
  bySeverity: Record<string, number>
  byConfidence: Record<string, number>
  byStatus: Record<string, number>
}

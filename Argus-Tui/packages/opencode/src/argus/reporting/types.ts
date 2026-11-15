import type { FindingAnalysis, NormalizedFinding } from "../shared/types"

export type ReportFormat = "markdown" | "sarif" | "json" | "html"

export interface Report {
  engagementId: string
  target: string
  workflow: string
  createdAt: string
  findings: NormalizedFinding[]
  analyses?: FindingAnalysis[]
  execution?: ReportExecutionSnapshot
  summary: ReportSummary
}

export interface ProofEvidenceArtifact {
  id: string
  path: string
  type: string
  sizeBytes: number
}

export interface ProofEvidencePackage {
  packageId: string
  packageHash: string
  createdAt: number
  artifacts: ProofEvidenceArtifact[]
}

export interface ReportExecutionProvenanceAction {
  tool: string
  outcome: string
  reasoning?: string
  identity?: string
  source: "llm" | "deterministic" | "fallback"
  detail?: string
}

export interface ReportExecutionAction {
  id: string
  tool: string
  status: "succeeded" | "failed" | "skipped" | "in_flight"
  readOnly: boolean
  startedAt?: string
  completedAt?: string
  error?: string
  /** Why this action was selected; never a secret value. */
  reason?: string
  source?: "plan" | "replan-rule" | "replan-llm" | "replan-chain" | "retry" | "resume"
  /** Operator, role reference, or worker identity label that chose it. */
  by?: string
  /** Tool-level actions actually issued inside this phase/action. */
  provenanceActions?: ReportExecutionProvenanceAction[]
}

export interface ReportExecutionBudget {
  deadlineAt?: string
  llmCalls: number
  llmFailures: number
  inputTokens: number
  outputTokens: number
  costUsd: number
  costKnown: boolean
  toolCalls: number
  requestCount: number
  source: "local-estimate" | "merged (ts driver + worker agent sessions)"
  workerToolCalls?: number
  discrepancies: string[]
}

export interface ReportExecutionSnapshot {
  scope: string[]
  model?: string
  limits?: Record<string, number | string | null>
  actions: ReportExecutionAction[]
  observations: string[]
  secretRefs: string[]
  authIdentities: string[]
  budgetUsage: ReportExecutionBudget
  startedAt?: string
  checkpointAt: string
  completedAt?: string
}

export interface ProofControlComparison {
  kind: string
  description?: string
  outcome?: string
  reference?: string
}

export interface ProofLedgerEntry {
  findingId: string
  title: string
  proofStatus: string
  verifier?: string
  confidence?: number
  verifiedAt?: string
  controls: number
  controlComparisons: ProofControlComparison[]
  evidencePackages: number
  evidenceArtifacts: number
  evidencePackageHashes: string[]
}

export interface ProofLedger {
  totalFindings: number
  verifiedOutcomes: number
  reproduced: number
  suspected: number
  inconclusive: number
  notReproduced: number
  unsupported: number
  unverified: number
  byProofStatus: Record<string, number>
  reproducedFindingIds: string[]
  attentionFindingIds: string[]
  coverageGaps: string[]
  evidencePackages: number
  evidenceArtifacts: number
  entries: ProofLedgerEntry[]
}

export interface ReportContentOptions {
  coverageGaps?: string[]
  evidenceByFinding?: Record<string, ProofEvidencePackage[]>
  execution?: ReportExecutionSnapshot
}

export interface ReportSummary {
  totalFindings: number
  analyzedCount?: number
  bySeverity: Record<string, number>
  byConfidence: Record<string, number>
  byStatus: Record<string, number>
  proof: ProofLedger
}

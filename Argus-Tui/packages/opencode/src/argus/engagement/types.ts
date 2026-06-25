import type { ExecutionMode } from "../shared/types"
import type { FindingAnalysis, NormalizedFinding } from "../shared/types"

export type EngagementStatus = "CREATED" | "RUNNING" | "PAUSED" | "COMPLETED" | "FAILED"
export type PhaseStatus = "PENDING" | "RUNNING" | "COMPLETED" | "PARTIAL" | "FAILED" | "SKIPPED"
export type FindingStatus = "PENDING" | "CONFIRMED" | "REJECTED" | "FINALIZED" | "DISMISSED"

export interface EngagementState {
  id: string
  target: string
  workflow: string
  workflowVersion: number
  status: EngagementStatus
  schemaVersion: number
  storageVersion: number
  createdAt: string
  updatedAt: string
}

/**
 * IEngagementStore — Interface for engagement storage.
 *
 * Abstracts the storage layer so consumers depend on the interface,
 * not the concrete implementation. This allows:
 *   1. Swapping the implementation (e.g. encrypted store for 14c)
 *   2. Mocking in tests
 *   3. The 14b dual-DB refactor without touching 7+ consumer files
 *
 * All methods that take an engagementId route to the per-engagement DB
 * when the store implements 14b's dual-DB architecture.
 */
export interface IEngagementStore {
  close(): void

  // ── Engagement CRUD (root DB) ──
  createEngagement(target: string, workflow: string): EngagementState
  getEngagement(id: string): EngagementState | null
  saveEngagement(engagement: EngagementState): void
  updateStatus(id: string, status: EngagementStatus): void
  listEngagements(): EngagementState[]

  // ── Phases (per-engagement DB) ──
  savePhases(id: string, records: PhaseRecord[]): void
  savePhase(engagementId: string, record: PhaseRecord): void
  getPhases(id: string): PhaseRecord[]

  // ── Findings ──
  saveFindings(engagementId: string, records: NormalizedFinding[]): void
  getFinding(id: string): NormalizedFinding | null
  getFindingEngagementId(findingId: string): string | null
  getFindings(engagementId: string): NormalizedFinding[]
  getFindingCountsByEngagementIds(ids: string[]): Map<string, { total: number; critical: number; confirmed: number }>

  // ── Audit log ──
  appendAuditLog(engagementId: string, eventType: string, message: string, metadata?: Record<string, unknown>): void
  getAuditLog(engagementId: string): Array<{ id: string; eventType: string; message: string; metadata: Record<string, unknown>; createdAt: number }>

  // ── Evidence ──
  saveEvidencePackage(id: string, findingId: string, packageHash: string): void
  getEvidencePackages(findingId: string): Array<{ id: string; packageHash: string; createdAt: number }>
  getEvidenceByEngagement(engagementId: string): Array<{
    findingId: string
    findingTitle: string
    packages: Array<{
      id: string
      packageHash: string
      createdAt: number
      artifacts: Array<{ id: string; path: string; type: string; sizeBytes: number }>
    }>
  }>
  getEvidenceCountsByEngagement(engagementId: string): Record<string, number>

  // ── Artifacts ──
  saveArtifact(id: string, packageId: string, path: string, sha256: string, sizeBytes: number, type: string): void
  getArtifacts(packageId: string): Array<{ id: string; path: string; sha256: string; sizeBytes: number; type: string }>

  // ── Engagement detail (bundled query) ──
  getEngagementDetail(engagementId: string): {
    engagement: EngagementState
    findings: NormalizedFinding[]
    evidence: ReturnType<IEngagementStore["getEvidenceByEngagement"]>
    auditLog: ReturnType<IEngagementStore["getAuditLog"]>
  } | null

  // ── Workflow snapshots ──
  saveWorkflowSnapshot(id: string, engagementId: string, workflowName: string, workflowVersion: number, workflowYaml: string): void
  getWorkflowSnapshots(engagementId: string): Array<{ id: string; workflowName: string; workflowVersion: number; workflowYaml: string; createdAt: number }>

  // ── Finding analysis ──
  saveFindingAnalysis(analysis: FindingAnalysis): void
  getFindingAnalysis(findingId: string): FindingAnalysis | null
  deleteFindingAnalysis(findingId: string): void
  getValidAnalysis(findingId: string): FindingAnalysis | null
}

export interface PhaseRecord {
  id: string
  engagementId: string
  name: string
  status: PhaseStatus
  capabilities: string[]
  executionMode: ExecutionMode
  startedAt?: string
  completedAt?: string
  error?: string
  replanCycle: boolean
}

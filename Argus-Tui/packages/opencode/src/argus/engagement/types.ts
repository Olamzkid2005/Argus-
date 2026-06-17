import type { ExecutionMode } from "../shared/types"

export type EngagementStatus = "CREATED" | "RUNNING" | "PAUSED" | "COMPLETED" | "FAILED"
export type PhaseStatus = "PENDING" | "RUNNING" | "COMPLETED" | "PARTIAL" | "FAILED" | "SKIPPED"
export type FindingStatus = "PENDING" | "CONFIRMED" | "REJECTED" | "FINALIZED"

export interface EngagementState {
  id: string
  target: string
  workflow: string
  workflowVersion: number
  status: EngagementStatus
  schemaVersion: number
  createdAt: string
  updatedAt: string
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

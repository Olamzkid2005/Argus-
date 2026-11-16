/**
 * Persisted engagement checkpoints for restart safety (Stage 6.2).
 *
 * `resume.ts` used to re-plan from the target, which meant a resumed run could
 * invent a different assessment than the one the operator approved, with a
 * fresh budget and a fresh plan. This module defines the checkpoint that a run
 * saves at phase boundaries and the rules that decide whether it may be
 * resumed:
 *
 *  - the approved plan/policy, workflow name and version, scope, model, limits,
 *    secret references, action signatures/results, observations and proof
 *    status all live in the checkpoint;
 *  - timestamps are explicit UTC strings, and a checkpoint with missing or
 *    out-of-order timestamps is rejected rather than treated as progress;
 *  - a workflow/version or scope mismatch is rejected;
 *  - a completed action is never replayed; an interrupted read-only action may
 *    be retried; an interrupted state-changing action is ambiguous and pauses
 *    the run instead of being replayed automatically;
 *  - usage may only grow across checkpoints.
 */

import type { EngagementState, PhaseRecord } from "./types"
import type { AssessmentPlan } from "../planner/types"

export type CheckpointActionSource = "plan" | "replan-rule" | "replan-llm" | "replan-chain" | "retry" | "resume"

export interface CheckpointProvenanceAction {
  tool: string
  outcome: string
  reasoning?: string
  identity?: string
  source: "llm" | "deterministic" | "fallback"
  detail?: string
}

export interface CheckpointActionProvenance {
  source: CheckpointActionSource
  /** Why this action/phase was selected; never a secret value. */
  reason?: string
  /** Operator, role reference, or worker identity label that chose it. */
  by?: string
  /** Tool-level actions actually issued inside this phase/action. */
  actions?: CheckpointProvenanceAction[]
}

export interface CheckpointAction {
  id: string
  tool: string
  /** Whole-action signature: tool + canonical arguments. */
  signature?: string
  status: "succeeded" | "failed" | "skipped" | "in_flight"
  /** Read-only actions may be retried after an interruption; others may not. */
  readOnly: boolean
  startedAt?: string
  completedAt?: string
  /** Why this action did not succeed; absent on success. */
  error?: string
  /** Why this action was selected and who/what selected it. */
  reason?: string
  source?: CheckpointActionSource
  by?: string
  provenance?: CheckpointActionProvenance
}

export interface CheckpointWorkerBudget {
  /** Worker-recorded hybrid tool executions for this engagement. */
  toolCalls: number
  executedTools: string[]
  /** Non-secret worker identity labels observed in session executions. */
  identities: string[]
  sessions: number
}

export interface CheckpointBudgetUsage {
  deadlineAt?: string
  llmCalls: number
  llmFailures: number
  inputTokens: number
  outputTokens: number
  costUsd: number
  /** False when the run could not price a call — explicit unknown cost. */
  costKnown: boolean
  toolCalls: number
  requestCount: number
}

export interface EngagementCheckpoint {
  engagementId: string
  workflow: string
  workflowVersion: number
  /** Approved plan, stored verbatim so resume never re-plans from scratch. */
  plan: AssessmentPlan
  /** Authorized scope entries at approval time. */
  scope: string[]
  model?: string
  limits?: Record<string, number | string | null>
  actions: CheckpointAction[]
  actionSignatures: Record<string, string>
  observations: string[]
  /** References into the protected credential store — never secret values. */
  secretRefs: string[]
  /** Non-secret identity labels authorized/observed for this engagement. */
  authIdentities?: string[]
  proofStatus: Record<string, string>
  budgetUsage: CheckpointBudgetUsage
  /** Worker session ledger used to reconcile the TS-side usage record. */
  workerBudget?: CheckpointWorkerBudget
  /** Explicit UTC timestamps; none may be inferred from progress. */
  createdAt: string
  startedAt?: string
  checkpointAt: string
  completedAt?: string
}

export interface ResumeValidationOptions {
  currentWorkflowName: string
  currentWorkflowVersion: number
  /** Scope that is authorized for this resume. */
  currentScope: string[]
  now?: Date
}

export interface ResumePlan {
  ok: boolean
  reasons: string[]
  /** Read-only actions that were interrupted and may safely be retried. */
  retryActionIds: string[]
  /** Interrupted state-changing actions: ambiguous, so the run must pause. */
  blockedActionIds: string[]
  /** Completed actions; these are never run again. */
  completedActionIds: string[]
}

function parseUtc(value: string | undefined, label: string, reasons: string[]): number | null {
  if (!value) {
    reasons.push(`missing ${label}`)
    return null
  }
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) {
    reasons.push(`invalid ${label}: ${value}`)
    return null
  }
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(value)) {
    reasons.push(`${label} is not an explicit UTC timestamp: ${value}`)
    return null
  }
  return parsed
}

/** The workflow phases whose replay could change target state. */
const STATE_CHANGING_PHASES = new Set(["web_exploitation", "api_exploitation"])

function normalizeScopeEntry(entry: string): string {
  return entry.trim().replace(/\/+$/, "").toLowerCase()
}

/** True when every checkpoint scope entry is still authorized. */
export function scopeIsNotWider(checkpointScope: string[], currentScope: string[]): boolean {
  if (checkpointScope.length === 0) return true
  if (currentScope.length === 0) return false
  const current = new Set(currentScope.map(normalizeScopeEntry))
  return checkpointScope.every((entry) => current.has(normalizeScopeEntry(entry)))
}

/** Completed work is never replayed; only interrupted read-only work retries. */
export function reconcileActions(actions: CheckpointAction[]): {
  retryActionIds: string[]
  blockedActionIds: string[]
  completedActionIds: string[]
} {
  const retryActionIds: string[] = []
  const blockedActionIds: string[] = []
  const completedActionIds: string[] = []
  for (const action of actions) {
    if (action.status === "succeeded") {
      completedActionIds.push(action.id)
      continue
    }
    if (action.status === "failed" || action.status === "skipped") continue
    // A phase that never started has nothing in flight: it is simply still to
    // do. Counting it as ambiguous paused every interrupted run whose later
    // phases were state-changing, so a restart could never be resumed at all.
    if (!action.startedAt) continue
    // in_flight: interruption is ambiguous for a state-changing action.
    if (action.readOnly) retryActionIds.push(action.id)
    else blockedActionIds.push(action.id)
  }
  return { retryActionIds, blockedActionIds, completedActionIds }
}

export interface CheckpointBudgetReconciliation {
  source: "local-estimate" | "merged (ts driver + worker agent sessions)"
  toolCalls: number
  discrepancies: string[]
}

/**
 * Merge the TS-side usage record with the worker's session ledger.
 *
 * The worker ledger only sees hybrid agent sessions, so it cannot replace the
 * driver count outright; the conservative reconciled count is their maximum.
 * Every mismatch is returned as an explicit discrepancy instead of being
 * averaged away, and cost remains explicitly unknown unless the worker ledger
 * priced it. Deterministic/direct tool calls never appear in agent sessions.
 */
export function reconcileCheckpointBudget(
  local: CheckpointBudgetUsage,
  worker?: CheckpointWorkerBudget,
): CheckpointBudgetReconciliation {
  if (!worker) {
    return { source: "local-estimate", toolCalls: local.toolCalls, discrepancies: ["no worker session ledger was attached to this checkpoint"] }
  }
  const discrepancies: string[] = []
  if (worker.toolCalls !== local.toolCalls) {
    discrepancies.push(`worker sessions recorded ${worker.toolCalls} tool call(s); TS driver recorded ${local.toolCalls}`)
  }
  if (worker.sessions === 0 && local.toolCalls > 0) {
    discrepancies.push("worker sessions recorded no linked agent sessions, so deterministic/direct tool calls cannot be cross-checked")
  } else if (worker.sessions > 0 && local.toolCalls > worker.toolCalls) {
    discrepancies.push("TS driver count includes calls outside worker agent sessions (deterministic/direct execution)")
  }
  return {
    source: "merged (ts driver + worker agent sessions)",
    toolCalls: Math.max(local.toolCalls, worker.toolCalls),
    discrepancies,
  }
}

/**
 * Decide whether this checkpoint may be resumed, and what may be replayed.
 *
 * Every rejection returns a human-readable reason; resume must not fall back to
 * inventing a fresh plan when validation fails.
 */
export function validateCheckpoint(
  checkpoint: EngagementCheckpoint,
  options: ResumeValidationOptions,
): ResumePlan {
  const reasons: string[] = []

  const created = parseUtc(checkpoint.createdAt, "createdAt", reasons)
  const started = parseUtc(checkpoint.startedAt, "startedAt", reasons)
  const checkpointed = parseUtc(checkpoint.checkpointAt, "checkpointAt", reasons)
  const completed = checkpoint.completedAt
    ? parseUtc(checkpoint.completedAt, "completedAt", reasons)
    : null

  if (created != null && started != null && started < created) {
    reasons.push("startedAt precedes createdAt")
  }
  if (started != null && checkpointed != null && checkpointed < started) {
    reasons.push("checkpointAt precedes startedAt")
  }
  if (checkpointed != null && completed != null && completed < checkpointed) {
    reasons.push("completedAt precedes checkpointAt")
  }

  if (checkpoint.workflow !== options.currentWorkflowName) {
    reasons.push(
      `workflow mismatch: checkpoint is ${checkpoint.workflow}, current is ${options.currentWorkflowName}`,
    )
  }
  if (checkpoint.workflowVersion !== options.currentWorkflowVersion) {
    reasons.push(
      `workflow version mismatch: checkpoint ${checkpoint.workflowVersion}, current ${options.currentWorkflowVersion}`,
    )
  }

  if (!scopeIsNotWider(checkpoint.scope, options.currentScope)) {
    reasons.push("checkpoint scope is wider than the currently authorized scope")
  }

  if (!checkpoint.plan || !Array.isArray(checkpoint.plan.phases)) {
    reasons.push("checkpoint has no approved plan")
  }

  if (checkpoint.budgetUsage == null) {
    reasons.push("checkpoint has no budget usage")
  }

  if (checkpoint.authIdentities !== undefined) {
    const validIdentity = (identity: unknown): boolean => {
      if (typeof identity !== "string" || identity.trim().length === 0) return false
      if (identity.startsWith("credential:")) return identity.slice("credential:".length).trim().length > 0
      if (identity.startsWith("worker:")) return identity.slice("worker:".length).trim().length > 0
      return false
    }
    if (!Array.isArray(checkpoint.authIdentities) || checkpoint.authIdentities.some((identity) => !validIdentity(identity))) {
      reasons.push("checkpoint has invalid auth identities")
    }
  }

  if (checkpoint.workerBudget !== undefined) {
    const workerBudget = checkpoint.workerBudget
    const validToolCalls = Number.isInteger(workerBudget.toolCalls) && workerBudget.toolCalls >= 0
    const validTools = Array.isArray(workerBudget.executedTools) && workerBudget.executedTools.every((tool) => typeof tool === "string" && tool.length > 0)
    const validIdentities = Array.isArray(workerBudget.identities) && workerBudget.identities.every((identity) => typeof identity === "string" && identity.length > 0)
    const validSessions = Number.isInteger(workerBudget.sessions) && workerBudget.sessions >= 0
    if (!validToolCalls || !validTools || !validIdentities || !validSessions) {
      reasons.push("checkpoint has an invalid worker budget ledger")
    }
  }

  const now = options.now ?? new Date()
  if (checkpoint.budgetUsage?.deadlineAt) {
    const deadline = parseUtc(checkpoint.budgetUsage.deadlineAt, "budgetUsage.deadlineAt", reasons)
    if (deadline != null && now.getTime() > deadline) {
      reasons.push("engagement deadline has already passed")
    }
  }

  // No actions yet is valid: the run was interrupted before executing.
  const reconciled = reconcileActions(checkpoint.actions ?? [])

  return {
    ok: reasons.length === 0,
    reasons,
    ...reconciled,
  }
}

/**
 * Build the checkpoint a run stores. Phase records become action records:
 * a phase that never finished is `in_flight` and its mutability decides whether
 * it may be retried or must pause the resume.
 */
export function buildCheckpoint(params: {
  engagement: EngagementState
  plan: AssessmentPlan
  phases: PhaseRecord[]
  scope: string[]
  model?: string
  limits?: Record<string, number | string | null>
  secretRefs?: string[]
  authIdentities?: string[]
  observations?: string[]
  proofStatus?: Record<string, string>
  budgetUsage: CheckpointBudgetUsage
  workerBudget?: CheckpointWorkerBudget
  actionDetails?: Record<string, Partial<Pick<CheckpointAction, "reason" | "source" | "by"> & { provenance?: CheckpointActionProvenance }>>
  startedAt?: string
  completedAt?: string
  now?: Date
}): EngagementCheckpoint {
  const now = (params.now ?? new Date()).toISOString()
  const actions: CheckpointAction[] = params.phases.map((phase) => {
    let status: CheckpointAction["status"] = "in_flight"
    if (phase.status === "COMPLETED" || phase.status === "PARTIAL") status = "succeeded"
    else if (phase.status === "FAILED") status = "failed"
    else if (phase.status === "SKIPPED") status = "skipped"
    // Never started (PENDING/no start time) is not an interrupted action.
    else if (!phase.startedAt) status = "skipped"
    const details = params.actionDetails?.[phase.id]
    return {
      id: phase.id,
      tool: phase.name,
      // Action identity: the phase and the capabilities it was approved for.
      signature: `${phase.name}:${[...phase.capabilities].sort().join("+")}`,
      status,
      readOnly: !STATE_CHANGING_PHASES.has(phase.name.toLowerCase()),
      startedAt: phase.startedAt,
      completedAt: phase.completedAt,
      error: phase.error,
      reason: details?.reason,
      source: details?.source,
      by: details?.by,
      provenance: details?.provenance ? { ...details.provenance, actions: details.provenance.actions?.map((action) => ({ ...action })) } : undefined,
    }
  })

  const actionSignatures: Record<string, string> = {}
  for (const action of actions) {
    if (action.signature) actionSignatures[action.id] = action.signature
  }

  return {
    engagementId: params.engagement.id,
    workflow: params.engagement.workflow,
    workflowVersion: params.engagement.workflowVersion,
    plan: params.plan,
    scope: params.scope,
    model: params.model,
    limits: params.limits,
    actions,
    actionSignatures,
    observations: params.observations ?? [],
    secretRefs: params.secretRefs ?? [],
    authIdentities: params.authIdentities ? [...params.authIdentities] : undefined,
    proofStatus: params.proofStatus ?? {},
    budgetUsage: params.budgetUsage,
    workerBudget: params.workerBudget ? { ...params.workerBudget, executedTools: [...params.workerBudget.executedTools], identities: [...params.workerBudget.identities] } : undefined,
    createdAt: params.engagement.createdAt,
    startedAt: params.startedAt,
    checkpointAt: now,
    completedAt: params.completedAt,
  }
}

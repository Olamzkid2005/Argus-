import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import { WorkersBridge } from "../bridge/mcp-client"
import { EngagementStore } from "../engagement/store"
import type { IEngagementStore } from "../engagement/types"
import { CredentialStore } from "../engagement/credentials"
import { ConfidenceEngine } from "../engagement/confidence"
import { ReportGenerator, persistedReportOptions } from "../reporting/generator"
import { canResume } from "../engagement/recovery"
import {
  buildCheckpoint,
  validateCheckpoint,
  type CheckpointBudgetUsage,
} from "../engagement/checkpoint"
import { scopeEntriesFor } from "../browser/scope-guard"
import { detectTargetType, detectAuthState } from "../planner/strategy"
import { Capability } from "../planner/capabilities"
import type { PhaseRecord } from "../engagement/types"
import type { NormalizedFinding } from "../shared/types"
import type { ProgressEvent } from "../shared/progress"
import type { PlannerContext } from "../planner/types"
import { homedir } from "os"
import { join } from "path"
import { PROJECT_ROOT } from "../shared/path"

/**
 * Authenticated resume requires every `credential:<role>` reference saved in
 * the checkpoint to be present under the operator's current credential
 * namespace. Worker-observed `worker:<identity>` labels are provenance only
 * and cannot satisfy a protected secret reference.
 */
export function missingCredentialRefs(secretRefs: string[], availableRoles: string[]): string[] {
  const available = new Set(availableRoles)
  return secretRefs.filter((ref) => {
    if (!ref.startsWith("credential:")) return true
    const role = ref.slice("credential:".length)
    return role.length === 0 || !available.has(role)
  })
}

export async function resumeCommand(
  engagementId: string,
  options?: {
    workersPath?: string
    workflowsPath?: string
    useLLM?: boolean
    onProgress?: (event: ProgressEvent | string) => void
    storeOverride?: IEngagementStore
    /** Test seam: execute phases without spawning the MCP worker. */
    executorOverride?: Pick<
      InProcessExecutor,
      "loadGates" | "setOnProgress" | "execute"
    >
    bridgeOverride?: Pick<WorkersBridge, "connect" | "disconnect">
  },
): Promise<string> {
  const store = options?.storeOverride ?? new EngagementStore()
  const engagement = store.getEngagement(engagementId)
  const emit = options?.onProgress ?? (() => {})

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  if (!canResume(engagement)) {
    return `Engagement ${engagementId} cannot be resumed (status: ${engagement.status})`
  }

  const workflowsDir = options?.workflowsPath ?? join(PROJECT_ROOT, "Argus-Tui/packages/opencode/src/argus/workflows")
  const toolsPath = join(workflowsDir, "tool-definitions.yaml")

  // Load registries
  const workflowRegistry = new WorkflowRegistry(workflowsDir)
  workflowRegistry.loadAll()

  const toolRegistry = new ToolRegistry()
  toolRegistry.load(toolsPath)

  // Stage 6.2: resume the saved run, not a newly invented assessment. The
  // approved plan and its policy are loaded from the checkpoint; re-planning
  // here would let a restart change what the operator authorized.
  const checkpoint = store.getLatestCheckpoint(engagementId)
  if (!checkpoint) {
    store.updateStatus(engagementId, "PAUSED")
    store.appendAuditLog(engagementId, "RESUME_REFUSED",
      "No checkpoint exists for this engagement — nothing is known about the approved plan, so it cannot be resumed.")
    return `Engagement ${engagementId} has no saved checkpoint. It cannot be resumed without inventing a new assessment; start a fresh assessment instead.`
  }

  const workflowDef = workflowRegistry.getWorkflow(checkpoint.workflow)
  // `argus assess` builds its plan in memory and names the workflow
  // "assessment"; there is no YAML for it in the registry. Comparing against a
  // missing definition produced `workflow version mismatch: checkpoint 1,
  // current -1` and refused every assessment ever created, so an interrupted
  // run could never be continued. With no definition to contradict it, the
  // version recorded in the checkpoint is the authority.
  const currentWorkflowVersion = workflowDef?.version ?? checkpoint.workflowVersion
  const currentScope = scopeEntriesFor(engagement.target)
  const validation = validateCheckpoint(checkpoint, {
    currentWorkflowName: checkpoint.workflow,
    currentWorkflowVersion,
    currentScope,
  })

  if (!validation.ok) {
    store.updateStatus(engagementId, "PAUSED")
    store.appendAuditLog(
      engagementId,
      "RESUME_REFUSED",
      `Checkpoint rejected: ${validation.reasons.join("; ")}`,
    )
    return `Engagement ${engagementId} cannot be resumed: ${validation.reasons.join("; ")}`
  }

  // Stage 6.2 item 2: an interrupted state-changing action is ambiguous. Do not
  // replay it automatically; pause for an operator decision instead.
  if (validation.blockedActionIds.length > 0) {
    store.updateStatus(engagementId, "PAUSED")
    store.appendAuditLog(
      engagementId,
      "RESUME_PAUSED",
      `Ambiguous in-flight state-changing action(s): ${validation.blockedActionIds.join(", ")}`,
    )
    return `Engagement ${engagementId} paused: action(s) ${validation.blockedActionIds.join(", ")} were in flight when the run stopped and are not safe to replay automatically. Review them before resuming.`
  }

  const plan = checkpoint.plan
  // Replanning may still happen mid-run, but the base plan is never re-derived.
  const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)

  const storedLimitNumber = (name: string): number | undefined => {
    const stored = checkpoint.limits?.[name]
    if (typeof stored === "number" && Number.isFinite(stored) && stored >= 0) return stored
    const envName = name === "maxReplans" ? "ARGUS_MAX_REPLANS" : "ARGUS_LLM_MAX_REPLANS"
    const raw = process.env[envName]
    if (!raw) return undefined
    const parsed = Number(raw)
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
  }

  // Restore the model and the protected credential references. Secret material
  // itself lives in the encrypted credential store; a missing credential means
  // the authenticated work cannot be resumed truthfully.
  const credStore = new CredentialStore()
  credStore.load()
  const availableRoles = credStore.listRoles()
  const requiredRefs = [
    ...checkpoint.secretRefs,
    ...(checkpoint.authIdentities ?? []).filter((identity) => identity.startsWith("credential:")),
  ]
  const missingRefs = missingCredentialRefs(requiredRefs, availableRoles)
  if (missingRefs.length > 0) {
    store.updateStatus(engagementId, "PAUSED")
    store.appendAuditLog(engagementId, "RESUME_PAUSED",
      `Required credential reference(s) unavailable: ${missingRefs.join(", ")}`)
    return `Engagement ${engagementId} paused: it needs credential reference(s) ${missingRefs.join(", ")} but none are loaded. Restore them before resuming.`
  }
  if (checkpoint.model) {
    try {
      const service = await import("../planner/llm-service")
      await service.LLMPlannerService.switchModel(checkpoint.model)
    } catch (modelErr) {
      store.appendAuditLog(engagementId, "RESUME_MODEL_WARNING",
        `Could not restore model ${checkpoint.model}: ${(modelErr as Error).message}`)
    }
  }

  store.appendAuditLog(engagementId, "RESUME_RESTORED",
    `Restored checkpoint: ${validation.completedActionIds.length} completed action(s), ` +
    `${validation.retryActionIds.length} read-only retry(ies), usage ` +
    `llm=${checkpoint.budgetUsage.llmCalls} tool=${checkpoint.budgetUsage.toolCalls} ` +
    `cost=${checkpoint.budgetUsage.costUsd}${checkpoint.budgetUsage.costKnown ? "" : " (cost unknown)"}`)
  // Read-only actions interrupted mid-flight are scheduled for a real retry:
  // they are treated as incomplete below even if a stale record says otherwise.
  const retryActionIds = new Set(validation.retryActionIds)
  if (retryActionIds.size > 0) {
    const retryNames = plan.phases
      .filter((phase) => retryActionIds.has(phase.phaseId))
      .map((phase) => phase.name)
    store.appendAuditLog(engagementId, "RESUME_RETRY_READ_ONLY",
      `Scheduling interrupted read-only action(s) for retry: ${retryNames.join(", ") || [...retryActionIds].join(", ")}`)
  }

  // Re-connect bridge
  const bridge =
    options?.bridgeOverride ??
    new WorkersBridge(options?.workersPath ?? join(PROJECT_ROOT, "argus-workers/mcp_server.py"))
  await bridge.connect()

  const confidenceEngine = new ConfidenceEngine()
  const executor =
    options?.executorOverride ??
    new InProcessExecutor(
      toolRegistry,
      bridge as WorkersBridge,
      confidenceEngine,
      workflowRegistry,
    )
  executor.loadGates(plan.workflow)
  executor.setOnProgress((event) => { emit(event) })

  credStore.clear()

  // Load existing phases and findings
  const existingPhases = store.getPhases(engagementId)
  const existingFindings = store.getFindings(engagementId)
  // A retried action is incomplete by definition, even if the stored record
  // still looks completed, so exclude its phase name from the skip set.
  const retryPhaseNames = new Set(
    plan.phases.filter((p) => retryActionIds.has(p.phaseId)).map((p) => p.name),
  )
  const completedPhaseNames = new Set(
    existingPhases
      .filter(
        (p) =>
          (p.status === "COMPLETED" || p.status === "PARTIAL") &&
          !retryPhaseNames.has(p.name),
      )
      .map((p) => p.name),
  )

  // Find the first incomplete phase; retried phases were excluded above.
  const startIndex = plan.phases.findIndex(
    (p) => !completedPhaseNames.has(p.name),
  )

  if (startIndex === -1) {
    await bridge.disconnect()
    return `All phases already completed for engagement ${engagementId}`
  }

  store.appendAuditLog(engagementId, "RESUME_START",
    `Resuming engagement from phase ${startIndex} (${plan.phases[startIndex].phaseId})`)

  // Update engagement status back to RUNNING
  store.updateStatus(engagementId, "RUNNING")

  // Build phase records for remaining phases.
  // Match by ID first (exact phase identity), then by name (workflow may have
  // shifted indices). Without name fallback, a reordered workflow would assign
  // PENDING status to all phases, causing the inner loop to re-execute
  // already-completed work.
  const allPhaseRecords = new Map<string, PhaseRecord>()
  for (const p of plan.phases) {
    let record: PhaseRecord | undefined

    // Exact ID match — same phase from the same workflow position
    const byId = existingPhases.find((ep) => ep.id === p.phaseId)
    if (byId) {
      record = byId
    } else {
      // Name fallback — same phase name but possibly shifted index.
      // Only reuse completed/partial status; a PENDING stored phase at a
      // different index is a genuinely new variant of that phase.
      const byName = existingPhases.find(
        (ep) => ep.name === p.name && (ep.status === "COMPLETED" || ep.status === "PARTIAL"),
      )
      record = byName ?? {
        id: p.phaseId,
        engagementId,
        name: p.name,
        status: "PENDING",
        capabilities: p.requiredCapabilities,
        executionMode: p.toolExecution ?? "sequential",
        replanCycle: p.replanCycle ?? false,
      }
    }

    allPhaseRecords.set(p.phaseId, record)
  }

  // Ensure phases are saved
  store.savePhases(engagementId, Array.from(allPhaseRecords.values()))

  // Reconstruct PlannerContext from stored phases
  const targetType = detectTargetType(engagement.target)
  const authState = detectAuthState(engagement.target)
  const executedCapabilities = new Set<Capability>()
  const insertedPhaseIds = new Set<string>()
  let replanCount = 0

  for (const ep of existingPhases) {
    if (ep.replanCycle) replanCount++
    if (ep.status === "COMPLETED" || ep.status === "PARTIAL") {
      for (const cap of ep.capabilities) {
        executedCapabilities.add(cap as Capability)
      }
    }
    insertedPhaseIds.add(ep.id)
  }

  // Execute phases with replan support
  const allFindings: NormalizedFinding[] = [...existingFindings]
  let executionError: Error | null = null

  try {
    let i = startIndex
    while (i < plan.phases.length) {
      const phase = plan.phases[i]

      // Check if phase was already completed; an interrupted read-only action
      // is deliberately not skipped.
      const phaseRecord = allPhaseRecords.get(phase.phaseId)!
      const retrying = retryActionIds.has(phase.phaseId)
      if (
        (phaseRecord.status === "COMPLETED" || phaseRecord.status === "PARTIAL") &&
        !retrying
      ) {
        i++
        continue
      }

      if (retrying) {
        phaseRecord.completedAt = undefined
        phaseRecord.error = undefined
        store.appendAuditLog(engagementId, "PHASE_RETRY_READ_ONLY",
          `Retrying interrupted read-only phase ${phase.name} (${phase.phaseId})`)
      }

      emit({ type: "phase_start", phaseId: phase.phaseId, name: phase.name, total: plan.phases.length, phaseIndex: i })
      phaseRecord.status = "RUNNING"
      phaseRecord.startedAt = new Date().toISOString()
      store.savePhase(engagementId, phaseRecord)

      const result = await executor.execute(phase)

      for (const finding of result.findings) {
        const promoted = confidenceEngine.promote(finding)
        finding.confidence = promoted
        allFindings.push(finding)
      }

      phaseRecord.status = result.status === "failed" ? "FAILED" : result.status === "partial" ? "PARTIAL" : result.status === "skipped" ? "SKIPPED" : "COMPLETED"
      phaseRecord.completedAt = new Date().toISOString()
      if (result.errors.length > 0) phaseRecord.error = result.errors.join("; ")
      store.savePhase(engagementId, phaseRecord)
      store.appendAuditLog(engagementId, "PHASE_COMPLETE",
        `Phase ${phaseRecord.name}: ${phaseRecord.status}`)

      if (phaseRecord.status === "FAILED") {
        emit({ type: "phase_error", phaseId: phase.phaseId, name: phase.name, error: result.errors.join("; ") })
      } else {
        emit({ type: "phase_complete", phaseId: phase.phaseId, name: phase.name, findings: result.findings.length, status: phaseRecord.status })
      }

      for (const cap of phase.requiredCapabilities) {
        executedCapabilities.add(cap)
      }
      insertedPhaseIds.add(phase.phaseId)

      if (!phase.replanCycle) {
        const replanCtx: PlannerContext = {
          target: engagement.target,
          targetType,
          authState,
          findings: allFindings,
          executedCapabilities,
          insertedPhases: insertedPhaseIds,
          replanCount,
          // Stage 6.2 item 2: restore the limits approved with the plan, not
          // whatever the environment happens to say after the restart.
          maxReplans: storedLimitNumber("maxReplans"),
          llmMaxReplans: storedLimitNumber("llmMaxReplans"),
        }
        const replanPhases = await planner.replan(replanCtx)
        replanCount = replanCtx.replanCount

        if (replanPhases && replanPhases.length > 0) {
          emit({ type: "phase_replan", count: replanPhases.length })
          store.appendAuditLog(engagementId, "REPLAN_INSERT",
            `Inserting ${replanPhases.length} replan phase(s) at position ${i + 1}`)

          let insertOffset = 0
          for (const rp of replanPhases) {
            for (const cap of rp.requiredCapabilities) {
              executedCapabilities.add(cap)
            }
            plan.phases.splice(i + 1 + insertOffset, 0, rp)
            insertOffset++
            plan.errorRecovery[rp.phaseId] = "retry_once_then_skip"
            allPhaseRecords.set(rp.phaseId, {
              id: rp.phaseId,
              engagementId,
              name: rp.name,
              status: "PENDING",
              capabilities: rp.requiredCapabilities,
              executionMode: rp.toolExecution ?? "sequential",
              replanCycle: true,
            })
          }
          store.savePhases(engagementId, Array.from(allPhaseRecords.values()))
        }
      }

      i++
    }
  } catch (error) {
    executionError = error as Error
    store.appendAuditLog(engagementId, "RESUME_ERROR",
      `Resume error: ${(error as Error).message}`)
  } finally {
    const allPhasesCompleted = Array.from(allPhaseRecords.values()).every((p) => p.status === "COMPLETED" || p.status === "PARTIAL")
    // Stage 6.2 item 4: explicit terminal state. A resumed run that finished
    // with failed/partial phases is PARTIAL, not COMPLETED.
    const finalStatus = executionError ? "FAILED" : allPhasesCompleted ? "COMPLETED" : "PARTIAL"
    store.updateStatus(engagementId, finalStatus)
    try {
      const budgetUsage: CheckpointBudgetUsage = {
        ...checkpoint.budgetUsage,
        toolCalls: Math.max(checkpoint.budgetUsage.toolCalls, allPhaseRecords.size),
      }
      store.saveCheckpoint(buildCheckpoint({
        engagement: store.getEngagement(engagementId)!,
        plan,
        phases: Array.from(allPhaseRecords.values()),
        scope: checkpoint.scope,
        model: checkpoint.model,
        limits: checkpoint.limits,
        secretRefs: checkpoint.secretRefs,
        proofStatus: checkpoint.proofStatus,
        budgetUsage,
        startedAt: checkpoint.startedAt,
        completedAt: new Date().toISOString(),
      }))
    } catch (checkpointErr) {
      // No false success: a run whose checkpoint could not be written is a
      // failure, because the next restart would have no trustworthy record.
      executionError = executionError ?? (checkpointErr as Error)
      store.updateStatus(engagementId, "FAILED")
      store.appendAuditLog(engagementId, "CHECKPOINT_SAVE_FAILED",
        `Could not persist resume checkpoint: ${(checkpointErr as Error).message}`)
    }
    store.saveFindings(engagementId, allFindings)
    store.appendAuditLog(engagementId, "RESUME_COMPLETE",
      executionError
        ? `Resume failed: ${executionError.message}`
        : `Resume completed — ${allFindings.length - existingFindings.length} new finding(s)`)
    emit({ type: "scan_complete", totalFindings: allFindings.length })
    await bridge.disconnect()
  }

  // Generate report
  if (!executionError) {
    const reportGen = new ReportGenerator()
    const report = reportGen.generateMarkdown(
      allFindings,
      engagementId,
      engagement.target,
      engagement.workflow,
      persistedReportOptions(store, engagementId),
    )
    // Same reason as `assess`: a resumed run must leave its report on disk, not
    // only in the terminal that happened to be watching.
    try {
      const reportPath = reportGen.writeArtifact(engagementId, report, "markdown")
      return `${report}\n\nReport written: ${reportPath}`
    } catch (err) {
      console.warn(`Could not write the report artifact: ${(err as Error).message}`)
      return report
    }
  }

  return `Resume completed with errors: ${executionError.message}`
}

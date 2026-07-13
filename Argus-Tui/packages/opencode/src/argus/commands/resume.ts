import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import { WorkersBridge } from "../bridge/mcp-client"
import { EngagementStore } from "../engagement/store"
import type { IEngagementStore } from "../engagement/types"
import { CredentialStore } from "../engagement/credentials"
import { ConfidenceEngine } from "../engagement/confidence"
import { ReportGenerator } from "../reporting/generator"
import { canResume, validateWorkflowVersion } from "../engagement/recovery"
import { detectTargetType, detectAuthState } from "../planner/strategy"
import { Capability } from "../planner/capabilities"
import type { PhaseRecord } from "../engagement/types"
import type { NormalizedFinding } from "../shared/types"
import type { ProgressEvent } from "../shared/progress"
import type { PlannerContext } from "../planner/types"
import { homedir } from "os"
import { join } from "path"
import { PROJECT_ROOT } from "../shared/path"

export async function resumeCommand(
  engagementId: string,
  options?: {
    workersPath?: string
    workflowsPath?: string
    useLLM?: boolean
    onProgress?: (event: ProgressEvent | string) => void
    storeOverride?: IEngagementStore
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

  // Re-create planner and plan
  const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
  const plan = await planner.plan(engagement.target, undefined, { useLLM: options?.useLLM ?? true })

  // Check for workflow version drift — if the workflow YAML changed between
  // the original run and this resume, abort to avoid applying a stale plan.
  const workflowDef = workflowRegistry.getWorkflow(plan.workflow)
  if (workflowDef && !validateWorkflowVersion(engagement, workflowDef.version)) {
    return `Engagement ${engagementId} workflow version mismatch: stored version ${engagement.workflowVersion} differs from current version ${workflowDef.version}. The workflow YAML may have changed since the original assessment.`
  }

  // Re-connect bridge
  const bridge = new WorkersBridge(options?.workersPath ?? join(PROJECT_ROOT, "argus-workers/mcp_server.py"))
  await bridge.connect()

  const confidenceEngine = new ConfidenceEngine()
  const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)
  executor.loadGates(plan.workflow)
  executor.setOnProgress((event) => { emit(event) })

  const credStore = new CredentialStore()
  credStore.load()
  credStore.clear()

  // Load existing phases and findings
  const existingPhases = store.getPhases(engagementId)
  const existingFindings = store.getFindings(engagementId)
  const completedPhaseNames = new Set(
    existingPhases.filter((p) => p.status === "COMPLETED" || p.status === "PARTIAL").map((p) => p.name),
  )

  // Find the first incomplete phase in the plan
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

      // Check if phase was already completed
      const phaseRecord = allPhaseRecords.get(phase.phaseId)!
      if (phaseRecord.status === "COMPLETED" || phaseRecord.status === "PARTIAL") {
        i++
        continue
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
          maxReplans: (() => {
            const raw = process.env.ARGUS_MAX_REPLANS
            if (!raw) return undefined  // unset → planner default
            const n = Number(raw)
            return Number.isFinite(n) && n >= 0 ? n : undefined
          })(),
          llmMaxReplans: (() => {
            const raw = process.env.ARGUS_LLM_MAX_REPLANS
            if (!raw) return undefined  // unset → planner default
            const n = Number(raw)
            return Number.isFinite(n) && n >= 0 ? n : undefined
          })(),
        }
        const replanPhases = planner.replan(replanCtx)
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
    store.updateStatus(engagementId, executionError ? "FAILED" : allPhasesCompleted ? "COMPLETED" : "PAUSED")
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
    const report = reportGen.generateMarkdown(allFindings, engagementId, engagement.target, engagement.workflow)
    return report
  }

  return `Resume completed with errors: ${executionError.message}`
}

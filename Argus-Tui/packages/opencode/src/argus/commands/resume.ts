import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import { WorkersBridge } from "../bridge/mcp-client"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { ConfidenceEngine } from "../engagement/confidence"
import { ReportGenerator } from "../reporting/generator"
import { canResume, validateWorkflowVersion } from "../engagement/recovery"
import { detectTargetType, detectAuthState } from "../planner/strategy"
import { Capability } from "../planner/capabilities"
import type { PhaseRecord } from "../engagement/types"
import type { NormalizedFinding } from "../shared/types"
import type { PlannerContext } from "../planner/types"
import { homedir } from "os"
import { join, resolve } from "path"

// Project root resolved once from __dirname to avoid brittle relative-path chains.
const projectRoot = resolve(__dirname, "../../../../../../")

export async function resumeCommand(
  engagementId: string,
  options?: {
    workersPath?: string
    workflowsPath?: string
    useLLM?: boolean
  },
): Promise<string> {
  const store = new EngagementStore()
  const engagement = store.getEngagement(engagementId)

  if (!engagement) {
    return `Engagement not found: ${engagementId}`
  }

  if (!canResume(engagement)) {
    return `Engagement ${engagementId} cannot be resumed (status: ${engagement.status})`
  }

  const workflowsDir = options?.workflowsPath ?? join(__dirname, "../workflows")
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
  const bridge = new WorkersBridge(options?.workersPath ?? join(projectRoot, "argus-workers/mcp_server.py"))
  await bridge.connect()

  const confidenceEngine = new ConfidenceEngine()
  const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)
  executor.loadGates(plan.workflow)

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

  // Build phase records for remaining phases
  const allPhaseRecords: PhaseRecord[] = plan.phases.map((p, i) => {
    const existing = existingPhases.find((ep) => ep.id === p.phaseId)
    return existing ?? {
      id: p.phaseId,
      engagementId,
      name: p.name,
      status: "PENDING" as const,
      capabilities: p.requiredCapabilities,
      executionMode: p.toolExecution ?? "sequential",
      replanCycle: p.replanCycle ?? false,
    }
  })

  // Ensure phases are saved
  store.savePhases(engagementId, allPhaseRecords)

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
      const phaseRecord = allPhaseRecords[i]
      if (phaseRecord.status === "COMPLETED" || phaseRecord.status === "PARTIAL") {
        i++
        continue
      }

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
        }
        const replanPhases = planner.replan(replanCtx)
        replanCount = replanCtx.replanCount

        if (replanPhases && replanPhases.length > 0) {
          store.appendAuditLog(engagementId, "REPLAN_INSERT",
            `Inserting ${replanPhases.length} replan phase(s) at position ${i + 1}`)

          for (const rp of replanPhases) {
            for (const cap of rp.requiredCapabilities) {
              executedCapabilities.add(cap)
            }
            plan.phases.push(rp)
            allPhaseRecords.push({
              id: rp.phaseId,
              engagementId,
              name: rp.name,
              status: "PENDING" as const,
              capabilities: rp.requiredCapabilities,
              executionMode: rp.toolExecution ?? "sequential",
              replanCycle: true,
            })
          }
          store.savePhases(engagementId, allPhaseRecords)
        }
      }

      i++
    }
  } catch (error) {
    executionError = error as Error
    store.appendAuditLog(engagementId, "RESUME_ERROR",
      `Resume error: ${(error as Error).message}`)
  } finally {
    const allPhasesCompleted = allPhaseRecords.every((p) => p.status === "COMPLETED" || p.status === "PARTIAL")
    store.updateStatus(engagementId, executionError ? "FAILED" : allPhasesCompleted ? "COMPLETED" : "PAUSED")
    store.saveFindings(engagementId, allFindings)
    store.appendAuditLog(engagementId, "RESUME_COMPLETE",
      executionError
        ? `Resume failed: ${executionError.message}`
        : `Resume completed — ${allFindings.length - existingFindings.length} new finding(s)`)
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

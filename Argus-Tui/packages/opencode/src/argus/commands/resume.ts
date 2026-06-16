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
import type { PhaseRecord } from "../engagement/types"
import type { NormalizedFinding } from "../shared/types"
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
      executionMode: "sequential",
      replanCycle: p.phaseId.startsWith("replan"),
    }
  })

  // Ensure phases are saved
  store.savePhases(engagementId, allPhaseRecords)

  // Execute remaining phases
  const allFindings: NormalizedFinding[] = [...existingFindings]
  let executionError: Error | null = null

  try {
    for (let i = startIndex; i < plan.phases.length; i++) {
      const phase = plan.phases[i]

      // Check if phase was already completed
      const phaseRecord = allPhaseRecords[i]
      if (phaseRecord.status === "COMPLETED" || phaseRecord.status === "PARTIAL") continue

      // Failed/skipped phases fall through to be retried (canRetryPhase always
      // returns true for these statuses, so the inner check was dead code)

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

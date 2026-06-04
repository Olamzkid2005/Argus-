import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import { WorkersBridge } from "../bridge/mcp-client"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { ConfidenceEngine } from "../engagement/confidence"
import { EvidenceCollector } from "../evidence/collector"
import { PlaywrightEngine } from "../browser/engine"
import { ReportGenerator } from "../reporting/generator"
import { canResume, canRetryPhase } from "../engagement/recovery"
import type { PhaseRecord } from "../engagement/types"
import type { NormalizedFinding } from "../shared/types"
import { homedir } from "os"
import { join } from "path"

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

  // Re-connect bridge
  const bridge = new WorkersBridge(options?.workersPath ?? "../argus-workers/mcp_server.py")
  await bridge.connect()

  const confidenceEngine = new ConfidenceEngine()
  const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)
  executor.loadGates(plan.workflow)

  // Wire up browser verifier deps
  const credStore = new CredentialStore()
  credStore.load()
  const allRoles = credStore.getAllCredentials()
  if (allRoles && Object.keys(allRoles).length > 0) {
    const evidenceBaseDir = join(homedir(), ".argus", "engagements")
    const evidenceCollector = new EvidenceCollector(evidenceBaseDir)
    const engine = new PlaywrightEngine()
    executor.setBrowserVerifierDeps({
      evidenceCollector,
      engine,
      credentials: allRoles as Record<string, { username: string; password: string }>,
      targetUrl: engagement.target,
    })
  }
  credStore.clear()

  // Load existing phases and findings
  const existingPhases = store.getPhases(engagementId)
  const existingFindings = store.getFindings(engagementId)
  const completedPhaseNames = new Set(
    existingPhases.filter((p) => p.status === "COMPLETED").map((p) => p.name),
  )

  // Find the first incomplete phase in the plan
  const startIndex = plan.phases.findIndex(
    (p) => !completedPhaseNames.has(p.phaseId.split("-").slice(2).join("-")),
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
      name: p.phaseId.split("-").slice(2).join("-"),
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
      if (phaseRecord.status === "COMPLETED") continue

      // If failed or skipped and not retryable, skip
      if (phaseRecord.status === "FAILED" || phaseRecord.status === "SKIPPED") {
        if (!canRetryPhase(phaseRecord.status)) continue
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

      phaseRecord.status = result.status === "failed" ? "FAILED" : "COMPLETED"
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
    const allPhasesCompleted = allPhaseRecords.every((p) => p.status === "COMPLETED")
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

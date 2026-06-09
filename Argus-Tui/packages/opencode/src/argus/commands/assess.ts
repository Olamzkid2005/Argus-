import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import type { NormalizedFinding } from "../shared/types"
import type { PhaseRecord } from "../engagement/types"
import type { ProgressEvent } from "../shared/progress"
import { WorkersBridge } from "../bridge/mcp-client"
import type { CacheMode } from "../bridge/types"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { ConfidenceEngine } from "../engagement/confidence"
import { ReportGenerator } from "../reporting/generator"
import { FeatureFlags, Feature } from "../config/feature-flags"
import { join } from "path"

export async function assessCommand(target: string, options?: {
  workersPath?: string
  workflowsPath?: string
  toolsPath?: string
  useLLM?: boolean
  credsPath?: string
  cacheMode?: CacheMode
  features?: Partial<Record<Feature, boolean>>
  onProgress?: (event: ProgressEvent | string) => void
}): Promise<void> {
  const workflowsDir = options?.workflowsPath ?? join(__dirname, "../workflows")
  const toolsPath = options?.toolsPath ?? join(workflowsDir, "tool-definitions.yaml")

  const workflowRegistry = new WorkflowRegistry(workflowsDir)
  workflowRegistry.loadAll()

  const toolRegistry = new ToolRegistry()
  toolRegistry.load(toolsPath)

  const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)

  const defaultWorkersPath = join(__dirname, "../../../../../../argus-workers/mcp_server.py")
  const bridge = new WorkersBridge(options?.workersPath ?? defaultWorkersPath)
  await bridge.connect()

  const confidenceEngine = new ConfidenceEngine()
  const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)

  // Task 4.1: Initialize feature flags (all opt-in by default)
  const featureFlags = new FeatureFlags(options?.features)

  // Task A: Load project config (./argus.config.yaml) — lowest priority, overridden by env/CLI
  try {
    const { readFileSync } = await import("fs")
    const { parse: YAML } = await import("yaml")
    const configPath = join(process.cwd(), "argus.config.yaml")
    const raw = readFileSync(configPath, "utf-8")
    const parsed = YAML(raw) as { features?: Record<string, boolean> } | undefined
    if (parsed?.features) {
      featureFlags.loadFromConfig(parsed.features)
    }
  } catch { /* config file missing or invalid — use defaults */ }

  featureFlags.loadFromEnv()
  executor.setFeatureFlags(featureFlags)

  const store = new EngagementStore()
  const engagement = store.createEngagement(target, "assessment")

  store.updateStatus(engagement.id, "RUNNING")

  const credStore = new CredentialStore()
  const creds = options?.credsPath ? credStore.load(options.credsPath) : credStore.load()
  const defaultCreds = credStore.getDefaultCredentials()
  if (defaultCreds) {
    store.appendAuditLog(engagement.id, "CREDS_LOADED", `Loaded credentials for roles: ${credStore.listRoles().join(", ")}`)
  }
  credStore.clear()

  // Apply cache mode to executor
  if (options?.cacheMode) {
    executor.setExecutionOptions({ cacheMode: options.cacheMode })
  }

  const plan = await planner.plan(target, undefined, { useLLM: options?.useLLM })
  executor.loadGates(plan.workflow)
  for (const phase of plan.phases) {
    if (defaultCreds) phase.config.credentials = defaultCreds
  }

  const phaseRecords: PhaseRecord[] = plan.phases.map((p, i) => ({
    id: p.phaseId,
    engagementId: engagement.id,
    name: p.phaseId.split("-")[2] ?? p.phaseId,
    status: "PENDING" as const,
    capabilities: p.requiredCapabilities,
    executionMode: "sequential",
    replanCycle: p.phaseId.startsWith("replan"),
  }))

  store.savePhases(engagement.id, phaseRecords)
  store.appendAuditLog(engagement.id, "ASSESS_START", `Assessment started against ${target} with workflow ${plan.workflow}`)

  const allFindings: NormalizedFinding[] = []
  let executionError: Error | null = null
  const emit = options?.onProgress ?? ((_: ProgressEvent | string) => {})

  try {
    for (let i = 0; i < plan.phases.length; i++) {
      const phase = plan.phases[i]
      const phaseName = phase.phaseId.split("-")[2] ?? phase.phaseId

      emit({ type: "phase_start", phaseId: phase.phaseId, name: phaseName, total: plan.phases.length })

      phaseRecords[i].status = "RUNNING"
      phaseRecords[i].startedAt = new Date().toISOString()
      store.savePhase(engagement.id, phaseRecords[i])

      const result = await executor.execute(phase)

      for (const finding of result.findings) {
        emit({ type: "finding", phaseId: phase.phaseId, severity: String(finding.severity), title: finding.title })
        const promoted = confidenceEngine.promote(finding)
        finding.confidence = promoted
        allFindings.push(finding)
      }

      const phaseStatus = result.status === "failed" ? "FAILED" : "COMPLETED"
      phaseRecords[i].status = phaseStatus
      phaseRecords[i].completedAt = new Date().toISOString()
      if (result.errors.length > 0) phaseRecords[i].error = result.errors.join("; ")
      store.savePhase(engagement.id, phaseRecords[i])

      if (phaseStatus === "FAILED") {
        emit({ type: "phase_error", phaseId: phase.phaseId, name: phaseName, error: result.errors.join("; ") })
      } else {
        emit({ type: "phase_complete", phaseId: phase.phaseId, name: phaseName, findings: result.findings.length, status: phaseStatus })
      }
    }
  } catch (error) {
    executionError = error as Error
    store.appendAuditLog(engagement.id, "ASSESS_ERROR", `Assessment error: ${(error as Error).message}`)
  } finally {
    emit({ type: "scan_complete", totalFindings: allFindings.length })
    const allPhasesCompleted = phaseRecords.every(p => p.status === "COMPLETED")
    store.updateStatus(engagement.id, executionError ? "FAILED" : allPhasesCompleted ? "COMPLETED" : "FAILED")
    store.saveFindings(engagement.id, allFindings)
    store.appendAuditLog(engagement.id, "ASSESS_COMPLETE",
      executionError
        ? `Assessment failed: ${executionError.message}`
        : `Assessment completed — ${allFindings.length} finding(s)`
    )
    await bridge.disconnect()
  }

  if (!executionError) {
    const reportGen = new ReportGenerator()
    const report = reportGen.generateMarkdown(allFindings, engagement.id, target, "assessment")
    process.stdout.write(report + "\n")
  }
}

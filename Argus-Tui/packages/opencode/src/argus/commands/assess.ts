import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import type { NormalizedFinding } from "../planner/types"
import type { PhaseRecord } from "../engagement/types"
import { WorkersBridge } from "../bridge/mcp-client"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { ConfidenceEngine } from "../engagement/confidence"
import { ReportGenerator } from "../reporting/generator"
import { join } from "path"

export async function assessCommand(target: string, options?: {
  workersPath?: string
  workflowsPath?: string
  toolsPath?: string
  useLLM?: boolean
  credsPath?: string
}): Promise<void> {
  const workflowsDir = options?.workflowsPath ?? join(__dirname, "../workflows")
  const toolsPath = options?.toolsPath ?? join(workflowsDir, "tool-definitions.yaml")

  const workflowRegistry = new WorkflowRegistry(workflowsDir)
  workflowRegistry.loadAll()

  const toolRegistry = new ToolRegistry()
  toolRegistry.load(toolsPath)

  const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)

  const bridge = new WorkersBridge(options?.workersPath ?? "../argus-workers/mcp_server.py")
  await bridge.connect()

  const confidenceEngine = new ConfidenceEngine()
  const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)

  const store = new EngagementStore()
  const engagement = store.createEngagement(target, "assessment")

  store.updateStatus(engagement.id, "RUNNING")

  const credStore = new CredentialStore()
  const creds = options?.credsPath ? credStore.load(options.credsPath) : credStore.load()
  const defaultCreds = credStore.getDefaultCredentials()
  if (defaultCreds) {
    store.appendAuditLog(engagement.id, "CREDS_LOADED", `Loaded credentials for roles: ${credStore.listRoles().join(", ")}`)
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

  for (let i = 0; i < plan.phases.length; i++) {
    const phase = plan.phases[i]
    phaseRecords[i].status = "RUNNING"
    phaseRecords[i].startedAt = new Date().toISOString()
    store.savePhase(engagement.id, phaseRecords[i])

    const result = await executor.execute(phase)

    for (const finding of result.findings) {
      const promoted = confidenceEngine.promote(finding)
      finding.confidence = promoted
      allFindings.push(finding)
    }

    phaseRecords[i].status = result.status === "failed" ? "FAILED" : "COMPLETED"
    phaseRecords[i].completedAt = new Date().toISOString()
    if (result.errors.length > 0) phaseRecords[i].error = result.errors.join("; ")
    store.savePhase(engagement.id, phaseRecords[i])
  }

  store.saveFindings(engagement.id, allFindings)
  store.appendAuditLog(engagement.id, "ASSESS_COMPLETE", `Assessment completed — ${allFindings.length} finding(s)`)
  store.updateStatus(engagement.id, allFindings.length > 0 ? "COMPLETED" : "FAILED")

  const reportGen = new ReportGenerator()
  const report = reportGen.generateMarkdown(allFindings, engagement.id, target, "assessment")
  process.stdout.write(report + "\n")

  await bridge.disconnect()
}

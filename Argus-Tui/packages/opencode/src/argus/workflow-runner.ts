/**
 * ArgusWorkflowRunner — Runs assessment workflows through the planner/executor.
 *
 * This is the single entry point for all assessment executions, whether
 * triggered by /assess, natural language detection, CLI, or API.
 *
 * Engagement creation happens here, not in the caller.
 */

import { WorkflowRegistry } from "./workflows/registry"
import { ToolRegistry } from "./workflows/tool-registry"
import { WorkflowPlanner } from "./planner/planner"
import { InProcessExecutor } from "./planner/executor"
import { WorkersBridge } from "./bridge/mcp-client"
import { EngagementStore } from "./engagement/store"
import { CredentialStore } from "./engagement/credentials"
import { ConfidenceEngine } from "./engagement/confidence"
import { EvidenceCollector } from "./evidence/collector"
import { ReportGenerator } from "./reporting/generator"
import { PlaywrightEngine } from "./browser/engine"
import { join } from "path"
import { homedir } from "os"

export interface WorkflowRunOptions {
  target: string
  useLLM?: boolean
  workersPath?: string
  workflowsDir?: string
  credsPath?: string
}

export interface WorkflowRunResult {
  engagementId: string
  findings: number
  critical: number
  high: number
  medium: number
  low: number
  durationMs: number
}

export class WorkflowRunner {
  /**
   * Run an assessment workflow against a target.
   * Creates an engagement, plans phases, executes them, and returns results.
   */
  async run(options: WorkflowRunOptions): Promise<WorkflowRunResult> {
    const startTime = Date.now()
    const target = options.target

    // Resolve paths relative to this file (src/argus/)
    const __dirname = typeof __dirname !== "undefined"
      ? __dirname
      : new URL(".", import.meta.url).pathname

    const workersPath = options.workersPath ?? join(__dirname, "../../../../../../argus-workers/mcp_server.py")
    const workflowsDir = options.workflowsDir ?? join(__dirname, "./workflows")
    const toolsPath = join(workflowsDir, "tool-definitions.yaml")

    // ── 1. Create engagement ──
    const store = new EngagementStore()
    const engagement = store.createEngagement(target, "assessment")
    const engagementId = engagement.id
    store.updateStatus(engagementId, "RUNNING")

    // ── 2. Load registries ──
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()

    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)

    // ── 3. Plan ──
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan(target, undefined, { useLLM: options.useLLM ?? true })

    // ── 4. Create phase records ──
    const phaseRecords = plan.phases.map((p, i) => ({
      id: p.phaseId,
      engagementId,
      name: p.phaseId.split("-")[2] ?? p.phaseId,
      status: "PENDING" as const,
      capabilities: p.requiredCapabilities,
      executionMode: "sequential" as const,
      replanCycle: p.phaseId.startsWith("replan"),
    }))
    store.savePhases(engagementId, phaseRecords)

    // ── 5. Connect bridge ──
    const bridge = new WorkersBridge(workersPath)
    await bridge.connect()

    const confidenceEngine = new ConfidenceEngine()
    const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)
    executor.loadGates(plan.workflow)

    // ── 6. Wire up browser verifier deps ──
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
        targetUrl: target,
      })
    }
    credStore.clear()

    // ── 7. Execute phases ──
    const allFindings: any[] = []
    let executionError: Error | null = null

    try {
      for (let i = 0; i < plan.phases.length; i++) {
        const phase = plan.phases[i]
        phaseRecords[i].status = "RUNNING"
        phaseRecords[i].startedAt = new Date().toISOString()
        store.savePhase(engagementId, phaseRecords[i])

        const result = await executor.execute(phase)

        for (const finding of result.findings) {
          const promoted = confidenceEngine.promote(finding)
          allFindings.push({ ...finding, confidence: promoted })
        }

        phaseRecords[i].status = result.status === "failed" ? "FAILED" : "COMPLETED"
        phaseRecords[i].completedAt = new Date().toISOString()
        if (result.errors.length > 0) phaseRecords[i].error = result.errors.join("; ")
        store.savePhase(engagementId, phaseRecords[i])
      }
    } catch (error) {
      executionError = error as Error
      store.appendAuditLog(engagementId, "RUNNER_ERROR",
        `Workflow error: ${(error as Error).message}`)
    } finally {
      const allCompleted = phaseRecords.every((p) => p.status === "COMPLETED")
      store.updateStatus(engagementId, executionError ? "FAILED" : allCompleted ? "COMPLETED" : "PARTIAL")
      store.saveFindings(engagementId, allFindings)
      await bridge.disconnect()
    }

    // ── 8. Return results ──
    const critical = allFindings.filter((f) => f.severity >= 4).length
    const high = allFindings.filter((f) => f.severity === 3).length
    const medium = allFindings.filter((f) => f.severity === 2).length
    const low = allFindings.filter((f) => f.severity <= 1).length

    return {
      engagementId,
      findings: allFindings.length,
      critical,
      high,
      medium,
      low,
      durationMs: Date.now() - startTime,
    }
  }
}

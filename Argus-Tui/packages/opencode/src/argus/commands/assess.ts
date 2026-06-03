import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkflowPlanner } from "../planner/planner"
import { InProcessExecutor } from "../planner/executor"
import type { NormalizedFinding } from "../planner/types"
import { WorkersBridge } from "../bridge/mcp-client"
import { EngagementStore } from "../engagement/store"
import { ConfidenceEngine } from "../engagement/confidence"
import { ReportGenerator } from "../reporting/generator"
import { join } from "path"

export async function assessCommand(target: string, options?: {
  workersPath?: string
  workflowsPath?: string
  toolsPath?: string
  useLLM?: boolean
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
  const executor = new InProcessExecutor(toolRegistry, bridge, confidenceEngine)

  const store = new EngagementStore()
  const engagement = store.createEngagement(target, "assessment")

  store.updateStatus(engagement.id, "RUNNING")

  const plan = await planner.plan(target, undefined, { useLLM: options?.useLLM })

  const allFindings: NormalizedFinding[] = []

  for (const phase of plan.phases) {
    const result = await executor.execute(phase)

    for (const finding of result.findings) {
      const promoted = confidenceEngine.promote(finding)
      finding.confidence = promoted
      allFindings.push(finding)
    }
  }

  store.saveFindings(engagement.id, allFindings)
  store.updateStatus(engagement.id, "COMPLETED")

  const reportGen = new ReportGenerator()
  const report = reportGen.generateMarkdown(allFindings, engagement.id, target, "assessment")
  process.stdout.write(report + "\n")

  await bridge.disconnect()
}

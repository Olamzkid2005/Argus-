import { PhaseExecutionRequest, PhaseExecutionResult, NormalizedFinding } from "./types"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkersBridge } from "../bridge/mcp-client"
import { ConfidenceEngine } from "../engagement/confidence"

export interface PhaseExecutor {
  execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult>
}

export class InProcessExecutor implements PhaseExecutor {
  constructor(
    private toolRegistry: ToolRegistry,
    private bridge: WorkersBridge,
    private confidenceEngine: ConfidenceEngine,
  ) {}

  async execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult> {
    const startTime = Date.now()
    const findings: NormalizedFinding[] = []
    const errors: string[] = []

    for (const cap of phase.requiredCapabilities) {
      const tools = this.toolRegistry.getToolsByCapability(cap)
      if (tools.length === 0) {
        errors.push(`No tools available for capability: ${cap}`)
        continue
      }

      for (const tool of tools) {
        try {
          const result = await this.bridge.callTool(tool.name, {
            target: phase.target,
            capability: cap,
            config: phase.config,
          })

          if (result.success && result.data) {
            const normalized = result.data as NormalizedFinding[]
            for (const finding of normalized) {
              const promoted = this.confidenceEngine.promote(finding)
              finding.confidence = promoted
              findings.push(finding)
            }
          }
        } catch (error) {
          errors.push(`Tool ${tool.name} failed: ${(error as Error).message}`)
        }
      }
    }

    return {
      phaseId: phase.phaseId,
      status: errors.length > 0 && findings.length === 0 ? "failed" : findings.length > 0 ? "completed" : "partial",
      findings,
      artifacts: [],
      errors,
      durationMs: Date.now() - startTime,
    }
  }
}

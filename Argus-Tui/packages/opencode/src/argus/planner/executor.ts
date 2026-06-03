import type { PhaseExecutionRequest, PhaseExecutionResult, NormalizedFinding } from "./types"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkersBridge } from "../bridge/mcp-client"
import { ConfidenceEngine } from "../engagement/confidence"
import { ApprovalService } from "../workflows/approval"
import type { ApprovalGate } from "../workflows/types"
import { WorkflowRegistry } from "../workflows/registry"

export interface PhaseExecutor {
  execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult>
}

export class InProcessExecutor implements PhaseExecutor {
  private approvalService: ApprovalService
  private requiredGates: ApprovalGate[] = []

  constructor(
    private toolRegistry: ToolRegistry,
    private bridge: WorkersBridge,
    private confidenceEngine: ConfidenceEngine,
    private workflowRegistry?: WorkflowRegistry,
  ) {
    this.approvalService = new ApprovalService()
  }

  loadGates(workflowName: string): void {
    const workflow = this.workflowRegistry?.getWorkflow(workflowName)
    this.requiredGates = this.approvalService.getRequiredGates(workflow?.approval_required)
  }

  async execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult> {
    const gate = this.approvalService.needsApproval(phase, this.requiredGates)
    if (gate) {
      const result = await this.approvalService.requestApproval(gate, phase.phaseId, phase.target)
      if (!result.approved) {
        return {
          phaseId: phase.phaseId,
          status: "skipped",
          findings: [],
          artifacts: [],
          errors: [result.reason ?? "Skipped by user"],
          durationMs: 0,
        }
      }
    }

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

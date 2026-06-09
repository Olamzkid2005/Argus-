import type { PhaseExecutionRequest, PhaseExecutionResult, NormalizedFinding, ErrorRecovery } from "./types"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkersBridge } from "../bridge/mcp-client"
import type { SignalQuality, CacheMode } from "../bridge/types"
import { Confidence } from "../shared/types"
import { ConfidenceEngine } from "../engagement/confidence"
import { ApprovalService } from "../workflows/approval"
import type { ApprovalGate } from "../workflows/types"
import { WorkflowRegistry } from "../workflows/registry"
import { Feature, type FeatureFlags } from "../config/feature-flags"
import { ToolConfig } from "../config/tool-config"
import { ToolHealthMonitor } from "../bridge/tool-health"
import type { ToolHealthRecord } from "../bridge/tool-health"

export interface ExecutionOptions {
  cacheMode?: CacheMode
}

/**
 * Map a tool's signal_quality tier to a baseline confidence level.
 * This gives the ConfidenceEngine a smarter starting point than always INFORMATIONAL.
 *
 *   CONFIRMED  → HIGH    (e.g. sqlmap, browser verifier, nuclei CVE templates)
 *   PROBABLE   → MEDIUM  (e.g. dalfox, semgrep, gitleaks)
 *   CANDIDATE  → LOW     (e.g. ffuf, nikto, passive recon)
 *   undefined  → INFORMATIONAL (legacy — no signal_quality metadata)
 */
function baselineConfidence(signalQuality: SignalQuality | undefined): number {
  switch (signalQuality) {
    case "CONFIRMED": return Confidence.HIGH
    case "PROBABLE":  return Confidence.MEDIUM
    case "CANDIDATE": return Confidence.LOW
    default:          return Confidence.INFORMATIONAL
  }
}

export interface PhaseExecutor {
  execute(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult>
}

const RECOVERY_LABELS: Record<ErrorRecovery, string> = {
  retry_once_then_skip: "retry once then skip",
  skip_and_continue: "skip and continue",
  fail_fast: "fail fast",
}

export class InProcessExecutor implements PhaseExecutor {
  private approvalService: ApprovalService
  private requiredGates: ApprovalGate[] = []
  private featureFlags: FeatureFlags | null = null
  private toolConfig: ToolConfig = new ToolConfig()
  private phaseCount = 0
  private toolHealth: ToolHealthMonitor

  private executionOptions: ExecutionOptions = {}

  constructor(
    private toolRegistry: ToolRegistry,
    private bridge: WorkersBridge,
    private confidenceEngine: ConfidenceEngine,
    private workflowRegistry?: WorkflowRegistry,
  ) {
    this.approvalService = new ApprovalService()
    this.toolHealth = new ToolHealthMonitor()
  }

  setExecutionOptions(options: ExecutionOptions): void {
    this.executionOptions = options
  }

  getToolHealth(): ToolHealthRecord[] {
    return this.toolHealth.getStatus()
  }

  setFeatureFlags(flags: FeatureFlags): void {
    this.featureFlags = flags
  }

  setToolConfig(tc: ToolConfig): void {
    this.toolConfig = tc
    const cb = tc.getCircuitBreakerConfig()
    this.toolHealth = new ToolHealthMonitor({
      maxConsecutiveFailures: cb.maxFailures,
      cooldownMs: cb.cooldownMs,
    })
  }

  /** Check whether a feature is enabled (defaults true if no flag system attached) */
  private isFeatureEnabled(feature: Feature): boolean {
    return this.featureFlags?.isEnabled(feature) ?? true
  }

  private gatesLoaded = false

  loadGates(workflowName: string): void {
    const workflow = this.workflowRegistry?.getWorkflow(workflowName)
    this.requiredGates = this.approvalService.getRequiredGates(workflow?.approval_required)
    this.gatesLoaded = true
  }

  async execute(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult> {
    const execOptions = { ...this.executionOptions, ...options }
    if (phase.execution === "llm_driven") {
      return this.executeHybrid(phase, execOptions)
    }

    if (!this.gatesLoaded) {
      throw new Error("loadGates must be called before execute")
    }

    this.phaseCount++

    // Periodic MCP drift check: every 5 phases, run a lightweight capability
    // hash comparison. On mismatch, run the full detectDrift() and log.
    if (this.phaseCount % 5 === 0) {
      try {
        const inSync = await this.bridge.quickDriftCheck()
        if (!inSync) {
          const drift = await this.bridge.detectDrift()
          if (drift.missing_from_mcp.length > 0 || drift.missing_from_registry.length > 0 || drift.capability_gaps.length > 0) {
            console.warn(`[executor] MCP drift detected at phase ${phase.phaseId}:`, JSON.stringify(drift))
          }
        }
      } catch {
        // Drift check is advisory — never fail a phase for it
      }
    }

    const gate = this.isFeatureEnabled(Feature.APPROVAL_GATES)
      ? this.approvalService.needsApproval(phase, this.requiredGates)
      : null
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
    const calledTools = new Set<string>()

    for (const cap of phase.requiredCapabilities) {
      const tools = this.toolRegistry.getToolsByCapability(cap)
      if (tools.length === 0) {
        errors.push(`No tools available for capability: ${cap}`)
        continue
      }

      for (const tool of tools) {
        if (calledTools.has(tool.name)) continue
        calledTools.add(tool.name)

        if (!this.toolHealth.isHealthy(tool.name)) {
          const alternatives = this.toolRegistry
            .getToolsByCapability(cap)
            .filter(t => t.name !== tool.name)
            .map(t => t.name)
          errors.push(`Tool ${tool.name} is temporarily unavailable (circuit breaker). Available alternatives: ${alternatives.join(", ") || "none"}`)
          continue
        }

        const errorRecovery = this.resolveErrorRecovery(phase, tool.name)
        let lastError: Error | null = null
        let success = false

        for (let attempt = 1; attempt <= 2; attempt++) {
          const attemptStartTime = Date.now()
          try {
            const result = await this.bridge.callTool(tool.name, {
              target: phase.target,
              capability: cap,
              config: phase.config,
            }, undefined, execOptions.cacheMode)

            if (result.success && result.data) {
              const data = result.data
              const baseConfidence = baselineConfidence(result.signalQuality)
              if (Array.isArray(data)) {
                // Structured findings from tool (expected format)
                // Apply signal_quality as a baseline floor for each finding
                for (const finding of data) {
                  finding.confidence = Math.max(finding.confidence ?? 0, baseConfidence)
                  const promoted = this.confidenceEngine.promote(finding)
                  findings.push({ ...finding, confidence: promoted })
                }
                this.toolHealth.recordSuccess(tool.name, Date.now() - attemptStartTime)
                success = true
                break
              } else if (typeof data === "string" && data.length > 0) {
                // Raw text output — create a basic finding from the tool output
                const truncated = data.length > 500 ? data.substring(0, 500) + "..." : data
                const finding: NormalizedFinding = {
                  id: `find-${tool.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                  title: `${tool.name} scan against ${phase.target}`,
                  severity: 2,
                  confidence: baseConfidence,
                  status: "PENDING",
                  description: truncated,
                  tool: tool.name,
                  phase: phase.phaseId,
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                }
                const promoted = this.confidenceEngine.promote(finding)
                findings.push({ ...finding, confidence: promoted })
                this.toolHealth.recordSuccess(tool.name, Date.now() - attemptStartTime)
                success = true
                break
              }
            }

            lastError = new Error(result.error ?? "Tool returned unsuccessful result")
            this.toolHealth.recordFailure(tool.name, lastError.message)
            if (errorRecovery === "fail_fast") {
              errors.push(`Tool ${tool.name} failed (fail_fast): ${lastError.message}`)
              return {
                phaseId: phase.phaseId,
                status: "failed",
                findings,
                artifacts: [],
                errors,
                durationMs: Date.now() - startTime,
              }
            }

            if (errorRecovery === "retry_once_then_skip" && attempt === 1) {
              continue
            }

            break
          } catch (error) {
            lastError = error as Error
            this.toolHealth.recordFailure(tool.name, lastError.message)
            if (errorRecovery === "fail_fast") {
              errors.push(`Tool ${tool.name} failed (fail_fast): ${lastError.message}`)
              return {
                phaseId: phase.phaseId,
                status: "failed",
                findings,
                artifacts: [],
                errors,
                durationMs: Date.now() - startTime,
              }
            }

            if (errorRecovery === "retry_once_then_skip" && attempt === 1) {
              continue
            }

            break
          }
        }

        if (!success && lastError) {
          errors.push(`Tool ${tool.name} failed after ${errorRecovery === "retry_once_then_skip" ? "1 retry" : "no retry"} (${RECOVERY_LABELS[errorRecovery]}): ${lastError.message}`)
        }
      }
    }

    return {
      phaseId: phase.phaseId,
      status: errors.length > 0 && findings.length > 0 ? "partial" : errors.length > 0 && findings.length === 0 ? "failed" : findings.length > 0 ? "completed" : "partial",
      findings,
      artifacts: [],
      errors,
      durationMs: Date.now() - startTime,
    }
  }

  async executeHybrid(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult> {
    const execOptions = { ...this.executionOptions, ...options }
    const startTime = Date.now()
    const findings: NormalizedFinding[] = []
    const errors: string[] = []

    // 1. Resolve pipeline from tool registry
    const pipeline = phase.requiredCapabilities.flatMap(cap => {
      const tools = this.toolRegistry.getToolsByCapability(cap)
      return tools.map(t => ({ tool: t.name, capabilities: [cap] }))
    })

    // 2. LLM creates plan (or deterministic default for now)
    const session = await this.bridge.agentInit({
      target: phase.target,
      phase: phase.phaseId,
      techStack: phase.config?.techStack as string[] | undefined,
      pipeline,
      context: { previousFindings: phase.previousPhaseResults },
    })

    let done = false

    while (!done) {
      // 3. Get next tool from plan
      const next = await this.bridge.agentNext({ session_id: session.session_id })
      if (next.done || !next.tool) {
        done = true
        break
      }

      // 4. Check tool health before executing
      if (!this.toolHealth.isHealthy(next.tool)) {
        const status = this.toolHealth.getToolStatus(next.tool)
        const retryAfter = status?.circuitOpenedAt
          ? Math.ceil((300_000 - (Date.now() - status.circuitOpenedAt)) / 1000)
          : 300
        errors.push(`Tool ${next.tool} is circuit-broken (retry in ${retryAfter}s)`)
        await this.bridge.agentObserve({
          session_id: session.session_id,
          tool: next.tool,
          success: false,
          summary: `Circuit breaker open for ${next.tool}`,
        })
        continue
      }

      // 5. Execute tool
      const toolStartTime = Date.now()
      try {
        const cap = pipeline.find(p => p.tool === next.tool)?.capabilities?.[0] ?? "web_recon"
        const result = await this.bridge.callTool(next.tool, {
          target: phase.target,
          capability: cap,
          config: phase.config,
        }, undefined, execOptions.cacheMode)
        const durationMs = Date.now() - toolStartTime

        if (result.success) {
          this.toolHealth.recordSuccess(next.tool, durationMs)

          // Parse findings from structured data
          if (result.data) {
            const data = result.data as any
            if (Array.isArray(data)) {
              for (const finding of data) {
                const promoted = this.confidenceEngine.promote(finding)
                findings.push({ ...finding, confidence: promoted })
              }
            } else if (typeof data === "string" && data.length > 0) {
              const baseConfidence = baselineConfidence(result.signalQuality)
              findings.push({
                id: `find-${next.tool}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                title: `${next.tool} scan against ${phase.target}`,
                severity: 2,
                confidence: baseConfidence,
                status: "PENDING",
                description: data.slice(0, 500),
                tool: next.tool,
                phase: phase.phaseId,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              })
            }
          }

          await this.bridge.agentObserve({
            session_id: session.session_id,
            tool: next.tool,
            success: true,
            durationMs,
            findingCount: findings.length,
            summary: `${next.tool}: ${findings.length} findings`,
          })
        } else {
          this.toolHealth.recordFailure(next.tool, result.error ?? "Unknown error")
          errors.push(`Tool ${next.tool} failed: ${result.error}`)

          await this.bridge.agentObserve({
            session_id: session.session_id,
            tool: next.tool,
            success: false,
            durationMs,
            summary: `${next.tool} failed: ${result.error}`,
          })
        }
      } catch (error) {
        const errorMsg = (error as Error).message
        this.toolHealth.recordFailure(next.tool, errorMsg)
        errors.push(`Tool ${next.tool} error: ${errorMsg}`)

        await this.bridge.agentObserve({
          session_id: session.session_id,
          tool: next.tool,
          success: false,
          summary: errorMsg,
        })
      }
    }

    return {
      phaseId: phase.phaseId,
      status: errors.length > 0 && findings.length === 0 ? "failed" : "completed",
      findings,
      artifacts: [],
      errors,
      durationMs: Date.now() - startTime,
    }
  }

  private resolveErrorRecovery(phase: PhaseExecutionRequest, toolName: string): ErrorRecovery {
    const tool = this.toolRegistry.getTool(toolName)
    if (tool?.destructive) return "fail_fast"
    if (tool?.requires_auth) return "skip_and_continue"
    return "retry_once_then_skip"
  }
}

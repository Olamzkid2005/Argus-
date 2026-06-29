import type { PhaseExecutionRequest, PhaseExecutionResult, NormalizedFinding, ErrorRecovery } from "./types"
import type { PipelineStep } from "./pipeline"
import { ToolRegistry } from "../workflows/tool-registry"
import type { SignalQuality, CacheMode } from "../bridge/types"
import { LLMUnavailableError } from "../bridge/types"
import type { WorkersBridge } from "../bridge/mcp-client"
import type { ProgressEvent, ErrorHintData } from "../shared/progress"
import type { ToolDef } from "../workflows/tool-registry"
import crypto from "crypto"
import { Capability } from "../shared/capabilities"

/**
 * Maximum parallelism for phases marked with `execution: parallel`.
 * Limits concurrent subprocess/network tool execution to avoid resource starvation.
 */
const MAX_PARALLEL_TOOLS = 4
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
  /**
   * Enable verbose execution logging.
   * When true, the executor emits additional detail about tool selection,
   * timing, and circuit-breaker status via console.log.
   */
  verbose?: boolean
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

export interface ScopeConfig {
  mode: "allowlist" | "allow_all"
  allowed_targets?: string[]
  blocked_targets?: string[]
}

export class InProcessExecutor implements PhaseExecutor {
  private approvalService: ApprovalService
  private requiredGates: ApprovalGate[] = []
  private featureFlags: FeatureFlags | null = null
  private toolConfig: ToolConfig = new ToolConfig()
  private phaseCount = 0
  private toolHealth: ToolHealthMonitor
  private scopeConfig: ScopeConfig | null = null
  private tempCredFiles: string[] = []

  setScopeConfig(config: ScopeConfig): void {
    this.scopeConfig = config
  }

  private executionOptions: ExecutionOptions = {}
  private emitProgress: ((event: ProgressEvent) => void) | null = null

  constructor(
    private toolRegistry: ToolRegistry,
    private bridge: WorkersBridge,
    private confidenceEngine: ConfidenceEngine,
    private workflowRegistry?: WorkflowRegistry,
  ) {
    this.approvalService = new ApprovalService()
    this.toolHealth = new ToolHealthMonitor()
    this.toolHealth.onErrorHint = (hint: ErrorHintData) => {
      this.emitProgress?.({ type: "error_hint", ...hint })
    }
  }

  setOnProgress(handler: (event: ProgressEvent) => void): void {
    this.emitProgress = handler
  }

  setExecutionOptions(options: ExecutionOptions): void {
    this.executionOptions = options
    if (options.verbose) {
      console.log("[executor] Verbose mode enabled")
    }
  }

  reset(): void {
    this.emitProgress = null
    this.executionOptions = {}
    this.cleanupCreds()
  }

  getToolHealth(): ToolHealthRecord[] {
    const status = this.toolHealth.getStatus()
    if (this.executionOptions.verbose && status.length > 0) {
      console.log("[executor] Tool health:", JSON.stringify(status.map(s => ({ tool: s.toolName, healthy: !s.circuitOpen }))))
    }
    return status
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
    // Re-attach the onErrorHint callback — the constructor set it on the old
    // ToolHealthMonitor instance, which was just replaced above. Without this
    // reassignment, error hints from tool health failures are silently dropped.
    this.toolHealth.onErrorHint = (hint: ErrorHintData) => {
      this.emitProgress?.({ type: "error_hint", ...hint })
    }
  }

  /** Check whether a feature is enabled (defaults false if no flag system attached) */
  private isFeatureEnabled(feature: Feature): boolean {
    return this.featureFlags?.isEnabled(feature) ?? false
  }

  private gatesLoaded = false

  loadGates(workflowName: string): void {
    const workflow = this.workflowRegistry?.getWorkflow(workflowName)
    this.requiredGates = this.approvalService.getRequiredGates(workflow?.approval_required)
    this.gatesLoaded = true
  }

  async execute(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult> {
    const execOptions = { ...this.executionOptions, ...options }
    if (!this.gatesLoaded) {
      throw new Error("loadGates must be called before execute")
    }

    // Approval gate check runs BEFORE phase dispatch (including hybrid)
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

    if (phase.toolExecution === "llm_driven") {
      if (execOptions.verbose) console.log(`[executor] Phase ${phase.phaseId}: hybrid (LLM-driven) execution`)
      return this.executeHybrid(phase, execOptions)
    }

    this.phaseCount++
    if (execOptions.verbose) {
      console.log(`[executor] Phase ${this.phaseCount}: ${phase.name} (${phase.toolExecution}) — ${phase.requiredCapabilities.length} capability(ies)`)
    }

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

    const startTime = Date.now()
    const findings: NormalizedFinding[] = []
    const errors: string[] = []
    const calledTools = new Set<string>()

    const toolConfigs: { tool: ToolDef; cap: Capability }[] = []
    const pipelineSteps = phase.config.pipelineSteps as PipelineStep[] | undefined
    if (pipelineSteps && pipelineSteps.length > 0) {
      // Use pre-computed pipeline steps from planner (gates already applied via selectBest)
      for (const step of pipelineSteps) {
        if (calledTools.has(step.tool)) continue
        calledTools.add(step.tool)
        const tool = this.toolRegistry.getTool(step.tool)
        if (!tool) {
          errors.push(`Tool ${step.tool} not found in registry`)
          continue
        }
        const cap = (step.capabilities?.[0] ?? phase.requiredCapabilities[0]) as Capability
        toolConfigs.push({ tool, cap })
        if (execOptions.verbose) console.log(`[executor]  Tool: ${step.tool} (capability: ${cap})`)
      }
    } else {
      // Fallback: select tools by capability (legacy path)
      for (const cap of phase.requiredCapabilities) {
        const tools = this.toolRegistry.getToolsByCapability(cap)
        if (tools.length === 0) {
          errors.push(`No tools available for capability: ${cap}`)
          continue
        }
        for (const tool of tools) {
          if (calledTools.has(tool.name)) continue
          calledTools.add(tool.name)
          toolConfigs.push({ tool, cap })
          if (execOptions.verbose) console.log(`[executor]  Tool: ${tool.name} (capability: ${cap})`)
        }
      }
    }

    if (execOptions.verbose) console.log(`[executor]  ${toolConfigs.length} tool(s) configured for this phase`)

    // Execute tools: parallel for `parallel` phases, sequential for `sequential` phases
    if (phase.toolExecution === "parallel") {
      if (execOptions.verbose) console.log(`[executor]  Executing ${toolConfigs.length} tool(s) in parallel (batch size: ${MAX_PARALLEL_TOOLS})`)
      // Run tools in batches of MAX_PARALLEL_TOOLS to avoid resource starvation
      for (let i = 0; i < toolConfigs.length; i += MAX_PARALLEL_TOOLS) {
        const batch = toolConfigs.slice(i, i + MAX_PARALLEL_TOOLS)
        const results = await Promise.all(
          batch.map(async ({ tool, cap }) =>
            this.executeTool(tool, cap, phase, startTime, execOptions),
          ),
        )
        for (const r of results) {
          findings.push(...r.findings)
          errors.push(...r.errors)
        }
        // In parallel mode, never abort the phase on individual tool failures.
        // Tools are independent — one tool's failure has no bearing on others.
        // Accumulate all findings and errors, then continue to the next batch.
        // The fail_fast concept only applies in sequential mode (below) where
        // a destructive tool could leave the target in a compromised state.
      }
    } else {
      // Sequential execution
      if (execOptions.verbose) console.log(`[executor]  Executing ${toolConfigs.length} tool(s) sequentially`)
      for (const { tool, cap } of toolConfigs) {
        const result = await this.executeTool(tool, cap, phase, startTime, execOptions)
        findings.push(...result.findings)
        errors.push(...result.errors)
        if (result.failFast) {
          return {
            phaseId: phase.phaseId,
            status: "failed",
            findings,
            artifacts: [],
            errors,
            durationMs: Date.now() - startTime,
          }
        }
      }
    }

    return {
      phaseId: phase.phaseId,
      status: errors.length > 0 && findings.length > 0 ? "partial" : errors.length > 0 && findings.length === 0 ? "failed" : "completed",
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
    let iterations = 0
    const maxIterations = (() => {
      const raw = process.env.ARGUS_HYBRID_MAX_ITERATIONS
      if (raw === undefined || raw === "") return 50
      const n = Number(raw)
      return Number.isFinite(n) && n > 0 ? n : 50
    })()

    while (!done) {
      if (++iterations >= maxIterations) {
        errors.push(`Hybrid executor exceeded maximum iterations (${maxIterations}) — stopping`)
        break
      }
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
          ? Math.max(0, Math.ceil((300_000 - (Date.now() - status.circuitOpenedAt)) / 1000))
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

      // 4b. Per-tool destructive confirmation (Task 4.1)
      if (this.isFeatureEnabled(Feature.APPROVAL_GATES)) {
        const toolDef = this.toolRegistry.getTool(next.tool)
        if (toolDef?.destructive) {
          const toolApproval = await this.approvalService.confirmDestructiveTool(
            next.tool,
            toolDef.label,
            phase.target,
          )
          if (!toolApproval.approved) {
            const reason = toolApproval.reason ?? "Skipped by user"
            errors.push(`Destructive tool ${next.tool} skipped: ${reason}`)
            await this.bridge.agentObserve({
              session_id: session.session_id,
              tool: next.tool,
              success: false,
              summary: reason,
            })
            continue
          }
        }
      }

      // 5. Execute tool
      const toolStartTime = Date.now()
      try {
        const cap = pipeline.find(p => p.tool === next.tool)?.capabilities?.[0] ?? Capability.WEB_RECON
        const toolArgs: Record<string, unknown> = {
          target: phase.target,
          capability: cap,
          config: phase.config,
        };
        const extra = this.buildExtraFromCredentials(phase.config);
        if (extra) toolArgs.extra = extra;
        const credsFile = await this.buildCredsFile(next.tool, phase.config)
        if (credsFile) toolArgs.creds_file = credsFile;
        // Use per-tool timeout from registry — matches executeTool() at line 473.
        // Without this, callTool defaults to 600s which may be too short for deep
        // scans (sqlmap, nuclei) or unnecessarily long for quick tools (httpx, gau).
        const toolTimeout = this.toolRegistry.getToolTimeout(next.tool) * 1000
        const result = await this.bridge.callTool(next.tool, toolArgs, toolTimeout, execOptions.cacheMode)
        const durationMs = Date.now() - toolStartTime

        if (result.success) {
          this.toolHealth.recordSuccess(next.tool, durationMs)

          // Parse findings from structured data
          if (result.data) {
            const data = result.data
            if (Array.isArray(data)) {
              for (const finding of data) {
                const promoted = this.confidenceEngine.promote(finding)
                findings.push({ ...finding, confidence: promoted })
              }
            } else if (typeof data === "string" && data.length > 0) {
              const baseConfidence = baselineConfidence(result.signalQuality)
              findings.push({
                id: `find-${next.tool}-${crypto.randomUUID()}`,
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
        if (error instanceof LLMUnavailableError) {
          errors.push(`Tool ${next.tool} skipped — LLM ${error.status}${error.retryAfter ? ` (retry in ${error.retryAfter}s)` : ""}`)
          this.bridge.resetCircuitBreaker()
          await this.bridge.agentObserve({
            session_id: session.session_id,
            tool: next.tool,
            success: false,
            summary: `LLM ${error.status} — skipping`,
          })
          continue
        }
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
      status: errors.length > 0 && findings.length === 0 ? "failed" : errors.length > 0 && findings.length > 0 ? "partial" : "completed",
      findings,
      artifacts: [],
      errors,
      durationMs: Date.now() - startTime,
    }
  }

  private async executeTool(
    tool: ToolDef,
    cap: Capability,
    phase: PhaseExecutionRequest,
    phaseStartTime: number,
    execOptions: ExecutionOptions,
  ): Promise<{ findings: NormalizedFinding[]; errors: string[]; failFast: boolean }> {
    if (!this.toolHealth.isHealthy(tool.name)) {
      if (execOptions.verbose) console.log(`[executor]  ⛔ Tool ${tool.name} skipped — circuit breaker open`)
      return { findings: [], errors: [`Tool ${tool.name} is temporarily unavailable (circuit breaker)`], failFast: false }
    }

    if (execOptions.verbose) console.log(`[executor]  ▶ Tool ${tool.name} (attempt 1, capability: ${cap})`)

    const errorRecovery = this.resolveErrorRecovery(phase, tool.name)
    let lastError: Error | null = null
    let success = false
    const findings: NormalizedFinding[] = []

    for (let attempt = 1; attempt <= 2; attempt++) {
      const attemptStartTime = Date.now()
      // Use per-tool timeout from registry (checks argus.config.yaml override first,
      // then YAML tool-definition timeout, defaulting to 120s). This ensures:
      // 1. Custom timeouts from argus.config.yaml are respected
      // 2. YAML-defined timeouts (e.g. nuclei 600s, sqlmap 600s) aren't killed at 120s
      // 3. Agent-internal tools get their extended timeout from tool-definitions.yaml
      const timeoutSeconds = this.toolRegistry.getToolTimeout(tool.name)
      const toolTimeout = timeoutSeconds * 1000
      try {
        // Scope check — skip if target is not in authorized scope
        if (this.scopeConfig?.mode === "allowlist") {
          const isAllowed = this.scopeConfig.allowed_targets?.some(
            (pattern: string) => phase.target.includes(pattern.replace("*.", ""))
          ) ?? false
          if (!isAllowed) {
            console.warn(`[executor] Target ${phase.target} is out of scope — skipping tool ${tool.name}`)
            return { findings: [], errors: [`Target ${phase.target} is out of scope`], failFast: false }
          }
        }

        // Populate extra with credentials for tools (login/register) that
        // expect credential data in the --extra JSON parameter.
        const toolArgs: Record<string, unknown> = {
          target: phase.target,
          capability: cap,
          config: phase.config,
        };
        const extra = this.buildExtraFromCredentials(phase.config);
        if (extra) toolArgs.extra = extra;
        const credsFile = await this.buildCredsFile(tool.name, phase.config)
        if (credsFile) toolArgs.creds_file = credsFile;
        if (execOptions.verbose) {
          // Only log safe fields to avoid leaking credentials from config
          const safeArgs = { target: toolArgs.target, capability: toolArgs.capability }
          console.log(`[executor]    Args:`, JSON.stringify(safeArgs))
        }

        // Per-tool destructive confirmation (Task 4.1)
        // Runs AFTER phase-level approval, giving users a second safety prompt
        // before individual destructive tools execute. In TTY mode, the user
        // can approve/reject each destructive tool independently.
        if (tool.destructive && this.isFeatureEnabled(Feature.APPROVAL_GATES)) {
          const toolApproval = await this.approvalService.confirmDestructiveTool(
            tool.name,
            tool.label,
            phase.target,
          )
          if (!toolApproval.approved) {
            const reason = toolApproval.reason ?? "Skipped by user"
            if (execOptions.verbose) {
              console.log(`[executor]  ⛔ Destructive tool ${tool.name} skipped: ${reason}`)
            }
            return { findings: [], errors: [`Destructive tool ${tool.name} skipped: ${reason}`], failFast: false }
          }
          if (execOptions.verbose) {
            console.log(`[executor]  ✓ Destructive tool ${tool.name} confirmed`)
          }
        }

        const result = await this.bridge.callTool(tool.name, toolArgs, toolTimeout, execOptions.cacheMode)
        // Clear credential data from args after the call
        delete toolArgs.extra

        if (execOptions.verbose) console.log(`[executor]    Result: success=${result.success}, duration=${result.durationMs}ms`)

        if (result.success && result.data) {
          const data = result.data
          const baseConfidence = baselineConfidence(result.signalQuality)
          if (Array.isArray(data)) {
            for (const finding of data) {
              const conf = Math.max(finding.confidence ?? 0, baseConfidence)
              const promoted = this.confidenceEngine.promote({ ...finding, confidence: conf })
              findings.push({ ...finding, confidence: promoted })
            }
            this.toolHealth.recordSuccess(tool.name, Date.now() - attemptStartTime)
            success = true
            break
          } else if (typeof data === "string" && data.length > 0) {
            const truncated = data.length > 500 ? data.substring(0, 500) + "..." : data
            findings.push({
              id: `find-${tool.name}-${crypto.randomUUID()}`,
              title: `${tool.name} scan against ${phase.target}`,
              severity: 2,
              confidence: baseConfidence,
              status: "PENDING",
              description: truncated,
              tool: tool.name,
              phase: phase.phaseId,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            })
            this.toolHealth.recordSuccess(tool.name, Date.now() - attemptStartTime)
            success = true
            break
          }
        }
        lastError = new Error(result.error ?? "Tool returned unsuccessful result")
        this.toolHealth.recordFailure(tool.name, lastError.message)
        if (errorRecovery === "fail_fast") {
          return { findings, errors: [`Tool ${tool.name} failed (fail_fast): ${lastError.message}`], failFast: true }
        }
        if (errorRecovery === "retry_once_then_skip" && attempt === 1) continue
        break
      } catch (error) {
        if (error instanceof LLMUnavailableError) {
          this.bridge.resetCircuitBreaker()
          return { findings, errors: [`Tool ${tool.name} skipped — LLM ${error.status}${error.retryAfter ? ` (retry in ${error.retryAfter}s)` : ""}`], failFast: false }
        }
        lastError = error as Error
        this.toolHealth.recordFailure(tool.name, lastError.message)
        if (errorRecovery === "fail_fast") {
          return { findings, errors: [`Tool ${tool.name} failed (fail_fast): ${lastError.message}`], failFast: true }
        }
        if (errorRecovery === "retry_once_then_skip" && attempt === 1) continue
        break
      }
    }

    if (!success && lastError) {
      return { findings, errors: [`Tool ${tool.name} failed after ${errorRecovery === "retry_once_then_skip" ? "1 retry" : "no retry"} (${RECOVERY_LABELS[errorRecovery]}): ${lastError.message}`], failFast: false }
    }

    return { findings, errors: [], failFast: false }
  }

  /**
   * Build an `extra` JSON string from credentials in the phase config.
   * Tools like login/register use the `--extra` JSON parameter for
   * credential data (email/password), but the executor previously never
   * populated this field — causing "NO_CREDENTIALS" errors.
   *
   * At runtime, credentials are stored as a single CredentialEntry-like
   * object: `{ username, password }` or `{ email, password }`.
   */
  private buildExtraFromCredentials(config: Record<string, unknown>): string | undefined {
    const creds = config?.credentials as Record<string, unknown> | undefined
    if (!creds) return undefined

    // Support both direct CredentialEntry { username, password }
    // and CredentialRef array [{ role, credentialType }] formats
    if (Array.isArray(creds)) {
      if (creds.length === 0) return undefined
      const first = creds[0] as Record<string, unknown>
      const entry = (first.credentialType as Record<string, unknown>) ?? first
      const email = (entry.username ?? entry.email ?? "") as string
      const password = (entry.password ?? "") as string
      if (!email && !password) return undefined
      return JSON.stringify({ email, password })
    }

    // Single CredentialEntry object { username, password }
    const email = (creds.username ?? creds.email ?? "") as string
    const password = (creds.password ?? "") as string
    if (!email && !password) return undefined
    return JSON.stringify({ email, password })
  }

  private async cleanupCreds(): Promise<void> {
    if (this.tempCredFiles.length === 0) return
    const { unlink } = await import("fs/promises")
    for (const f of this.tempCredFiles) {
      try {
        await unlink(f)
      } catch (err) {
        console.warn(`[executor] Failed to clean up temp creds file ${f}:`, (err as Error).message)
      }
    }
    this.tempCredFiles = []
  }

  /**
   * Build a temporary JSON credentials file for tools that accept
   * `--creds-file` (e.g. playwright-bola). The file is written with
   * mode 0o600 and tracked for cleanup.
   */
  private async buildCredsFile(toolName: string, config: Record<string, unknown>): Promise<string | null> {
    const creds = config?.credentials
    if (!creds || (Array.isArray(creds) && creds.length === 0)) return null
    const { CredentialStore } = await import("../engagement/credentials")
    const { writeFile, mkdtemp } = await import("fs/promises")
    const { join } = await import("path")
    const { tmpdir } = await import("os")

    const credStore = new CredentialStore()
    credStore.load()
    const allRoles = credStore.getAllCredentials()

    const toolDef = this.toolRegistry.getTool(toolName)
    const requiredRoles = toolDef?.credential_roles ?? ["attacker", "victim"]

    const selected: Record<string, unknown> = {}
    for (const role of requiredRoles) {
      const match = Object.entries(allRoles).find(
        ([key]) => key.toLowerCase() === role.toLowerCase() || key.toLowerCase().includes(role.toLowerCase()),
      )
      if (match) selected[role] = match[1]
    }

    if (Object.keys(selected).length === 0) return null

    const tmpDir = await mkdtemp(join(tmpdir(), "argus-creds-"))
    const credsPath = join(tmpDir, "credentials.json")
    await writeFile(credsPath, JSON.stringify(selected, null, 2), { mode: 0o600 })
    this.tempCredFiles.push(credsPath)
    return credsPath
  }

  private resolveErrorRecovery(phase: PhaseExecutionRequest, toolName: string): ErrorRecovery {
    const tool = this.toolRegistry.getTool(toolName)
    if (tool?.destructive) return "fail_fast"
    if (tool?.requires_auth) return "skip_and_continue"
    return "retry_once_then_skip"
  }
}

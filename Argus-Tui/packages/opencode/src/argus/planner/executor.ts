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

/**
 * Cross-tool rate limiter — sliding window that limits requests per second
 * across ALL tools targeting a given target (blocker 44).
 * Prevents tools like nuclei (150 req/s) + ffuf (200 req/s) from
 * overloading the target simultaneously.
 *
 * Uses a per-target sliding window. Configured via env var:
 *   ARGUS_CROSS_TOOL_RATE_LIMIT: max requests per window (default 50)
 *   ARGUS_CROSS_TOOL_RATE_WINDOW_MS: window duration in ms (default 1000)
 */
export class CrossToolRateLimiter {
  private windows = new Map<string, number[]>()
  private readonly maxRequests: number
  private readonly windowMs: number

  constructor() {
    const rawLimit = process.env.ARGUS_CROSS_TOOL_RATE_LIMIT
    const parsedLimit = rawLimit ? Number(rawLimit) : NaN
    this.maxRequests = Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : 50
    const parsedWindow = Number(process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS)
    this.windowMs = Number.isFinite(parsedWindow) && parsedWindow > 0 ? parsedWindow : 1000
  }

  /** Acquire a slot for the given target. Returns delay needed (ms), or 0 if allowed. */
  acquire(target: string): number {
    const now = Date.now()
    const windowStart = now - this.windowMs

    let timestamps = this.windows.get(target)
    if (!timestamps) {
      timestamps = []
      this.windows.set(target, timestamps)
    }

    // Prune old entries
    const valid = timestamps.filter(t => t > windowStart)
    this.windows.set(target, valid)

    if (valid.length >= this.maxRequests) {
      // Calculate when the next slot opens (the oldest timestamp + window)
      const oldest = valid[0]
      const delay = (oldest + this.windowMs) - now
      // Record that we'll fire at (now + delay)
      valid.push(now + delay)
      return Math.max(1, delay)
    }

    valid.push(now)
    return 0
  }

  /** Reset all rate limit windows (e.g. between phases). */
  reset(): void {
    this.windows.clear()
  }
}

/**
 * Throttle tracker for 429/503 responses (blocker 45).
 * Detects rate-limit errors from tool responses and applies exponential
 * backoff per target before allowing further requests.
 *
 * Configured via env var:
 *   ARGUS_THROTTLE_BASE_DELAY_MS: initial backoff delay (default 2000)
 *   ARGUS_THROTTLE_MAX_DELAY_MS:  maximum backoff delay (default 60000)
 */
export class ThrottleTracker {
  private throttledTargets = new Map<string, { until: number; backoffMs: number; consecutive: number }>()
  private readonly baseDelayMs: number
  private readonly maxDelayMs: number

  constructor() {
    const rawBase = process.env.ARGUS_THROTTLE_BASE_DELAY_MS
    const parsedBase = Number(rawBase)
    this.baseDelayMs = Number.isFinite(parsedBase) && parsedBase > 0 ? parsedBase : 2000
    const parsedMax = Number(process.env.ARGUS_THROTTLE_MAX_DELAY_MS)
    this.maxDelayMs = Number.isFinite(parsedMax) && parsedMax > 0 ? parsedMax : 60000
  }

  /** Returns true if the target is currently throttled. */
  isThrottled(target: string): boolean {
    const entry = this.throttledTargets.get(target)
    if (!entry) return false
    if (Date.now() >= entry.until) {
      this.throttledTargets.delete(target)
      return false
    }
    return true
  }

  /** Get remaining throttle delay in ms, or 0 if not throttled. */
  getRemainingDelay(target: string): number {
    const entry = this.throttledTargets.get(target)
    if (!entry) return 0
    const remaining = entry.until - Date.now()
    return Math.max(0, remaining)
  }

  /**
   * Detect if an error message indicates rate limiting (429/503/etc).
   * Returns true if the error matches known rate-limit patterns.
   */
  static isRateLimitError(errorMessage: string): boolean {
    const lower = (errorMessage ?? "").toLowerCase()
    return /\b429\b/.test(lower)
      || /\b503\b/.test(lower)
      || /rate.?limit/i.test(lower)
      || /too many requests/i.test(lower)
      || /retry[\s-]after/i.test(lower)
      || /throttl/i.test(lower)
  }

  /**
   * Record a rate-limit hit for the given target.
   * Applies exponential backoff: base * 2^consecutive, capped at max.
   */
  recordThrottle(target: string): void {
    const current = this.throttledTargets.get(target)
    const consecutive = (current?.consecutive ?? 0) + 1
    const delay = Math.min(this.baseDelayMs * Math.pow(2, consecutive - 1), this.maxDelayMs)
    this.throttledTargets.set(target, {
      until: Date.now() + delay,
      backoffMs: delay,
      consecutive,
    })
  }

  /**
   * Record a successful response for the target (resets backoff).
   */
  recordSuccess(target: string): void {
    this.throttledTargets.delete(target)
  }

  /** Reset all throttle state (e.g., between phases). */
  reset(): void {
    this.throttledTargets.clear()
  }
}

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
  /** Cross-tool rate limiter (blocker 44). */
  private rateLimiter: CrossToolRateLimiter = new CrossToolRateLimiter()
  /** Target throttle tracker for 429/503 backoff (blocker 45). */
  private throttleTracker: ThrottleTracker = new ThrottleTracker()
  /** Phase-relative max duration per phase (env ARGUS_MAX_PHASE_DURATION_MS, default 30 min). */
  private maxPhaseDurationMs: number = (() => {
    const raw = process.env.ARGUS_MAX_PHASE_DURATION_MS
    if (raw === undefined || raw === "") return 1_800_000  // 30 min
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : 1_800_000
  })()
  /** Global max assessment duration (env ARGUS_MAX_ASSESSMENT_DURATION_MS, default 2 hours). */
  private maxAssessmentDurationMs: number = (() => {
    const raw = process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS
    if (raw === undefined || raw === "") return 7_200_000  // 2 hours
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : 7_200_000
  })()
  private assessmentStartTime: number = 0
  /** Per-phase deadline (set at phase start). Used in both execute() and executeHybrid(). */
  private phaseDeadline: number = 0

  /** Check if the current phase has exceeded its timeout (blocker 35). */
  private checkPhaseTimeout(): string | null {
    if (this.phaseDeadline > 0 && Date.now() > this.phaseDeadline) {
      return `Phase exceeded ${this.maxPhaseDurationMs}ms timeout`
    }
    return null
  }

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

  /**
   * Consume an MCP verification result and cascade confidence promotion.
   * Called from the workflow runner after receiving verification results
   * from the finding_verifier MCP tool.
   *
   * This promotes findings through the full cascade:
   *   MEDIUM → HIGH → VERIFIED → CONFIRMED
   *
   * Each promote() call advances at most one tier, so the while loop is
   * required to reach CONFIRMED in a single pass.
   *
   * @param finding - The finding to promote. Its confidence is updated in-place.
   * @returns The promoted confidence level.
   */
  consumeVerificationResult(finding: NormalizedFinding): number {
    let promoted = this.confidenceEngine.promote(finding)
    while (promoted !== finding.confidence) {
      finding.confidence = promoted
      promoted = this.confidenceEngine.promote(finding)
    }
    return promoted
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

    // Start global assessment timer on first phase execution (blocker 20 fix)
    // Guard ensures the timer starts once per assessment, not reset on each phase.
    if (this.assessmentStartTime === 0) {
      this.assessmentStartTime = Date.now()
    }

    // Global max-assessment-duration circuit breaker (blocker 20)
    if (this.assessmentStartTime > 0 && Date.now() - this.assessmentStartTime > this.maxAssessmentDurationMs) {
      return {
        phaseId: phase.phaseId,
        status: "failed",
        findings: [],
        artifacts: [],
        errors: [`Assessment duration exceeded ${this.maxAssessmentDurationMs}ms — global circuit breaker tripped`],
        durationMs: 0,
      }
    }      // Phase-level timeout (blocker 35) — set deadline for this phase
    this.phaseDeadline = Date.now() + this.maxPhaseDurationMs
    // Reset cross-tool rate limiter and throttle tracker at phase start (blockers 44, 45)
    this.rateLimiter.reset()
    this.throttleTracker.reset()

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
          // No local tools registered for this capability — it's handled
          // externally (e.g., post-exploitation → Python Celery pipeline).
          // Skip gracefully instead of adding an error that would mark the
          // phase as failed. The phase completes cleanly with zero findings.
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
      if (execOptions.verbose) console.log(`[executor]  Cross-tool rate limiter reset for ${phase.name}`)
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
      engagementId: phase.config?.engagementId as string | undefined,
    })
    const hypotheses = session.hypotheses ?? []

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
      // Pass max_iterations so the Python side caps its loop (blocker 32).
      const next = await this.bridge.agentNext({
        session_id: session.session_id,
        max_iterations: maxIterations,
      })
      if (next.done || !next.tool) {
        done = true
        break
      }

      // 3b. Check phase timeout before executing next tool (blocker 35)
      const pto = this.checkPhaseTimeout()
      if (pto) {
        errors.push(pto)
        break
      }

      // 4. Check tool health before executing
      if (!this.toolHealth.isHealthy(next.tool)) {
        // Blocker 6: Try fallback tool for the same capability
        const cap = pipeline.find(p => p.tool === next.tool)?.capabilities?.[0] ?? Capability.WEB_RECON
        const fallback = this.findFallbackTool(next.tool, cap as Capability)
        if (fallback) {
          if (execOptions.verbose) console.log(`[executor]  ⛔ Tool ${next.tool} circuit-broken — hybrid fallback to ${fallback.name}`)
          // Execute the fallback tool directly
          const fallbackResult = await this.executeTool(fallback, cap as Capability, phase, startTime, execOptions)
          findings.push(...fallbackResult.findings)
          errors.push(...fallbackResult.errors)
          await this.bridge.agentObserve({
            session_id: session.session_id,
            tool: fallback.name,
            success: fallbackResult.findings.length > 0 || fallbackResult.errors.length === 0,
            findingCount: fallbackResult.findings.length,
            summary: `${fallback.name} (fallback): ${fallbackResult.findings.length} findings`,
          })
          continue
        }
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

      // 4c. Cross-tool rate limiting (blocker 44)
      const rateDelay = this.rateLimiter.acquire(phase.target)
      if (rateDelay > 0) {
        if (execOptions.verbose) console.log(`[executor]  ⏱ Rate limit hit for ${phase.target} — waiting ${rateDelay}ms`)
        await new Promise(r => setTimeout(r, rateDelay))
      }

      // 4d. Target throttle check (blocker 45): 429/503 backoff
      const thrRemaining = this.throttleTracker.getRemainingDelay(phase.target)
      if (thrRemaining > 0) {
        if (execOptions.verbose) console.log(`[executor]  ⏱ Target ${phase.target} throttled — waiting ${thrRemaining}ms`)
        await new Promise(r => setTimeout(r, thrRemaining))
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

        // Hybrid path: check for rate-limit responses (blocker 45)
        if (!result.success && result.error && ThrottleTracker.isRateLimitError(result.error)) {
          this.throttleTracker.recordThrottle(phase.target)
          if (execOptions.verbose) console.log(`[executor]  ⏱ Target ${phase.target} returned rate-limit error — backing off`)
        } else if (result.success) {
          this.throttleTracker.recordSuccess(phase.target)
        }

        if (result.success) {
          this.toolHealth.recordSuccess(next.tool, durationMs)

          // Parse findings from structured data
          if (result.data) {
            // Phase 4.5.5: Consume the "structured" key from MCP responses.
            // The Python MCP server stores structured findings with proper
            // severity, CWE, and evidence in mcp_result.data["structured"].
            // These were previously bypassed because the executor only checked
            // result.data for raw arrays or strings.
            const structuredData = (result.data as any).structured as Array<Record<string, unknown>> | undefined
            if (structuredData && Array.isArray(structuredData) && structuredData.length > 0) {
              for (const finding of structuredData) {
                const promoted = this.confidenceEngine.promote(finding as any)
                findings.push({ ...finding, confidence: promoted } as any)
              }
            } else if (Array.isArray(result.data)) {
              for (const finding of result.data) {
                const promoted = this.confidenceEngine.promote(finding)
                findings.push({ ...finding, confidence: promoted })
              }
            } else if (typeof result.data === "string" && result.data.length > 0) {
              const baseConfidence = baselineConfidence(result.signalQuality)
              findings.push({
                id: `find-${next.tool}-${crypto.randomUUID()}`,
                title: `${next.tool} scan against ${phase.target}`,
                severity: 2,
                confidence: baseConfidence,
                status: "PENDING",
                description: (result.data as string).slice(0, 500),
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
          // Gap 9.2: Do NOT call resetCircuitBreaker() here — let failures
          // accumulate so the circuit opens after the threshold is reached.
          // The circuit recovers naturally via half-open semantics after the
          // cooldown expires and a probe succeeds.
          errors.push(`Tool ${next.tool} skipped — LLM ${error.status}${error.retryAfter ? ` (retry in ${error.retryAfter}s)` : ""}`)
          await this.bridge.agentObserve({
            session_id: session.session_id,
            tool: next.tool,
            success: false,
            summary: `LLM ${error.status} — skipping`,
          })
          continue
        }
        const errorMsg = (error as Error).message
        // Check for rate-limit errors in hybrid catch block too (blocker 45)
        if (ThrottleTracker.isRateLimitError(errorMsg)) {
          this.throttleTracker.recordThrottle(phase.target)
          if (execOptions.verbose) console.log(`[executor]  ⏱ Target ${phase.target} rate-limited in hybrid catch block — backing off`)
        }
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
      hypotheses,
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
      // Blocker 6: Try fallback tool for the same capability before giving up.
      // This ensures we still get results even when the preferred tool is
      // circuit-broken (e.g., dalfox down → try xsser for XSS detection).
      const fallback = this.findFallbackTool(tool.name, cap)
      if (fallback) {
        if (execOptions.verbose) {
          console.log(`[executor]  ⛔ Tool ${tool.name} circuit-broken — trying fallback ${fallback.name}`)
        }
        return this.executeTool(fallback, cap, phase, phaseStartTime, execOptions)
      }
      if (execOptions.verbose) console.log(`[executor]  ⛔ Tool ${tool.name} skipped — circuit breaker open, no fallback for ${cap}`)
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

        // Cross-tool rate limiting: check before executing (blocker 44)
        const rateDelay = this.rateLimiter.acquire(phase.target)
        if (rateDelay > 0) {
          if (execOptions.verbose) console.log(`[executor]  ⏱ Rate limit hit for ${phase.target} — waiting ${rateDelay}ms`)
          await new Promise(r => setTimeout(r, rateDelay))
        }

        // Target throttle check (blocker 45): 429/503 backoff
        const throttleRemaining = this.throttleTracker.getRemainingDelay(phase.target)
        if (throttleRemaining > 0) {
          if (execOptions.verbose) console.log(`[executor]  ⏱ Target ${phase.target} throttled — waiting ${throttleRemaining}ms`)
          await new Promise(r => setTimeout(r, throttleRemaining))
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

        // Check phase timeout before processing results (blocker 35)
        const timeoutErr = this.checkPhaseTimeout()
        if (timeoutErr) {
          if (execOptions.verbose) console.log(`[executor]  ⛔ Phase timeout reached — stopping tool loop`)
          return { findings, errors: [timeoutErr], failFast: true }
        }

        // Check if the response indicates target rate limiting (blocker 45)
        if (!result.success && result.error && ThrottleTracker.isRateLimitError(result.error)) {
          this.throttleTracker.recordThrottle(phase.target)
          if (execOptions.verbose) console.log(`[executor]  ⏱ Target ${phase.target} returned rate-limit error — backing off`)
        } else if (result.success) {
          // Successful response — reset throttle state for this target
          this.throttleTracker.recordSuccess(phase.target)
        }

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
          // Gap 9.2: Do NOT call resetCircuitBreaker() here — let failures
          // accumulate so the circuit opens after the threshold is reached.
          // The circuit recovers naturally via half-open semantics after the
          // cooldown expires and a probe succeeds.
          return { findings, errors: [`Tool ${tool.name} skipped — LLM ${error.status}${error.retryAfter ? ` (retry in ${error.retryAfter}s)` : ""}`], failFast: false }
        }
        // Check for rate-limit errors in catch block too (blocker 45)
        const errMsg = (error as Error).message
        if (ThrottleTracker.isRateLimitError(errMsg)) {
          this.throttleTracker.recordThrottle(phase.target)
          if (execOptions.verbose) console.log(`[executor]  ⏱ Target ${phase.target} rate-limited in catch block — backing off`)
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

  /**
   * Find a fallback tool when the primary tool is circuit-broken (blocker 6).
   * Looks for another enabled tool that covers the same capability.
   * Skips tools that are also circuit-broken or are the original tool.
   */
  private findFallbackTool(unhealthyTool: string, cap: Capability): ToolDef | undefined {
    const alternatives = this.toolRegistry.getToolsByCapability(cap)
    for (const alt of alternatives) {
      if (alt.name === unhealthyTool) continue
      // Skip if the alternative is also circuit-broken
      if (!this.toolHealth.isHealthy(alt.name)) continue
      // Skip destructive tools unless approved
      if (alt.destructive && !this.isFeatureEnabled(Feature.APPROVAL_GATES)) continue
      return alt
    }
    return undefined
  }

  private resolveErrorRecovery(phase: PhaseExecutionRequest, toolName: string): ErrorRecovery {
    const tool = this.toolRegistry.getTool(toolName)
    if (tool?.destructive) return "fail_fast"
    if (tool?.requires_auth) return "skip_and_continue"
    return "retry_once_then_skip"
  }
}

import { spawn, ChildProcess } from "child_process"
import { createInterface } from "readline"
import { accessSync, constants } from "fs"
import { join } from "path"
import type { ToolDefinition, ToolResult, MCPError, DriftReport, CacheMode } from "./types"
import { LLMUnavailableError } from "./types"
import { WorkerSupervisor } from "./supervisor"
import { PROJECT_ROOT } from "../shared/path"

interface PendingRequest {
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  timer: ReturnType<typeof setTimeout>
}

interface RPCRequest {
  jsonrpc: "2.0"
  id: string
  method: string
  params?: unknown
}

interface RPCResponse {
  jsonrpc: "2.0"
  id: string
  result?: unknown
  error?: MCPError
}

const LLM_STATUS = ["AVAILABLE", "DEGRADED", "UNAVAILABLE"] as const
type LLMStatus = (typeof LLM_STATUS)[number]

/**
 * Timeout for the `agent_*` RPCs. They are not plain tool dispatches: the
 * worker's engine does the thinking in them.
 *
 * `agent_init` has the engine choose the phase's tools, which is one LLM call
 * per planned tool, and `agent_next`/`agent_observe` can re-plan off a stuck or
 * failed tool. The 30s default cut `agent_init` off mid-planning and failed the
 * whole `llm_driven` phase — no tool choice was ever recorded for it. Measured
 * against the free gateway this run's demo uses, one planning call took 145s.
 *
 * Ten minutes is the same ceiling `callTool` gives a security tool, and it
 * clears the worker's own `ARGUS_PLAN_BUDGET_SECONDS` (90s) plus the slowest
 * call that budget can still be waiting on.
 */
const AGENT_PLANNING_TIMEOUT_MS = 600_000

/**
 * Resolve the interpreter used to spawn the Python worker.
 *
 * Order: `ARGUS_PYTHON` → the repo virtualenv (`argus-workers/venv`) → bare
 * `python3`.
 *
 * The venv matters for reproducibility: defaulting to bare `python3` means a
 * run depends on the worker's dependencies happening to be installed on the
 * system interpreter, which is environmental luck rather than a configuration.
 */
export function resolveDefaultPython(): string {
  const explicit = process.env.ARGUS_PYTHON?.trim()
  if (explicit) return explicit

  const venv = join(PROJECT_ROOT, "argus-workers", "venv")
  const candidates = [join(venv, "bin", "python"), join(venv, "Scripts", "python.exe")]
  for (const candidate of candidates) {
    try {
      accessSync(candidate, constants.X_OK)
      return candidate
    } catch {
      // try next candidate
    }
  }

  return "python3"
}

export class WorkersBridge {
  private process: ChildProcess | null = null
  private rl: ReturnType<typeof createInterface> | null = null
  private pending = new Map<string, PendingRequest>()
  private requestId = 0
  public supervisor: WorkerSupervisor
  private toolsCache: ToolDefinition[] = []     // Registry tools (set by setRegistryTools)
  private _mcpToolsCache: ToolDefinition[] = []  // MCP tools (fetched from worker)
  private _toolsEverFetched = false
  private _llmStatus: LLMStatus = "AVAILABLE"
  private statusListeners: Array<(status: string) => void> = []

  /** Phase 4.2.2: Cache of recent tool results used when the worker is in degraded mode.
   *  Keyed by tool name, stores the last successful result so non-critical operations
   *  can return cached data instead of failing when the MCP worker is unavailable.
   *  Each entry tracks hit count to prevent stale data from being served
   *  indefinitely (blocker 7). */
  private degradedToolCache = new Map<string, {
    result: ToolResult
    timestamp: number
    /** Number of times this cached result has been served. Reset on each fresh cache write. */
    hitCount: number
  }>()
  /** Max age for cached results in degraded mode (5 minutes by default, configurable via ARGUS_DEGRADED_CACHE_TTL_MS). */
  private static get DEGRADED_CACHE_TTL_MS(): number {
    const raw = process.env.ARGUS_DEGRADED_CACHE_TTL_MS
    if (raw === undefined || raw === "") return 5 * 60 * 1000
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : 5 * 60 * 1000
  }
  /** Max cache hits before a cached result transitions to stale (default 3). */
  private static readonly DEGRADED_CACHE_MAX_HITS = 3

  private pendingCount = 0
  private readonly maxPending: number

  // Circuit breaker state (Gap 9.2: must track failures across calls)
  private circuitFailures = 0
  private readonly circuitThreshold: number = (() => {
    const raw = process.env.ARGUS_LLM_CIRCUIT_THRESHOLD
    // Must equal Python's max_retries + 1 (default: max_retries=2 → threshold=3)
    if (raw === undefined || raw === "") return 3
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : 3
  })()
  private circuitOpenUntil = 0
  private readonly circuitCooldown: number = (() => {
    const raw = process.env.ARGUS_LLM_CIRCUIT_COOLDOWN_MS
    // Aligned with Python _circuit_cooldown=30s (default)
    if (raw === undefined || raw === "") return 30_000
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : 30_000
  })()
  private readonly llmToolNames = new Set(["finding_verifier", "llm_detector", "llm_payload_generator"])

  // Signal forwarding state
  private signalHandlers: Array<{ signal: NodeJS.Signals; handler: () => void }> = []
  private forwardingEnabled = false
  /** Flag to prevent restart races when disconnect is intentional */
  private _disconnecting = false
  /** Single-flight guard so two restart triggers cannot kill each other's worker. */
  private _restartInFlight = false
  /** Periodic health probe interval handle (blocker 15). */
  private _healthProbeTimer: ReturnType<typeof setInterval> | null = null
  /** Default health probe interval in ms (30s). */
  private static readonly HEALTH_PROBE_INTERVAL_MS = 30_000

  constructor(
    private workersPath: string,
    private pythonPath: string = resolveDefaultPython(),
    options?: { maxPending?: number },
  ) {
    this.maxPending = options?.maxPending ?? 10
    this.supervisor = new WorkerSupervisor({
      killChild: () => this.killChild(),
      connect: () => this.connect(),
      isHealthy: () => this.isHealthy(),
    })
  }

  private validatePaths(): void {
    const VALID_PYTHON = new Set(["python3", "python", "python3.12"])
    // ARGUS_PYTHON (and the default venv path) may be an absolute executable;
    // those are validated by the accessSync check below.
    if (!VALID_PYTHON.has(this.pythonPath)) {
      try {
        accessSync(this.pythonPath, constants.X_OK)
      } catch {
        throw new Error(
          `Invalid pythonPath: "${this.pythonPath}" is not "python3", "python", or a resolvable executable`
        )
      }
    }
    if (!this.workersPath.endsWith("mcp_server.py")) {
      throw new Error(
        `Invalid workersPath: "${this.workersPath}" must end with "mcp_server.py"`
      )
    }
    try {
      accessSync(this.workersPath, constants.R_OK)
    } catch {
      throw new Error(
        `Invalid workersPath: "${this.workersPath}" does not exist or is not readable`
      )
    }
  }

  /** Register signal forwarding from parent to child process */
  enableSignalForwarding(): void {
    if (this.forwardingEnabled) return
    this.forwardingEnabled = true

    const forward = (signal: NodeJS.Signals) => {
      if (this.process && !this.process.killed) {
        try {
          this.process.kill(signal)
        } catch { /* process may already be dead */ }
      }
      // Don't prevent default — let the signal propagate
    }

    for (const signal of ["SIGTERM", "SIGINT"] as NodeJS.Signals[]) {
      const handler = () => forward(signal)
      process.on(signal, handler)
      this.signalHandlers.push({ signal, handler })
    }
  }

  /** Remove signal forwarding handlers */
  private disableSignalForwarding(): void {
    for (const { signal, handler } of this.signalHandlers) {
      process.removeListener(signal, handler)
    }
    this.signalHandlers = []
    this.forwardingEnabled = false
  }

  on(event: "llm-status-changed", handler: (status: string) => void): void {
    if (event === "llm-status-changed") {
      this.statusListeners.push(handler)
    }
  }

  llmStatus(): LLMStatus {
    return this._llmStatus
  }

  private setLLMStatus(status: LLMStatus): void {
    this._llmStatus = status
    for (const handler of this.statusListeners) {
      handler(status)
    }
  }

  async connect(): Promise<void> {
    this.validatePaths()
    this.cleanup()
    await this.spawnChild()
    this.enableSignalForwarding()
    this._startHealthProbes()
  }

  private cleanup(): void {
    this._stopHealthProbes()
    this.supervisor.cancelRecovery()
    this.disableSignalForwarding()
    if (this.rl) {
      this.rl.removeAllListeners()
      this.rl.close()
      this.rl = null
    }
    if (this.process) {
      this.process.removeAllListeners()
    }
    for (const { timer } of this.pending.values()) {
      clearTimeout(timer)
    }
    this.pending.clear()
    this.pendingCount = 0
    this.process = null
  }

  private async spawnChild(): Promise<void> {
    // Hold the child in a local for this spawn: the exit handler must know
    // which worker it belongs to, because a restart may have replaced it in
    // `this.process` before the exit event is delivered.
    const child = spawn(this.pythonPath, [this.workersPath], {
      stdio: ["pipe", "pipe", "pipe"],
      // Anchor the worker to the project root so it can resolve config files
      // and tool definitions relative to a known location regardless of where
      // the parent process was launched from.
      cwd: PROJECT_ROOT,
    })
    this.process = child

    this.rl = createInterface({
      input: child.stdout!,
    })

    // The worker may die at any moment (missing Python deps on CI, crash,
    // OOM). Writes to its closed stdin pipe emit an EPIPE 'error' event on
    // the Writable stream; without a handler bun raises it as an uncaught
    // exception that takes down the whole process. Swallow it — pending
    // requests are rejected by the process 'exit' handler instead.
    child.stdin?.on("error", (err: Error) => {
      if ((err as NodeJS.ErrnoException).code === "EPIPE") {
        // Expected when the worker exits — pending RPCs get rejected on exit.
        return
      }
      console.warn(`[MCP] stdin error: ${err.message}`)
    })

    let malformedLineCount = 0
    this.rl.on("line", (line: string) => {
      try {
        const response: RPCResponse = JSON.parse(line)
        const pending = this.pending.get(response.id)
        if (pending) {
          clearTimeout(pending.timer)
          this.pending.delete(response.id)
          if (response.error) {
            const err = new Error(response.error.message);
            (err as any).code = response.error.code
            pending.reject(err)
          } else {
            pending.resolve(response.result)
          }
        }
      } catch {
        malformedLineCount++
        if (malformedLineCount <= 5) {
          console.warn(`[MCP] Skipped malformed JSON line #${malformedLineCount} (first 200 chars): ${line.slice(0, 200)}`)
        }
      }
    })

    child.on("exit", (code) => this.handleChildExit(child, code, stderrBuffer))

    const stderrBuffer: string[] = []
    child.stderr?.on("data", (data: Buffer) => {
      stderrBuffer.push(data.toString())
    })

    await this.waitForReady()
    await this.getTools()
  }

  /**
   * Handle a worker exiting.
   *
   * The exit event is bound to the child that produced it, because a restart
   * replaces `this.process` before the old worker's exit is delivered. Acting on
   * a stale exit is what used to kill the replacement worker: `this.rl` was by
   * then the new worker's reader (so it was detached and the worker looked
   * "unresponsive"), pending calls to the new worker were rejected, and the
   * exit-triggered restart called killChild() — which acts on `this.process`,
   * i.e. the fresh worker. Every subsequent tool call then failed with
   * "Process not running" and the assessment finished with zero findings.
   */
  private handleChildExit(child: ChildProcess, code: number | null, stderrBuffer: string[]): void {
    if (this.process !== child) return

    // Reject all pending requests — process is gone
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer)
      pending.reject(new Error(`Process exited with code ${code}`))
    }
    this.pending.clear()
    this.pendingCount = 0
    this.rl?.removeAllListeners()
    this.rl?.close()
    child.stderr?.removeAllListeners()
    // Stop tracking the dead child so killChild() cannot act on it and a
    // later exit check sees "no worker", not "this worker".
    this.process = null
    if (code !== 0) {
      if (stderrBuffer.length > 0) {
        console.error(`[MCP Worker stderr]:\n${stderrBuffer.join("")}`)
      }
      console.warn(`[MCP] Worker exited with code ${code} — setting UNAVAILABLE`)
      this.setLLMStatus("UNAVAILABLE")
      if (!this._disconnecting) {
        this.restartWorker().catch((err) => {
          console.error(`[MCP] Worker restart failed after exit code ${code}:`, err)
        })
      }
    }
  }

  killChild(): void {
    const proc = this.process
    if (proc && !proc.killed && proc.exitCode === null && proc.pid !== undefined) {
      // Send SIGTERM to the process group to ensure child processes are also
      // terminated (blocker 40). Without this, orphaned grandchild processes
      // (nuclei, nmap, sqlmap subprocesses) linger after the parent dies.
      try {
        process.kill(-proc.pid, "SIGTERM")
      } catch {
        // Negative PID kill may not work on all platforms — fall back to
        // killing just the parent process
        proc.kill("SIGTERM")
      }
      setTimeout(() => {
        if (proc && !proc.killed && proc.exitCode === null && proc.pid !== undefined) {
          try {
            process.kill(-proc.pid, "SIGKILL")
          } catch {
            proc.kill("SIGKILL")
          }
        }
      }, 3000)
    }
  }

  async restartWorker(): Promise<void> {
    // Single-flight: the health probe and a worker exit can ask for a restart at
    // the same moment. Two overlapping restarts race on `this.process`, and the
    // loser's killChild() terminates the winner's freshly spawned worker.
    if (this._restartInFlight) return
    this._restartInFlight = true
    try {
      await this.supervisor.restartWorker()
    } finally {
      this._restartInFlight = false
    }
  }

  async isHealthy(timeoutMs?: number): Promise<boolean> {
    try {
      const result = await this.sendRequest("ping", {}, timeoutMs)
      // The Python worker answers `ping` with {"pong": true, "timestamp": ...}
      // (mcp_transport.create_ping_handler), which MCPTransport._process_request
      // wraps as the JSON-RPC `result`. Older/alternative transports answer with
      // the bare string "pong". Accept both — requiring only the string made
      // every readiness check fail, so spawnChild() always timed out and no tool
      // could ever execute.
      if (result === "pong") return true
      return (
        typeof result === "object" &&
        result !== null &&
        (result as { pong?: unknown }).pong === true
      )
    } catch {
      return false
    }
  }

  private async waitForReady(timeoutMs?: number): Promise<void> {
    // Read from env var with fallback to default 10s, then parameter
    const effectiveTimeout = timeoutMs ?? (() => {
      const raw = process.env.ARGUS_MCP_READY_TIMEOUT_MS
      if (raw === undefined || raw === "") return 10000
      const n = Number(raw)
      return Number.isFinite(n) && n > 0 ? n : 10000
    })()
    const start = Date.now()
    let delay = 200
    while (Date.now() - start < effectiveTimeout) {
      if (await this.isHealthy()) return
      await new Promise((r) => setTimeout(r, delay))
      delay = Math.min(delay * 2, 1600)
    }
    throw new Error(`MCP worker failed to become ready after ${effectiveTimeout}ms`)
  }

  /** Periodic health probe — returns true if worker is responsive. */
  async probeHealth(): Promise<boolean> {
    try {
      return await this.isHealthy(WorkersBridge.HEALTH_PROBE_TIMEOUT_MS)
    } catch {
      return false
    }
  }

  /** Probe ping timeout. A healthy *idle* worker answers in milliseconds, so a
   *  short timeout keeps a probe from overlapping the next interval when the
   *  worker is busy. */
  private static readonly HEALTH_PROBE_TIMEOUT_MS = 5_000

  /**
   * Whether a failed probe justifies restarting the worker.
   *
   * A busy worker is not a dead worker: the worker executes tools in-process,
   * one request at a time, so a long scan (nikto and nuclei run for minutes)
   * blocks its `ping` until the scan returns. Restarting on that timeout used to
   * SIGTERM the worker mid-scan — the in-flight call came back as "Process
   * exited with code null" and every later tool failed with "Process not
   * running". A worker that actually died is handled by its exit event, which
   * restarts it regardless of this probe.
   */
  private shouldRestartAfterFailedProbe(): boolean {
    if (this._disconnecting) return false
    // Supervisor is handling recovery autonomously via _scheduleRecovery after
    // the degraded cooldown — no need to trigger restarts from here.
    if (this.supervisor.degraded) return false
    if (this.pendingCount > 0) return false
    return true
  }

  /** Start periodic health probes every 30s while connected (blocker 15).
   *  If probeHealth() returns false, logs a warning and kicks off worker
   *  restart via the supervisor, unless the worker is busy or already
   *  degraded. Uses unref() so the timer doesn't keep the process alive. */
  private _startHealthProbes(): void {
    this._stopHealthProbes()
    this._healthProbeTimer = setInterval(async () => {
      const healthy = await this.probeHealth()
      if (healthy) return
      if (!this.shouldRestartAfterFailedProbe()) return
      console.warn(`[MCP] Health probe failed — worker unresponsive, initiating restart`)
      this.setLLMStatus("UNAVAILABLE")
      this.restartWorker().catch((err) => {
        console.error(`[MCP] Worker restart from health probe failed:`, err)
      })
    }, WorkersBridge.HEALTH_PROBE_INTERVAL_MS)
    this._healthProbeTimer.unref()
  }

  private _stopHealthProbes(): void {
    if (this._healthProbeTimer !== null) {
      clearInterval(this._healthProbeTimer)
      this._healthProbeTimer = null
    }
  }

  private async sendRequest(method: string, params?: unknown, timeoutMs = 30000): Promise<unknown> {
    if (this.pendingCount >= this.maxPending) {
      throw new Error(`Too many pending requests (max ${this.maxPending})`)
    }
    this.pendingCount++

    const id = String(++this.requestId)
    const request: RPCRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    }

    try {
      return await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.pending.delete(id)
          reject(new Error(`Request ${method} timed out after ${timeoutMs}ms`))
        }, timeoutMs)

        this.pending.set(id, { resolve, reject, timer })

        if (!this.process || this.process.exitCode !== null || this.process.killed) {
          clearTimeout(timer)
          this.pending.delete(id)
          reject(new Error("Process not running"))
          return
        }
        try {
          this.process.stdin!.write(JSON.stringify(request) + "\n")
        } catch (err) {
          clearTimeout(timer)
          this.pending.delete(id)
          reject(new Error(`Failed to write to process stdin: ${err}`))
          return
        }
      })
    } finally {
      this.pendingCount--
    }
  }

  async callTool(name: string, args: unknown, timeoutMs?: number, cacheMode?: CacheMode): Promise<ToolResult> {
    const now = Date.now()
    // Circuit breaker check — only for LLM-related tools (Gap 9.2 fix)
    // Non-LLM tools (nmap, nuclei, gau, etc.) bypass this check entirely
    // so a period of LLM failures doesn't block unrelated scanning tools.
    if (this.llmToolNames.has(name) && this.circuitOpenUntil > now) {
      const retryAfter = Math.ceil((this.circuitOpenUntil - now) / 1000)
      throw new LLMUnavailableError("UNAVAILABLE", retryAfter)
    }

    try {
      const raw = await this.sendRequest("call_tool", { name, arguments: args, cache_mode: cacheMode }, timeoutMs ?? 600000) // default 10min for security tools
      // Success — reset circuit breaker
      if (this.circuitFailures > 0) {
        this.circuitFailures = 0
        this.setLLMStatus("AVAILABLE")
      }

      // Transform MCP response format to ToolResult format
      // Python MCP server returns: { content: [...], isError: bool, meta: { success, duration_ms, tool, signal_quality } }
      // Executor expects:        { success: bool, data: unknown, error?: string, durationMs: number, signalQuality?: string }
      const mcpResponse = raw as {
        content?: Array<{ type: string; text: string }>
        isError?: boolean
        meta?: {
          success?: boolean
          duration_ms?: number
          tool?: string
          signal_quality?: string
          data?: { structured?: unknown }
        }
      }
      const text = mcpResponse.content?.[0]?.text ?? ""
      // The worker parses the tool's output with its own parser and returns the
      // findings under meta.data.structured. They — not the raw text — are the
      // findings: the text is stdout/stderr and is often just a CLI error
      // (e.g. "unknown flag: --json"), which must never be promoted downstream.
      const structuredRaw = mcpResponse.meta?.data?.structured
      const structured = Array.isArray(structuredRaw)
        ? structuredRaw.filter((f): f is Record<string, unknown> => !!f && typeof f === "object")
        : []
      const result: ToolResult = {
        success: mcpResponse.meta?.success ?? (mcpResponse.isError !== undefined ? !mcpResponse.isError : false),
        data: text,
        structured: structured.length > 0 ? structured : undefined,
        error: mcpResponse.isError ? text : undefined,
        durationMs: mcpResponse.meta?.duration_ms ?? 0,
        signalQuality: mcpResponse.meta?.signal_quality as ToolResult["signalQuality"],
      }
      // Phase 4.2.2: Cache successful results for degraded-mode fallback
      this.cacheToolResult(name, result)
      return result
    } catch (error) {
      // Python mcp_transport now includes structured error_type in error.data
      // (e.g. "llm_error") for known error categories. When available, use it
      // for detection instead of fragile string matching. Fall back to keyword
      // regex for older transport versions that don't send error_type.
      // WARNING: keep the regex list tight — callTool() is called for ALL tools
      // (incl. nuclei, nmap, etc.), not just LLM tools. Broad terms like "model"
      // or "api key" would cause cross-contamination from non-LLM tool errors.
      const errData = (error as any)?.data as { error_type?: string } | undefined
      const errType = errData?.error_type
      const errMsg = ((error as any)?.message ?? "").toLowerCase()
      const isLLMError = errType === "llm_error"
        || /\b(llm|openai|anthropic)\b/i.test(errMsg)
        || /\bai (provider|model)\b/i.test(errMsg)
        || errMsg.includes("llm is not available")

      if (isLLMError) {
        this.circuitFailures++
        if (this.circuitFailures >= this.circuitThreshold) {
          const cooldownSec = Math.ceil(this.circuitCooldown / 1000)
          console.warn(
            `[LLM Circuit Breaker] ${this.circuitFailures} consecutive LLM failures — ` +
            `circuit OPEN for ${cooldownSec}s. Subsequent LLM tool calls will fail fast until cooldown expires.`
          )
          this.circuitOpenUntil = now + this.circuitCooldown
          this.setLLMStatus("UNAVAILABLE")
          throw new LLMUnavailableError("UNAVAILABLE", cooldownSec)
        }
        console.warn(
          `[LLM Circuit Breaker] LLM failure ${this.circuitFailures}/${this.circuitThreshold} — ` +
          `circuit DEGRADED. ${this.circuitThreshold - this.circuitFailures} more failure(s) before circuit opens.`
        )
        this.setLLMStatus("DEGRADED")
        throw new LLMUnavailableError("DEGRADED", 30)
      }
      throw error
    }
  }

  async getTools(): Promise<ToolDefinition[]> {
    try {
      const result = await this.sendRequest("list_tools", {}) as { tools: ToolDefinition[] }
      this._mcpToolsCache = result.tools ?? []
      this._toolsEverFetched = true
      return this._mcpToolsCache
    } catch {
      if (!this._toolsEverFetched) {
        throw new Error("MCP worker tools never successfully fetched")
      }
      return this._mcpToolsCache
    }
  }
  /** Phase 4.2.2: Check if degraded mode is active (worker unavailable). */
  isDegraded(): boolean {
    return this.supervisor.degraded
  }

  /** Phase 4.2.2: Get a cached tool result from the degraded cache.
   *  Uses freshness tracking (blocker 7):
   *  - Hit count tracks how many times the cached result has been served
   *  - Warning logged at DEGRADED_CACHE_MAX_HITS (3) to indicate staleness
   *  - TTL expiry removes entry entirely
   *
   *  Returns undefined if no recent cache entry exists for the tool. */
  getCachedToolResult(toolName: string): ToolResult | undefined {
    const entry = this.degradedToolCache.get(toolName)
    if (!entry) return undefined

    // Check TTL expiry
    if (Date.now() - entry.timestamp > WorkersBridge.DEGRADED_CACHE_TTL_MS) {
      this.degradedToolCache.delete(toolName)
      return undefined
    }

    // Track hit count; warn when stale threshold is crossed
    entry.hitCount++
    if (entry.hitCount === WorkersBridge.DEGRADED_CACHE_MAX_HITS) {
      console.warn(
        `[MCP] Degraded cache stale for tool '${toolName}': served ${entry.hitCount} times since last write. ` +
        `Consider refreshing or switching to alternative tools.`
      )
    }

    return entry.result
  }

  /** Phase 4.2.2: Store a successful tool result in the degraded cache.
   *  Called automatically by callTool on success. Resets hit count on
   *  each fresh write (blocker 7). */
  private cacheToolResult(toolName: string, result: ToolResult): void {
    if (result.success) {
      this.degradedToolCache.set(toolName, {
        result,
        timestamp: Date.now(),
        hitCount: 0,
      })
    }
  }

  /** Reset circuit breaker — called after cooldown or manual recovery */
  resetCircuitBreaker(): void {
    this.circuitFailures = 0
    this.circuitOpenUntil = 0
    this.setLLMStatus("AVAILABLE")
  }

  /** Set the local tool registry snapshot for drift comparison.
   *  Without this, quickDriftCheck would compare MCP against itself. */
  setRegistryTools(tools: ToolDefinition[]): void {
    this.toolsCache = tools
  }

  /** Lightweight drift check: compares a hash of (tool names + capability sets).
   *  Returns true if MCP and registry are in sync. Returns false on mismatch,
   *  at which point callers should run the full detectDrift() for details.
   *  Hash includes capability sets so a tool that changes capabilities without
   *  changing its name is still detected.
   */
  async quickDriftCheck(): Promise<boolean> {
    const { createHash } = await import("crypto")
    // Use the separate MCP tools cache so setRegistryTools() is not overwritten
    const mcpTools = this._toolsEverFetched ? this._mcpToolsCache : await this.getTools()
    const regTools = this.toolsCache

    const nameAndCaps = (t: ToolDefinition): string =>
      `${t.name}:${[...(t.capabilities ?? [])].sort().join(",")}`

    // Compare only dispatchable tools, on both sides. A tool the worker reports
    // as unrunnable is not something the registry needs to agree about, so it
    // is excluded from the MCP list *and* from the registry list — otherwise
    // this check never returned true and every fifth phase paid for a full
    // detectDrift().
    const mcpBlocked = new Set(
      mcpTools.filter((t) => t.disabled || t.available === false).map((t) => t.name),
    )
    const mcpKey = mcpTools
      .filter((t) => !mcpBlocked.has(t.name))
      .map(nameAndCaps)
      .sort()
      .join("|")
    const regKey = regTools
      .filter((t) => !mcpBlocked.has(t.name))
      .map(nameAndCaps)
      .sort()
      .join("|")

    const mcpHash = createHash("sha256").update(mcpKey).digest("hex")
    const regHash = createHash("sha256").update(regKey).digest("hex")

    return mcpHash === regHash
  }

  async detectDrift(): Promise<DriftReport> {
    const mcpTools = await this.getTools()
    const mcpNames = new Set(mcpTools.map((t) => t.name))
    const registryNames = new Set(this.toolsCache.map((t) => t.name))

    // A tool the worker reports as disabled is not drift: it is a tool the
    // worker itself refuses to run, so there is nothing for the planner to
    // agree with. Without this the report permanently listed every in-process
    // pipeline step (attack-graph, report-generator, the post-exploitation
    // trio) as "missing from the registry", burying the real mismatches.
    const dispatchable = mcpTools.filter((t) => !t.disabled && t.available !== false)

    // Detect capability gaps: tools that exist in both but have different capability sets
    const capabilityGaps: string[] = []
    for (const mcpTool of dispatchable) {
      const regTool = this.toolsCache.find((t) => t.name === mcpTool.name)
      if (regTool && JSON.stringify([...(mcpTool.capabilities ?? [])].sort()) !== JSON.stringify([...(regTool.capabilities ?? [])].sort())) {
        capabilityGaps.push(`${mcpTool.name}: MCP=${JSON.stringify(mcpTool.capabilities)} vs registry=${JSON.stringify(regTool.capabilities)}`)
      }
    }

    return {
      missing_from_registry: dispatchable.filter((t) => !registryNames.has(t.name)).map((t) => t.name),
      missing_from_mcp: this.toolsCache.filter((t) => !mcpNames.has(t.name)).map((t) => t.name),
      capability_gaps: capabilityGaps,
    }
  }

  async agentInit(params: {
    target: string
    phase: string
    techStack?: string[]
    pipeline?: any[]
    context?: Record<string, any>
    engagementId?: string
    /**
     * The model the Python worker should use. Supplied by the planner so one
     * run uses one model — the worker has no provider registry of its own.
     *
     * `openai-compatible` is called directly by the worker with `apiKey`;
     * `opencode-server` asks the local OpenCode server to make the call, which
     * is the only way to reach `opencode*` gateways (blocker B9).
     *
     * Never logged: the direct form carries an API key.
     */
    llm?:
      | {
          provider: "openai-compatible"
          providerID: string
          model: string
          apiKey: string
          baseUrl: string
        }
      | {
          provider: "opencode-server"
          providerID: string
          modelID: string
          baseUrl: string
          directory: string
        }
  }): Promise<{ session_id: string; plan: string[]; reasoning: string; phase: string; hypotheses?: Array<{ id: string; description: string; confidence: number; status: string }> }> {
    return this.sendRequest("agent_init", params, AGENT_PLANNING_TIMEOUT_MS) as Promise<{ session_id: string; plan: string[]; reasoning: string; phase: string; hypotheses?: Array<{ id: string; description: string; confidence: number; status: string }> }>
  }

  async agentNext(params: {
    session_id: string
    trigger?: "stuck" | "new_finding" | "phase_complete"
    /** Max iterations for this agent session — TS caps the Python loop (blocker 32). */
    max_iterations?: number
  }): Promise<{ tool?: string; session_id: string; reasoning: string; done: boolean }> {
    return this.sendRequest("agent_next", params, AGENT_PLANNING_TIMEOUT_MS) as Promise<{ tool?: string; session_id: string; reasoning: string; done: boolean }>
  }

  async agentObserve(params: {
    session_id: string
    tool: string
    arguments?: Record<string, string>
    reasoning?: string
    success: boolean
    durationMs?: number
    findingCount?: number
    summary?: string
  }): Promise<{ tool?: string; session_id: string; reasoning: string; done: boolean }> {
    return this.sendRequest("agent_observe", params, AGENT_PLANNING_TIMEOUT_MS) as Promise<{ tool?: string; session_id: string; reasoning: string; done: boolean }>
  }

  /**
   * Fetch the attack graph for an engagement from the Python MCP worker.
   * Returns detected chains, highest-risk paths, and chain-derived phase plans
   * that the TypeScript planner can use to insert exploitation phases.
   */
  async getAttackGraph(params: {
    engagement_id: string
    findings?: any[]
  }): Promise<{
    chains: Array<{
      chain_id: string
      name: string
      severity: string
      correlation_factor: number
      prerequisite_type: string
      chain_type: string
      description: string
    }>
    paths: any[]
    chain_plans: Array<{
      chain_id: string
      name: string
      severity: string
      risk_score: number
      prerequisite_finding_types: string[]
      suggested_capabilities: string[]
      description: string
    }>
  }> {
    return this.sendRequest("get_attack_graph", params) as Promise<any>
  }

  /**
   * Fetch the full attack graph snapshot for frontend visualization.
   *
   * Returns the complete `to_snapshot_dict()` output enriched with chain
   * metadata (chain_id, chain_name per path) and summary statistics.
   * Designed for the AttackGraphVisualizer component.
   */
  async getAttackGraphSnapshot(params: {
    engagement_id: string
    findings?: any[]
  }): Promise<{
    paths: Array<{
      risk_score: number
      nodes: Array<{
        id: string
        type: "vulnerability" | "endpoint"
        data: Record<string, any>
        cvss: number | null
        confidence: number | null
        prerequisites: string[]
        downstream_impacts: string[]
      }>
      edges: Array<{
        from_node: string
        to_node: string
        type: string
        correlation_factor: number
        relationship_type: string
      }>
      chain_id?: string
      chain_name?: string
    }>
    metadata: {
      totalPaths: number
      totalFindings: number
      highestRiskScore: number
      chainsDetected: number
    }
  }> {
    return this.sendRequest("get_attack_graph_snapshot", params) as Promise<any>
  }

  /** Phase 4.1.4: Get completed tool list for a given phase (for checkpoint resume). */
  async getCheckpoint(engagementId: string, phase: string): Promise<{ completed_tools: string[] }> {
    return this.sendRequest("get_checkpoint", { engagement_id: engagementId, phase }) as Promise<{ completed_tools: string[] }>
  }

  /** Phase 4.4.1: Acquire a distributed lock for an engagement via MCP. */
  async acquireEngagementLock(engagementId: string): Promise<{ acquired: boolean }> {
    return this.sendRequest("acquire_lock", { engagement_id: engagementId }) as Promise<{ acquired: boolean }>
  }

  /** Phase 4.4.1: Release a distributed lock for an engagement via MCP. */
  async releaseEngagementLock(engagementId: string): Promise<{ released: boolean }> {
    return this.sendRequest("release_lock", { engagement_id: engagementId }) as Promise<{ released: boolean }>
  }

  /**
   * Cancel the current ReActAgent session for an engagement (blocker 38).
   * This propagates the stop signal from TypeScript to the Python agent
   * so it stops mid-execution instead of continuing until the next iteration.
   */
  async cancelAgent(engagementId: string, sessionId?: string): Promise<{ cancelled: boolean; error?: string }> {
    return this.sendRequest("cancel", { engagement_id: engagementId, session_id: sessionId }) as Promise<{ cancelled: boolean; error?: string }>
  }

  /**
   * Signal phase completion to the Python MCP worker (Phase 1.2 — LLM-Driven Replanning).
   *
   * After each phase completes, the workflow-runner sends all accumulated findings
   * so the LLM can analyze them and suggest the next capabilities to run. This
   * closes the feedback loop from findings to tool selection.
   *
   * @param params.engagement_id - The engagement UUID.
   * @param params.phase - The phase that just completed.
   * @param params.target - The assessment target.
   * @param params.findings - All findings accumulated so far.
   * @returns Suggested next capabilities and whether to stop the assessment.
   */
  async phaseComplete(params: {
    engagement_id: string
    phase: string
    target: string
    findings: any[]
  }): Promise<{
    next_capabilities: string[]
    reasoning: string
    stop: boolean
    fallback?: boolean  // true when LLM was unavailable (blocker 16)
  }> {
    return this.sendRequest("phase_complete", params) as Promise<{
      next_capabilities: string[]
      reasoning: string
      stop: boolean
      fallback?: boolean
    }>
  }

  async disconnect(): Promise<void> {
    this._disconnecting = true
    this.supervisor.cancelRecovery()
    this.supervisor.resetAttempts()
    this.killChild()
    this.cleanup()
  }
}

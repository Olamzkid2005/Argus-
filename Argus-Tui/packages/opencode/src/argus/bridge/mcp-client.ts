import { spawn, ChildProcess } from "child_process"
import { createInterface } from "readline"
import { accessSync, constants } from "fs"
import type { ToolDefinition, ToolResult, MCPError, DriftReport } from "./types"
import { LLMUnavailableError } from "./types"
import { WorkerSupervisor } from "./supervisor"

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

export class WorkersBridge {
  private process: ChildProcess | null = null
  private rl: ReturnType<typeof createInterface> | null = null
  private pending = new Map<string, PendingRequest>()
  private requestId = 0
  public supervisor: WorkerSupervisor
  private toolsCache: ToolDefinition[] = []
  private _llmStatus: LLMStatus = "AVAILABLE"
  private statusListeners: Array<(status: string) => void> = []

  private pendingCount = 0
  private readonly maxPending = 10

  // Circuit breaker state
  private circuitFailures = 0
  private readonly circuitThreshold = 3
  private circuitOpenUntil = 0
  private readonly circuitCooldown = 300_000 // 5 minutes

  // Signal forwarding state
  private signalHandlers: Array<{ signal: NodeJS.Signals; handler: () => void }> = []
  private forwardingEnabled = false

  constructor(
    private workersPath: string,
    private pythonPath: string = "python3",
  ) {
    this.supervisor = new WorkerSupervisor({
      killChild: () => this.killChild(),
      connect: () => this.connect(),
      isHealthy: () => this.isHealthy(),
    })
  }

  private validatePaths(): void {
    const VALID_PYTHON = new Set(["python3", "python"])
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
  }

  private cleanup(): void {
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
    this.process = spawn(this.pythonPath, [this.workersPath], {
      stdio: ["pipe", "pipe", "pipe"],
    })

    this.rl = createInterface({
      input: this.process.stdout!,
    })

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
        // Ignore malformed JSON lines
      }
    })

    this.process.on("exit", (code) => {
      this.setLLMStatus("UNAVAILABLE")
      // Reject all pending requests — process is gone
      for (const [id, pending] of this.pending) {
        clearTimeout(pending.timer)
        pending.reject(new Error(`Process exited with code ${code}`))
      }
      this.pending.clear()
      this.pendingCount = 0
    })

    this.process.stderr?.on("data", (data: Buffer) => {
      process.stderr.write(`[MCP Worker] ${data.toString()}`)
    })

    await this.waitForReady()
    this.toolsCache = await this.getTools()
  }

  killChild(): void {
    const proc = this.process
    if (proc && !proc.killed && proc.exitCode === null) {
      proc.kill("SIGTERM")
      setTimeout(() => {
        if (proc && !proc.killed && proc.exitCode === null) {
          proc.kill("SIGKILL")
        }
      }, 3000)
    }
  }

  async restartWorker(): Promise<void> {
    this.supervisor.resetAttempts()
    await this.supervisor.restartWorker()
  }

  async isHealthy(): Promise<boolean> {
    try {
      const result = await this.sendRequest("ping", {})
      return result === "pong"
    } catch {
      return false
    }
  }

  private async waitForReady(timeoutMs = 10000): Promise<void> {
    const start = Date.now()
    let delay = 200
    while (Date.now() - start < timeoutMs) {
      if (await this.isHealthy()) return
      await new Promise((r) => setTimeout(r, delay))
      delay = Math.min(delay * 2, 1600)
    }
    throw new Error("MCP worker failed to become ready")
  }

  private async sendRequest(method: string, params?: unknown): Promise<unknown> {
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
          reject(new Error(`Request ${method} timed out`))
        }, 30000)

        this.pending.set(id, { resolve, reject, timer })

        if (!this.process || this.process.exitCode !== null || this.process.killed) {
          clearTimeout(timer)
          this.pending.delete(id)
          reject(new Error("Process not running"))
          return
        }
        this.process.stdin!.write(JSON.stringify(request) + "\n")
      })
    } finally {
      this.pendingCount--
    }
  }

  async callTool(name: string, args: unknown): Promise<ToolResult> {
    // Circuit breaker check
    const now = Date.now()
    if (this.circuitOpenUntil > now) {
      const retryAfter = Math.ceil((this.circuitOpenUntil - now) / 1000)
      throw new LLMUnavailableError("UNAVAILABLE", retryAfter)
    }

    try {
      const result = await this.sendRequest("call_tool", { name, arguments: args })
      // Success — reset circuit breaker
      if (this.circuitFailures > 0) {
        this.circuitFailures = 0
        this.setLLMStatus("AVAILABLE")
      }
      return result as ToolResult
    } catch (error) {
      const isLLMError = (error as any)?.code === -32000 || (error as Error).message.includes("LLM is not available")

      if (isLLMError) {
        this.circuitFailures++
        if (this.circuitFailures >= this.circuitThreshold) {
          this.circuitOpenUntil = now + this.circuitCooldown
          this.setLLMStatus("UNAVAILABLE")
          throw new LLMUnavailableError("UNAVAILABLE", Math.ceil(this.circuitCooldown / 1000))
        }
        this.setLLMStatus("DEGRADED")
        throw new LLMUnavailableError("DEGRADED", 30)
      }
      throw error
    }
  }

  async getTools(): Promise<ToolDefinition[]> {
    try {
      const result = await this.sendRequest("list_tools", {})
      return result as ToolDefinition[]
    } catch {
      return this.toolsCache
    }
  }

  /** Reset circuit breaker — called after cooldown or manual recovery */
  resetCircuitBreaker(): void {
    this.circuitFailures = 0
    this.circuitOpenUntil = 0
    this.setLLMStatus("AVAILABLE")
  }

  /** Lightweight drift check: compares a hash of (tool names + capability sets).
   *  Returns true if MCP and registry are in sync. Returns false on mismatch,
   *  at which point callers should run the full detectDrift() for details.
   *  Hash includes capability sets so a tool that changes capabilities without
   *  changing its name is still detected.
   */
  async quickDriftCheck(): Promise<boolean> {
    const { createHash } = await import("crypto")
    const mcpTools = await this.getTools()

    const mcpKey = mcpTools
      .map((t) => `${t.name}:${[...(t.capabilities ?? [])].sort().join(",")}`)
      .sort()
      .join("|")
    const regKey = this.toolsCache
      .map((t) => `${t.name}:${[...(t.capabilities ?? [])].sort().join(",")}`)
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

    // Detect capability gaps: tools that exist in both but have different capability sets
    const capabilityGaps: string[] = []
    for (const mcpTool of mcpTools) {
      const regTool = this.toolsCache.find((t) => t.name === mcpTool.name)
      if (regTool && JSON.stringify([...(mcpTool.capabilities ?? [])].sort()) !== JSON.stringify([...(regTool.capabilities ?? [])].sort())) {
        capabilityGaps.push(`${mcpTool.name}: MCP=${JSON.stringify(mcpTool.capabilities)} vs registry=${JSON.stringify(regTool.capabilities)}`)
      }
    }

    return {
      missing_from_registry: mcpTools.filter((t) => !registryNames.has(t.name)).map((t) => t.name),
      missing_from_mcp: this.toolsCache.filter((t) => !mcpNames.has(t.name)).map((t) => t.name),
      capability_gaps: capabilityGaps,
    }
  }

  async disconnect(): Promise<void> {
    this.killChild()
    this.cleanup()
  }
}

/**
 * Tool Health Monitor — Circuit breaker for MCP tool calls.
 *
 * Tracks tool execution health and opens a circuit after N consecutive
 * failures. The executor checks isHealthy() before calling any tool.
 * If a tool is circuit-broken, the LLM is informed about alternatives.
 */

export interface ToolHealthRecord {
  toolName: string
  lastSuccess: number
  lastFailure: number
  consecutiveFailures: number
  totalCalls: number
  totalFailures: number
  avgDurationMs: number
  circuitOpen: boolean
  circuitOpenedAt?: number
}

export interface ToolHealthConfig {
  maxConsecutiveFailures: number
  cooldownMs: number
}

const DEFAULT_CONFIG: ToolHealthConfig = {
  maxConsecutiveFailures: 5,
  cooldownMs: 300_000,
}

export class ToolHealthMonitor {
  private records = new Map<string, ToolHealthRecord>()
  private config: ToolHealthConfig

  constructor(config?: Partial<ToolHealthConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config }
  }

  recordSuccess(tool: string, durationMs: number): void {
    const r = this.getOrCreate(tool)
    r.lastSuccess = Date.now()
    r.consecutiveFailures = 0
    r.totalCalls++
    r.avgDurationMs = this.calculateNewAvg(r.avgDurationMs, r.totalCalls, durationMs)
    if (r.circuitOpen) {
      r.circuitOpen = false
      r.circuitOpenedAt = undefined
    }
  }

  recordFailure(tool: string, error: string): void {
    const r = this.getOrCreate(tool)
    r.lastFailure = Date.now()
    r.consecutiveFailures++
    r.totalCalls++
    r.totalFailures++

    if (r.consecutiveFailures >= this.config.maxConsecutiveFailures && !r.circuitOpen) {
      r.circuitOpen = true
      r.circuitOpenedAt = Date.now()
    }
  }

  isHealthy(tool: string): boolean {
    const r = this.records.get(tool)
    if (!r) return true

    if (r.circuitOpen) {
      const cooldownElapsed = Date.now() - (r.circuitOpenedAt ?? 0)
      if (cooldownElapsed >= this.config.cooldownMs) {
        r.circuitOpen = false
        r.circuitOpenedAt = undefined
        r.consecutiveFailures = 0
        return true
      }
      return false
    }

    return true
  }

  getStatus(): ToolHealthRecord[] {
    return [...this.records.values()]
  }

  getToolStatus(tool: string): ToolHealthRecord | undefined {
    return this.records.get(tool)
  }

  getUnhealthyTools(): string[] {
    return [...this.records.entries()]
      .filter(([_, r]) => r.circuitOpen)
      .map(([name]) => name)
  }

  resetAll(): void {
    for (const r of this.records.values()) {
      r.circuitOpen = false
      r.circuitOpenedAt = undefined
      r.consecutiveFailures = 0
    }
  }

  reset(tool: string): void {
    const r = this.records.get(tool)
    if (r) {
      r.circuitOpen = false
      r.circuitOpenedAt = undefined
      r.consecutiveFailures = 0
    }
  }

  private getOrCreate(tool: string): ToolHealthRecord {
    let r = this.records.get(tool)
    if (!r) {
      r = {
        toolName: tool,
        lastSuccess: 0,
        lastFailure: 0,
        consecutiveFailures: 0,
        totalCalls: 0,
        totalFailures: 0,
        avgDurationMs: 0,
        circuitOpen: false,
      }
      this.records.set(tool, r)
    }
    return r
  }

  private calculateNewAvg(currentAvg: number, newCount: number, newValue: number): number {
    return currentAvg + (newValue - currentAvg) / newCount
  }
}

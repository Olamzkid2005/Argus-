/**
 * Tool Health Monitor — Circuit breaker for MCP tool calls.
 *
 * Tracks tool execution health and opens a circuit after N consecutive
 * failures. The executor checks isHealthy() before calling any tool.
 * If a tool is circuit-broken, the LLM is informed about alternatives.
 */

import type { ErrorHintData } from "../shared/progress"

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
  /**
   * Half-open state: cooldown has expired and one probe call is in flight.
   * Only a single test call is allowed in this state. On success the circuit
   * closes; on failure it re-opens with a fresh cooldown.
   */
  halfOpen: boolean
  /** Timestamp when half-open state was entered (for timeout). */
  _halfOpenStartedAt?: number
  /**
   * Accumulated active execution time (ms) since the circuit opened.
   * Used instead of wall-clock time for cooldown checks (blocker 58).
   * Increases only when tools are actually running, not during idle periods.
   */
  activeDurationMsSinceOpen: number
}

export interface ToolHealthConfig {
  maxConsecutiveFailures: number
  cooldownMs: number
}

// Blocker 22: Must stay in sync with tool-config.ts DEFAULT_CIRCUIT_BREAKER.
// The executor always passes explicit config, so this is only a fallback
// for tests and direct ToolHealthMonitor construction.
const DEFAULT_CONFIG: ToolHealthConfig = {
  maxConsecutiveFailures: 8,
  cooldownMs: 120_000,
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
    // Note: activeDurationMsSinceOpen is NOT reset here — it's tracked
    // independently so cooldown checks (isHealthy) work correctly.
    if (r.halfOpen) {
      // Half-open probe succeeded → close circuit
      r.halfOpen = false
      r.circuitOpen = false
      r.circuitOpenedAt = undefined
      r.activeDurationMsSinceOpen = 0
    } else if (r.circuitOpen) {
      // Shouldn't happen on success, but belt-and-suspenders
      r.circuitOpen = false
      r.circuitOpenedAt = undefined
      r.activeDurationMsSinceOpen = 0
    }
  }

  /** Callback invoked when a failure includes an error hint. */
  onErrorHint?: (hint: ErrorHintData) => void

  recordFailure(tool: string, error: string, hint?: ErrorHintData, durationMs?: number): void {
    const r = this.getOrCreate(tool)
    r.lastFailure = Date.now()
    r.consecutiveFailures++
    r.totalCalls++
    r.totalFailures++

    if (durationMs !== undefined) {
      r.activeDurationMsSinceOpen += durationMs
    }

    if (hint) {
      this.onErrorHint?.(hint)
    }

    if (r.halfOpen) {
      // Half-open probe failed → re-open with fresh cooldown
      r.halfOpen = false
      r.circuitOpen = true
      r.circuitOpenedAt = Date.now()
      // Reset active-time counter since we're starting a fresh cooldown
      r.activeDurationMsSinceOpen = durationMs ?? 0
    } else if (r.consecutiveFailures >= this.config.maxConsecutiveFailures && !r.circuitOpen) {
      r.circuitOpen = true
      r.circuitOpenedAt = Date.now()
      r.activeDurationMsSinceOpen = 0
    }
  }

  /** Max time (ms) to stay half-open before reverting to open if no probe completes. */
  private static readonly HALF_OPEN_TIMEOUT_MS = 60_000

  isHealthy(tool: string): boolean {
    const r = this.records.get(tool)
    if (!r) return true

    if (r.circuitOpen) {
      // Check active-time-based cooldown (blocker 58).
      // Instead of wall-clock time, we check accumulated active execution
      // time since the circuit opened. This prevents quick retries when
      // the system was idle the whole time.
      const activeCooldownElapsed = r.activeDurationMsSinceOpen >= this.config.cooldownMs
      const wallCooldownElapsed = Date.now() - (r.circuitOpenedAt ?? 0) >= this.config.cooldownMs

      // Use whichever elapses first — if wall clock has passed AND some
      // active time has accumulated, transition to half-open.
      const cooldownExpired = wallCooldownElapsed || activeCooldownElapsed

      if (cooldownExpired && !r.halfOpen) {
        // Transition to HALF-OPEN: allow one probe call.
        // Don't reset consecutiveFailures yet — that happens on probe success.
        r.halfOpen = true
        r.circuitOpenedAt = undefined  // Clear for fresh timing on re-open
        r._halfOpenStartedAt = Date.now()
        return true
      }

      if (r.halfOpen) {
        // Check if half-open has timed out (probe call was never made).
        // This prevents permanent stall if the caller checks isHealthy()
        // but never actually runs the tool (e.g., LLM error).
        if (r._halfOpenStartedAt && Date.now() - r._halfOpenStartedAt > ToolHealthMonitor.HALF_OPEN_TIMEOUT_MS) {
          r.halfOpen = false
          r._halfOpenStartedAt = undefined
          r.circuitOpen = true
          r.circuitOpenedAt = Date.now()
          return false
        }
        // Half-open and someone already took the probe — reject until
        // the probe completes (recordSuccess or recordFailure will resolve it).
        return false
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
      r.halfOpen = false
      r._halfOpenStartedAt = undefined
      r.consecutiveFailures = 0
      r.activeDurationMsSinceOpen = 0
    }
  }

  reset(tool: string): void {
    const r = this.records.get(tool)
    if (r) {
      r.circuitOpen = false
      r.circuitOpenedAt = undefined
      r.halfOpen = false
      r._halfOpenStartedAt = undefined
      r.consecutiveFailures = 0
      r.activeDurationMsSinceOpen = 0
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
      halfOpen: false,
      _halfOpenStartedAt: undefined,
      activeDurationMsSinceOpen: 0,
      }
      this.records.set(tool, r)
    }
    return r
  }

  private calculateNewAvg(currentAvg: number, newCount: number, newValue: number): number {
    return currentAvg + (newValue - currentAvg) / newCount
  }
}

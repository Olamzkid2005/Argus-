export class WorkerSupervisor {
  private attempts = 0
  private readonly maxRestarts = 3
  /** Phase 4.2.1: When true, the worker is in degraded mode (max restarts exceeded).
   *  Callers should use cached tools and avoid critical operations. */
  private _degraded = false

  /** Cooldown before attempting recovery from degraded mode (default 60s). */
  private readonly degradedRecoveryCooldownMs: number

  /** Timestamp when degraded mode was entered — used to schedule recovery attempts. */
  private degradedAt = 0

  /** Timer handle for the scheduled recovery attempt. */
  private _recoveryTimer: ReturnType<typeof setTimeout> | null = null

  constructor(private callbacks: {
    killChild: () => void
    connect: () => Promise<void>
    isHealthy: () => Promise<boolean>
  }, private backoffMs: number = 1000) {
    this.degradedRecoveryCooldownMs = (() => {
      const raw = process.env.ARGUS_DEGRADED_RECOVERY_COOLDOWN_MS
      if (raw === undefined || raw === "") return 60_000
      const n = Number(raw)
      return Number.isFinite(n) && n >= 1000 ? n : 60_000
    })()
  }

  /** Whether the worker is operating in degraded mode.
   *  Phase 4.2.1: Set to true after max restarts exceeded. */
  get degraded(): boolean {
    return this._degraded
  }

  async restartWorker(): Promise<void> {
    if (this.attempts >= this.maxRestarts) {
      // Phase 4.2.1: Enter degraded mode so callers can continue
      // with cached data and avoid critical tool calls.
      // Schedule a recovery attempt after the cooldown period.
      this._enterDegraded()
      return
    }
    this.attempts++
    this.callbacks.killChild()
    // Exponential backoff: base, base*2, base*4
    await new Promise(r => setTimeout(r, this.backoffMs * Math.pow(2, this.attempts - 1)))
    try {
      await this.callbacks.connect()
      this.attempts = 0
    } catch (err) {
      // If connect fails, allow subsequent restart attempts
      // to retry — attempts already incremented, so the next
      // call uses the next backoff tier.
      throw err
    }
  }

  /** Enter degraded mode and schedule a recovery attempt after the cooldown. */
  private _enterDegraded(): void {
    if (this._degraded) return // already degraded
    this._degraded = true
    this.degradedAt = Date.now()
    this._scheduleRecovery()
  }

  /** Schedule a single recovery attempt after the cooldown period.
   *  Only one recovery timer is active at a time — subsequent calls
   *  are no-ops until the current recovery resolves. */
  private _scheduleRecovery(): void {
    if (this._recoveryTimer) return // recovery already scheduled
    this._recoveryTimer = setTimeout(async () => {
      this._recoveryTimer = null
      try {
        // Before attempting recovery, check if the worker has already
        // been recovered by another path (e.g. manual reset).
        if (!this._degraded) return
        await this._attemptRecovery()
      } catch {
        // Recovery attempt failed — stay in degraded mode.
        // Schedule another recovery after the cooldown.
        this._scheduleRecovery()
      }
    }, this.degradedRecoveryCooldownMs)
    // Don't let the timer keep the process alive
    if (this._recoveryTimer && typeof this._recoveryTimer === "object" && "unref" in this._recoveryTimer) {
      this._recoveryTimer.unref()
    }
  }

  /** Attempt to recover from degraded mode by killing the old child
   *  and attempting a fresh connect. On success, resets attempts
   *  and exits degraded mode. On failure, stays degraded. */
  private async _attemptRecovery(): Promise<void> {
    this.callbacks.killChild()
    // Fixed backoff for recovery (not exponential — recovery is infrequent)
    await new Promise(r => setTimeout(r, 2_000))
    try {
      await this.callbacks.connect()
      // Recovery succeeded — clear degraded state
      this.attempts = 0
      this._degraded = false
      this.degradedAt = 0
    } catch {
      // Recovery failed — will be re-scheduled by _scheduleRecovery
      throw new Error("recovery connect failed")
    }
  }

  /** Cancel any pending recovery attempt (e.g., on clean disconnect). */
  cancelRecovery(): void {
    if (this._recoveryTimer) {
      clearTimeout(this._recoveryTimer)
      this._recoveryTimer = null
    }
  }

  isHealthy(): Promise<boolean> {
    return this.callbacks.isHealthy()
  }

  resetAttempts(): void {
    this.attempts = 0
    this._degraded = false
    this.degradedAt = 0
    this.cancelRecovery()
  }

  attemptsRemaining(): number {
    return this.maxRestarts - this.attempts
  }
}

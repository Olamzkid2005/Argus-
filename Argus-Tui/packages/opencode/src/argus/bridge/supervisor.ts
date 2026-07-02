export class WorkerSupervisor {
  private attempts = 0
  private readonly maxRestarts = 3
  /** Phase 4.2.1: When true, the worker is in degraded mode (max restarts exceeded).
   *  Callers should use cached tools and avoid critical operations. */
  private _degraded = false

  constructor(private callbacks: {
    killChild: () => void
    connect: () => Promise<void>
    isHealthy: () => Promise<boolean>
  }, private backoffMs: number = 1000) {}

  /** Whether the worker is operating in degraded mode.
   *  Phase 4.2.1: Set to true after max restarts exceeded. */
  get degraded(): boolean {
    return this._degraded
  }

  async restartWorker(): Promise<void> {
    if (this.attempts >= this.maxRestarts) {
      // Phase 4.2.1: Instead of throwing, signal degraded mode so callers
      // can continue with cached data and avoid critical tool calls.
      this._degraded = true
      return
    }
    this.attempts++
    this.callbacks.killChild()
    // Exponential backoff: base, base*2, base*4
    await new Promise(r => setTimeout(r, this.backoffMs * Math.pow(2, this.attempts - 1)))
    await this.callbacks.connect()
    this.attempts = 0
  }

  isHealthy(): Promise<boolean> {
    return this.callbacks.isHealthy()
  }

  resetAttempts(): void {
    this.attempts = 0
    this._degraded = false
  }

  attemptsRemaining(): number {
    return this.maxRestarts - this.attempts
  }
}

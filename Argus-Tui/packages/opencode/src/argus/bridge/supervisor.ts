export class WorkerSupervisor {
  private attempts = 0
  private readonly maxRestarts = 3

  constructor(private callbacks: {
    killChild: () => void
    connect: () => Promise<void>
    isHealthy: () => Promise<boolean>
  }, private backoffMs: number = 1000) {}

  async restartWorker(): Promise<void> {
    if (this.attempts >= this.maxRestarts) {
      throw new Error("Worker crashed too many times — falling back to deterministic mode")
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
  }

  attemptsRemaining(): number {
    return this.maxRestarts - this.attempts
  }
}

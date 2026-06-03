export class WorkerSupervisor {
  private attempts = 0
  private readonly maxRestarts = 3

  constructor(private bridge: {
    restartWorker: () => Promise<void>
    killChild: () => void
    connect: () => Promise<void>
    isHealthy: () => Promise<boolean>
  }) {}

  async restartWorker(): Promise<void> {
    if (this.attempts >= this.maxRestarts) {
      throw new Error("Worker crashed too many times — falling back to deterministic mode")
    }
    this.attempts++
    this.bridge.killChild()
    await this.bridge.connect()
  }

  isHealthy(): Promise<boolean> {
    return this.bridge.isHealthy()
  }

  resetAttempts(): void {
    this.attempts = 0
  }

  attemptsRemaining(): number {
    return this.maxRestarts - this.attempts
  }
}

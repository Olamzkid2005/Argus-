export declare class WorkerSupervisor {
    private callbacks;
    private backoffMs;
    private attempts;
    private readonly maxRestarts;
    /** Phase 4.2.1: When true, the worker is in degraded mode (max restarts exceeded).
     *  Callers should use cached tools and avoid critical operations. */
    private _degraded;
    /** Cooldown before attempting recovery from degraded mode (default 60s). */
    private readonly degradedRecoveryCooldownMs;
    /** Timestamp when degraded mode was entered — used to schedule recovery attempts. */
    private degradedAt;
    /** Timer handle for the scheduled recovery attempt. */
    private _recoveryTimer;
    constructor(callbacks: {
        killChild: () => void;
        connect: () => Promise<void>;
        isHealthy: () => Promise<boolean>;
    }, backoffMs?: number);
    /** Whether the worker is operating in degraded mode.
     *  Phase 4.2.1: Set to true after max restarts exceeded. */
    get degraded(): boolean;
    restartWorker(): Promise<void>;
    /** Enter degraded mode and schedule a recovery attempt after the cooldown. */
    private _enterDegraded;
    /** Schedule a single recovery attempt after the cooldown period.
     *  Only one recovery timer is active at a time — subsequent calls
     *  are no-ops until the current recovery resolves. */
    private _scheduleRecovery;
    private _attemptRecovery;
    /** Cancel any pending recovery attempt (e.g., on clean disconnect). */
    cancelRecovery(): void;
    isHealthy(): Promise<boolean>;
    resetAttempts(): void;
    attemptsRemaining(): number;
}

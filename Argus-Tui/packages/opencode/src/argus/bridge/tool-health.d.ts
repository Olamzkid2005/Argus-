/**
 * Tool Health Monitor — Circuit breaker for MCP tool calls.
 *
 * Tracks tool execution health and opens a circuit after N consecutive
 * failures. The executor checks isHealthy() before calling any tool.
 * If a tool is circuit-broken, the LLM is informed about alternatives.
 */
import type { ErrorHintData } from "../shared/progress";
export interface ToolHealthRecord {
    toolName: string;
    lastSuccess: number;
    lastFailure: number;
    consecutiveFailures: number;
    totalCalls: number;
    totalFailures: number;
    avgDurationMs: number;
    circuitOpen: boolean;
    circuitOpenedAt?: number;
    /**
     * Half-open state: cooldown has expired and one probe call is in flight.
     * Only a single test call is allowed in this state. On success the circuit
     * closes; on failure it re-opens with a fresh cooldown.
     */
    halfOpen: boolean;
    /** Timestamp when half-open state was entered (for timeout). */
    _halfOpenStartedAt?: number;
    /**
     * Accumulated active execution time (ms) since the circuit opened.
     * Used instead of wall-clock time for cooldown checks (blocker 58).
     * Increases only when tools are actually running, not during idle periods.
     */
    activeDurationMsSinceOpen: number;
}
export interface ToolHealthConfig {
    maxConsecutiveFailures: number;
    cooldownMs: number;
}
export declare class ToolHealthMonitor {
    private records;
    private config;
    constructor(config?: Partial<ToolHealthConfig>);
    recordSuccess(tool: string, durationMs: number): void;
    /** Callback invoked when a failure includes an error hint. */
    onErrorHint?: (hint: ErrorHintData) => void;
    recordFailure(tool: string, error: string, hint?: ErrorHintData, durationMs?: number): void;
    /** Max time (ms) to stay half-open before reverting to open if no probe completes. */
    private static readonly HALF_OPEN_TIMEOUT_MS;
    isHealthy(tool: string): boolean;
    getStatus(): ToolHealthRecord[];
    getToolStatus(tool: string): ToolHealthRecord | undefined;
    getUnhealthyTools(): string[];
    resetAll(): void;
    reset(tool: string): void;
    private getOrCreate;
    private calculateNewAvg;
}

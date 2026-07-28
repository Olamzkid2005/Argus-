import type { PhaseExecutionRequest, PhaseExecutionResult, NormalizedFinding } from "./types";
import { ToolRegistry } from "../workflows/tool-registry";
import type { CacheMode } from "../bridge/types";
import type { WorkersBridge } from "../bridge/mcp-client";
import type { ProgressEvent } from "../shared/progress";
/**
 * Cross-tool rate limiter — sliding window that limits requests per second
 * across ALL tools targeting a given target (blocker 44).
 * Prevents tools like nuclei (150 req/s) + ffuf (200 req/s) from
 * overloading the target simultaneously.
 *
 * Uses a per-target sliding window. Configured via env var:
 *   ARGUS_CROSS_TOOL_RATE_LIMIT: max requests per window (default 50)
 *   ARGUS_CROSS_TOOL_RATE_WINDOW_MS: window duration in ms (default 1000)
 */
export declare class CrossToolRateLimiter {
    private windows;
    private readonly maxRequests;
    private readonly windowMs;
    constructor();
    /** Acquire a slot for the given target. Returns delay needed (ms), or 0 if allowed. */
    acquire(target: string): number;
    /** Reset all rate limit windows (e.g. between phases). */
    reset(): void;
}
/**
 * Throttle tracker for 429/503 responses (blocker 45).
 * Detects rate-limit errors from tool responses and applies exponential
 * backoff per target before allowing further requests.
 *
 * Configured via env var:
 *   ARGUS_THROTTLE_BASE_DELAY_MS: initial backoff delay (default 2000)
 *   ARGUS_THROTTLE_MAX_DELAY_MS:  maximum backoff delay (default 60000)
 */
export declare class ThrottleTracker {
    private throttledTargets;
    private readonly baseDelayMs;
    private readonly maxDelayMs;
    constructor();
    /** Returns true if the target is currently throttled. */
    isThrottled(target: string): boolean;
    /** Get remaining throttle delay in ms, or 0 if not throttled. */
    getRemainingDelay(target: string): number;
    /**
     * Detect if an error message indicates rate limiting (429/503/etc).
     * Returns true if the error matches known rate-limit patterns.
     */
    static isRateLimitError(errorMessage: string): boolean;
    /**
     * Record a rate-limit hit for the given target.
     * Applies exponential backoff: base * 2^consecutive, capped at max.
     */
    recordThrottle(target: string): void;
    /**
     * Record a successful response for the target (resets backoff).
     */
    recordSuccess(target: string): void;
    /** Reset all throttle state (e.g., between phases). */
    reset(): void;
}
import { ConfidenceEngine } from "../engagement/confidence";
import { WorkflowRegistry } from "../workflows/registry";
import { type FeatureFlags } from "../config/feature-flags";
import { ToolConfig } from "../config/tool-config";
import type { ToolHealthRecord } from "../bridge/tool-health";
export interface ExecutionOptions {
    cacheMode?: CacheMode;
    /**
     * Enable verbose execution logging.
     * When true, the executor emits additional detail about tool selection,
     * timing, and circuit-breaker status via console.log.
     */
    verbose?: boolean;
}
export interface PhaseExecutor {
    execute(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult>;
}
export interface ScopeConfig {
    mode: "allowlist" | "allow_all";
    allowed_targets?: string[];
    blocked_targets?: string[];
}
export declare class InProcessExecutor implements PhaseExecutor {
    private toolRegistry;
    private bridge;
    private confidenceEngine;
    private workflowRegistry?;
    private approvalService;
    private requiredGates;
    private featureFlags;
    private toolConfig;
    private phaseCount;
    private toolHealth;
    private scopeConfig;
    private tempCredFiles;
    setScopeConfig(config: ScopeConfig): void;
    private executionOptions;
    private emitProgress;
    /** Cross-tool rate limiter (blocker 44). */
    private rateLimiter;
    /** Target throttle tracker for 429/503 backoff (blocker 45). */
    private throttleTracker;
    /** Phase-relative max duration per phase (env ARGUS_MAX_PHASE_DURATION_MS, default 30 min). */
    private maxPhaseDurationMs;
    /** Global max assessment duration (env ARGUS_MAX_ASSESSMENT_DURATION_MS, default 2 hours). */
    private maxAssessmentDurationMs;
    private assessmentStartTime;
    /** Per-phase deadline (set at phase start). Used in both execute() and executeHybrid(). */
    private phaseDeadline;
    /** Check if the current phase has exceeded its timeout (blocker 35). */
    private checkPhaseTimeout;
    constructor(toolRegistry: ToolRegistry, bridge: WorkersBridge, confidenceEngine: ConfidenceEngine, workflowRegistry?: WorkflowRegistry | undefined);
    setOnProgress(handler: (event: ProgressEvent) => void): void;
    setExecutionOptions(options: ExecutionOptions): void;
    /**
     * Consume an MCP verification result and cascade confidence promotion.
     * Called from the workflow runner after receiving verification results
     * from the finding_verifier MCP tool.
     *
     * This promotes findings through the full cascade:
     *   MEDIUM → HIGH → VERIFIED → CONFIRMED
     *
     * Each promote() call advances at most one tier, so the while loop is
     * required to reach CONFIRMED in a single pass.
     *
     * @param finding - The finding to promote. Its confidence is updated in-place.
     * @returns The promoted confidence level.
     */
    consumeVerificationResult(finding: NormalizedFinding): number;
    reset(): void;
    getToolHealth(): ToolHealthRecord[];
    setFeatureFlags(flags: FeatureFlags): void;
    setToolConfig(tc: ToolConfig): void;
    /** Check whether a feature is enabled (defaults false if no flag system attached) */
    private isFeatureEnabled;
    private gatesLoaded;
    loadGates(workflowName: string): void;
    execute(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult>;
    executeHybrid(phase: PhaseExecutionRequest, options?: ExecutionOptions): Promise<PhaseExecutionResult>;
    private executeTool;
    /**
     * Build an `extra` JSON string from credentials in the phase config.
     * Tools like login/register use the `--extra` JSON parameter for
     * credential data (email/password), but the executor previously never
     * populated this field — causing "NO_CREDENTIALS" errors.
     *
     * At runtime, credentials are stored as a single CredentialEntry-like
     * object: `{ username, password }` or `{ email, password }`.
     */
    private buildExtraFromCredentials;
    private cleanupCreds;
    private buildCredsFile;
    /**
     * Find a fallback tool when the primary tool is circuit-broken (blocker 6).
     * Looks for another enabled tool that covers the same capability.
     * Skips tools that are also circuit-broken or are the original tool.
     */
    private findFallbackTool;
    private resolveErrorRecovery;
}

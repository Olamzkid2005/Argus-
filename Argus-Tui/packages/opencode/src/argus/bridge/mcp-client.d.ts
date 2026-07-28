import type { ToolDefinition, ToolResult, DriftReport, CacheMode } from "./types";
import { WorkerSupervisor } from "./supervisor";
declare const LLM_STATUS: readonly ["AVAILABLE", "DEGRADED", "UNAVAILABLE"];
type LLMStatus = (typeof LLM_STATUS)[number];
export declare class WorkersBridge {
    private workersPath;
    private pythonPath;
    private process;
    private rl;
    private pending;
    private requestId;
    supervisor: WorkerSupervisor;
    private toolsCache;
    private _mcpToolsCache;
    private _toolsEverFetched;
    private _llmStatus;
    private statusListeners;
    /** Phase 4.2.2: Cache of recent tool results used when the worker is in degraded mode.
     *  Keyed by tool name, stores the last successful result so non-critical operations
     *  can return cached data instead of failing when the MCP worker is unavailable.
     *  Each entry tracks hit count to prevent stale data from being served
     *  indefinitely (blocker 7). */
    private degradedToolCache;
    /** Max age for cached results in degraded mode (5 minutes by default, configurable via ARGUS_DEGRADED_CACHE_TTL_MS). */
    private static get DEGRADED_CACHE_TTL_MS();
    /** Max cache hits before a cached result transitions to stale (default 3). */
    private static readonly DEGRADED_CACHE_MAX_HITS;
    private pendingCount;
    private readonly maxPending;
    private circuitFailures;
    private readonly circuitThreshold;
    private circuitOpenUntil;
    private readonly circuitCooldown;
    private readonly llmToolNames;
    private signalHandlers;
    private forwardingEnabled;
    /** Flag to prevent restart races when disconnect is intentional */
    private _disconnecting;
    /** Periodic health probe interval handle (blocker 15). */
    private _healthProbeTimer;
    /** Default health probe interval in ms (30s). */
    private static readonly HEALTH_PROBE_INTERVAL_MS;
    constructor(workersPath: string, pythonPath?: string, options?: {
        maxPending?: number;
    });
    private validatePaths;
    /** Register signal forwarding from parent to child process */
    enableSignalForwarding(): void;
    /** Remove signal forwarding handlers */
    private disableSignalForwarding;
    on(event: "llm-status-changed", handler: (status: string) => void): void;
    llmStatus(): LLMStatus;
    private setLLMStatus;
    connect(): Promise<void>;
    private cleanup;
    private spawnChild;
    killChild(): void;
    restartWorker(): Promise<void>;
    isHealthy(): Promise<boolean>;
    private waitForReady;
    /** Periodic health probe — returns true if worker is responsive. */
    probeHealth(): Promise<boolean>;
    /** Start periodic health probes every 30s while connected (blocker 15).
     *  If probeHealth() returns false, logs a warning and kicks off worker
     *  restart via the supervisor. The supervisor handles its own recovery
     *  from degraded mode, so this probe only triggers restarts when the
     *  worker is NOT already in degraded mode. Uses unref() so the timer
     *  doesn't keep the process alive. */
    private _startHealthProbes;
    private _stopHealthProbes;
    private sendRequest;
    callTool(name: string, args: unknown, timeoutMs?: number, cacheMode?: CacheMode): Promise<ToolResult>;
    getTools(): Promise<ToolDefinition[]>;
    /** Phase 4.2.2: Check if degraded mode is active (worker unavailable). */
    isDegraded(): boolean;
    /** Phase 4.2.2: Get a cached tool result from the degraded cache.
     *  Uses freshness tracking (blocker 7):
     *  - Hit count tracks how many times the cached result has been served
     *  - Warning logged at DEGRADED_CACHE_MAX_HITS (3) to indicate staleness
     *  - TTL expiry removes entry entirely
     *
     *  Returns undefined if no recent cache entry exists for the tool. */
    getCachedToolResult(toolName: string): ToolResult | undefined;
    /** Phase 4.2.2: Store a successful tool result in the degraded cache.
     *  Called automatically by callTool on success. Resets hit count on
     *  each fresh write (blocker 7). */
    private cacheToolResult;
    /** Reset circuit breaker — called after cooldown or manual recovery */
    resetCircuitBreaker(): void;
    /** Set the local tool registry snapshot for drift comparison.
     *  Without this, quickDriftCheck would compare MCP against itself. */
    setRegistryTools(tools: ToolDefinition[]): void;
    /** Lightweight drift check: compares a hash of (tool names + capability sets).
     *  Returns true if MCP and registry are in sync. Returns false on mismatch,
     *  at which point callers should run the full detectDrift() for details.
     *  Hash includes capability sets so a tool that changes capabilities without
     *  changing its name is still detected.
     */
    quickDriftCheck(): Promise<boolean>;
    detectDrift(): Promise<DriftReport>;
    agentInit(params: {
        target: string;
        phase: string;
        techStack?: string[];
        pipeline?: any[];
        context?: Record<string, any>;
        engagementId?: string;
    }): Promise<{
        session_id: string;
        plan: string[];
        reasoning: string;
        phase: string;
        hypotheses?: Array<{
            id: string;
            description: string;
            confidence: number;
            status: string;
        }>;
    }>;
    agentNext(params: {
        session_id: string;
        trigger?: "stuck" | "new_finding" | "phase_complete";
        /** Max iterations for this agent session — TS caps the Python loop (blocker 32). */
        max_iterations?: number;
    }): Promise<{
        tool?: string;
        session_id: string;
        reasoning: string;
        done: boolean;
    }>;
    agentObserve(params: {
        session_id: string;
        tool: string;
        arguments?: Record<string, string>;
        reasoning?: string;
        success: boolean;
        durationMs?: number;
        findingCount?: number;
        summary?: string;
    }): Promise<{
        tool?: string;
        session_id: string;
        reasoning: string;
        done: boolean;
    }>;
    /**
     * Fetch the attack graph for an engagement from the Python MCP worker.
     * Returns detected chains, highest-risk paths, and chain-derived phase plans
     * that the TypeScript planner can use to insert exploitation phases.
     */
    getAttackGraph(params: {
        engagement_id: string;
        findings?: any[];
    }): Promise<{
        chains: Array<{
            chain_id: string;
            name: string;
            severity: string;
            correlation_factor: number;
            prerequisite_type: string;
            chain_type: string;
            description: string;
        }>;
        paths: any[];
        chain_plans: Array<{
            chain_id: string;
            name: string;
            severity: string;
            risk_score: number;
            prerequisite_finding_types: string[];
            suggested_capabilities: string[];
            description: string;
        }>;
    }>;
    /**
     * Fetch the full attack graph snapshot for frontend visualization.
     *
     * Returns the complete `to_snapshot_dict()` output enriched with chain
     * metadata (chain_id, chain_name per path) and summary statistics.
     * Designed for the AttackGraphVisualizer component.
     */
    getAttackGraphSnapshot(params: {
        engagement_id: string;
        findings?: any[];
    }): Promise<{
        paths: Array<{
            risk_score: number;
            nodes: Array<{
                id: string;
                type: "vulnerability" | "endpoint";
                data: Record<string, any>;
                cvss: number | null;
                confidence: number | null;
                prerequisites: string[];
                downstream_impacts: string[];
            }>;
            edges: Array<{
                from_node: string;
                to_node: string;
                type: string;
                correlation_factor: number;
                relationship_type: string;
            }>;
            chain_id?: string;
            chain_name?: string;
        }>;
        metadata: {
            totalPaths: number;
            totalFindings: number;
            highestRiskScore: number;
            chainsDetected: number;
        };
    }>;
    /** Phase 4.1.4: Get completed tool list for a given phase (for checkpoint resume). */
    getCheckpoint(engagementId: string, phase: string): Promise<{
        completed_tools: string[];
    }>;
    /** Phase 4.4.1: Acquire a distributed lock for an engagement via MCP. */
    acquireEngagementLock(engagementId: string): Promise<{
        acquired: boolean;
    }>;
    /** Phase 4.4.1: Release a distributed lock for an engagement via MCP. */
    releaseEngagementLock(engagementId: string): Promise<{
        released: boolean;
    }>;
    /**
     * Cancel the current ReActAgent session for an engagement (blocker 38).
     * This propagates the stop signal from TypeScript to the Python agent
     * so it stops mid-execution instead of continuing until the next iteration.
     */
    cancelAgent(engagementId: string, sessionId?: string): Promise<{
        cancelled: boolean;
        error?: string;
    }>;
    /**
     * Signal phase completion to the Python MCP worker (Phase 1.2 — LLM-Driven Replanning).
     *
     * After each phase completes, the workflow-runner sends all accumulated findings
     * so the LLM can analyze them and suggest the next capabilities to run. This
     * closes the feedback loop from findings to tool selection.
     *
     * @param params.engagement_id - The engagement UUID.
     * @param params.phase - The phase that just completed.
     * @param params.target - The assessment target.
     * @param params.findings - All findings accumulated so far.
     * @returns Suggested next capabilities and whether to stop the assessment.
     */
    phaseComplete(params: {
        engagement_id: string;
        phase: string;
        target: string;
        findings: any[];
    }): Promise<{
        next_capabilities: string[];
        reasoning: string;
        stop: boolean;
        fallback?: boolean;
    }>;
    disconnect(): Promise<void>;
}
export {};

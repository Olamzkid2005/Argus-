/**
 * LLM Planner Service — bridges the OpenCode Session LLM into the Argus planner.
 *
 * This service uses the @opencode-ai/llm package (which IS the OpenCode LLM
 * infrastructure) to:
 *   1. Suggest assessment phases/capabilities during initial planning
 *   2. Analyze accumulated findings and suggest next capabilities during replanning
 *
 * Architecture:
 *   LLMPlannerService.lazy() → creates singleton instance
 *     ↓
 *   Uses openai/anthropic providers from @opencode-ai/llm/providers/*
 *     → openai.model("gpt-4o-mini", { apiKey }) returns a Model with route
 *     → Route has protocol (OpenAI Chat), endpoint, auth, transport
 *     ↓
 *   LLM.generateObject() → forces structured output via synthetic tool call
 *     → Returns Effect<GenerateObjectResponse<T>>
 *     → Effect.runPromise wraps it for async/await usage
 *     ↓
 *   Returns structured capability suggestions for the planner
 */
export interface LLMPhaseSuggestion {
    /** LLM-suggested capability strings (e.g. "sqli_detection", "xss_detection"). */
    readonly capabilities: string[];
    /** Natural-language reasoning for this suggestion. */
    readonly reasoning: string;
}
export interface LLMReplanSuggestion {
    /** Suggested next capability strings. */
    readonly nextCapabilities: string[];
    /** Why the LLM suggests these capabilities. */
    readonly reasoning: string;
    /** Whether the assessment should stop (all important findings found). */
    readonly stopAssessment: boolean;
}
export interface LLMPhaseSuggestionResult {
    readonly targetAnalysis: string;
    readonly suggestedPhases: LLMPhaseSuggestion[];
}
export declare class LLMPlannerService {
    private static instance;
    private model;
    private initialized;
    private initError;
    private available;
    private constructor();
    /**
     * Get or create the singleton LLMPlannerService instance.
     * Initialization is lazy — the first call to any suggestion method
     * triggers setup. This keeps assessment start fast when LLM isn't needed.
     */
    static lazy(): LLMPlannerService;
    private ensureInitialized;
    /**
     * Check if the LLM service is available for use.
     * Triggers lazy initialization on first call.
     */
    isAvailable(): Promise<boolean>;
    /** Get the initialization error message, if any. */
    getInitError(): string | null;
    /**
     * Use the LLM to suggest assessment phases/capabilities for a target.
     * Returns an empty array if the LLM is unavailable or the call fails.
     *
     * @param target - The target URL or identifier
     * @param targetType - Detected target type (web_app, api, spa, unknown)
     * @param techStack - Optional detected technologies
     * @returns Array of capability suggestions with reasoning
     */
    suggestPhases(target: string, targetType: string, techStack?: string[]): Promise<LLMPhaseSuggestionResult>;
    /**
     * Use the LLM to analyze accumulated findings and suggest next capabilities.
     * Returns null if the LLM is unavailable or the call fails.
     *
     * @param target - The target being assessed
     * @param findings - Accumulated findings from completed phases
     * @returns Replan suggestion or null on failure
     */
    suggestReplan(target: string, findings: ReadonlyArray<{
        title: string;
        severity: number;
        subtype?: string;
        confidence: number;
    }>): Promise<LLMReplanSuggestion | null>;
    /**
     * Get the resolved model identifier string for diagnostic/logging purposes.
     * Returns "unavailable" if not yet initialized.
     */
    getModelId(): string;
    /**
     * Switch the planner model at runtime.
     *
     * Resets the initialized state and forces reinitialization with the
     * new model ID on the next LLM call. Also updates the environment
     * variable so subsequent env-var-based resolution uses the new value.
     *
     * @param modelId - The new model identifier (e.g. "gpt-4o", "claude-sonnet-4-20250514")
     */
    static switchModel(modelId: string): void;
    /**
     * Get the current model ID from the env var, if one is set.
     * Returns the raw value or undefined.
     */
    static getCurrentModelId(): string | undefined;
    /**
     * Get available model options based on configured API keys.
     * Returns a sorted list of model ID strings the user can switch to.
     * Always includes the currently active model (if any).
     */
    static getAvailableModels(): string[];
    /**
     * Get which env var controls the planner model (for help/doctor displays).
     */
    static getModelEnvVarDescription(): string;
    /**
     * Resolve an API key from environment variables.
     * Tries, in order: OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENCODE_API_KEY.
     */
    private resolveApiKey;
    /**
     * Create an LLM Model from the configured model string and API key.
     * Uses the model specified in ARGUS_PLANNER_MODEL (or OPENCODE_MODEL),
     * otherwise defaults to gpt-4o-mini.
     *
     * Detects Anthropic models vs OpenAI-compatible models by the model name.
     *
     * Configure via env var:
     *   ARGUS_PLANNER_MODEL=claude-sonnet-4-20250514   → Anthropic
     *   ARGUS_PLANNER_MODEL=gpt-4o-mini                 → OpenAI (default)
     *   ARGUS_PLANNER_MODEL=accounts/fireworks/models/... → OpenAI-compatible
     */
    private resolveModel;
}

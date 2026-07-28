/**
 * Feature Flag System (Task 4.1)
 *
 * All V5 features are **opt-in** — disabled by default for backward compatibility.
 * v5 behaves identically to v4 until explicitly configured.
 *
 * Precedence (highest to lowest):
 *   1. CLI flags (--enable-workflow-registry)
 *   2. Environment variables (ARGUS_FEATURE_*)
 *   3. Project config (./argus.config.yaml → features: {})
 *   4. User config (~/.argus/config.yaml → features: {})
 *   5. Built-in defaults (all false)
 */
import type { IFeatureFlags } from "@opencode/runtime";
export declare enum Feature {
    WORKFLOW_REGISTRY = "workflow_registry",
    ENGAGEMENT_STORE = "engagement_store",
    DETERMINISTIC_FALLBACK = "deterministic_fallback",
    APPROVAL_GATES = "approval_gates",
    LLM_FINDING_ANALYSIS = "llm_finding_analysis",
    ENCRYPTION_AT_REST = "encryption_at_rest"
}
export declare class FeatureFlags implements IFeatureFlags {
    private flags;
    private sources;
    constructor(overrides?: Partial<Record<Feature, boolean>>);
    /** Apply overrides from any source with proper precedence tracking */
    applyOverrides(overrides: Partial<Record<Feature, boolean>>, source: string): void;
    /**
     * Load from environment variables (ARGUS_FEATURE_*).
     *
     * Also checks ARGUS_AUTONOMOUS=1 — when set, autonomy-related features
     * are enabled by default as an autonomous profile. Individual
     * ARGUS_FEATURE_* env vars take precedence over the profile, allowing
     * explicit overrides to disable specific features.
     */
    loadFromEnv(): void;
    /** Returns true when running in autonomous mode (ARGUS_AUTONOMOUS=1) */
    isAutonomousMode(): boolean;
    /**
     * In autonomous mode, fail hard if required features are disabled.
     * Throws an error listing which features must be enabled.
     */
    failIfAutonomousFeaturesDisabled(): void;
    /** Load from a config object (from argus.config.yaml) */
    loadFromConfig(configObj: Record<string, boolean>): void;
    /**
     * Validate that no unknown feature keys exist in the config.
     * In autonomous mode, this fails hard with an error listing unknown keys.
     */
    validateKeys(configObj: Record<string, unknown>): void;
    /** Load from ~/.argus/config.yaml (user config) */
    loadFromUserConfig(configPath?: string): void;
    /** Returns true when ALL feature flags are disabled (degraded mode) */
    isDegradedMode(): boolean;
    /** Check if a feature is enabled */
    isEnabled(feature: Feature): boolean;
    /** Check if ALL listed features are enabled */
    allEnabled(...features: Feature[]): boolean;
    /** Check if ANY of the listed features is enabled */
    anyEnabled(...features: Feature[]): boolean;
    /** Get all features with their current state and source */
    dump(): Record<string, {
        enabled: boolean;
        source: string;
    }>;
}
export declare function getFeatureFlags(): FeatureFlags;
export declare function resetFeatureFlags(): void;

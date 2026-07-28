/**
 * TargetValidator — Hard technical guardrails for target scope enforcement.
 *
 * Provides three layers of protection before any assessment or tool execution:
 *   1. Scope validation against configured allowed/blocked targets
 *   2. DNS reachability check for the target host
 *   3. allowed_git_hosts enforcement for git-related tools
 *
 * Configuration is read from argus.config.yaml's security.scope section.
 * The validator is fail-open when no scope is configured (backward compatible)
 * and fail-closed when scope IS configured but validation errors occur.
 *
 * This is the TS/TUI-side equivalent of the Python workers' ScopeValidator.
 * The Python side already has comprehensive scope validation in the orchestrator
 * and agent runtimes — this fills the gap for the TS-side execution path
 * (workflow-runner.ts, assess command, TUI /assess).
 */
export interface GitHostPolicy {
    policy: "allowlist" | "allow_all";
    allowedHosts?: string[];
}
export interface ScopeConfig {
    /** Glob patterns for targets that ARE allowed (e.g. ["*.example.com"]) */
    allowed_targets?: string[];
    /** Glob patterns for targets that are NEVER allowed (e.g. ["*.internal.corp"]) */
    blocked_targets?: string[];
    /** If true, requires user confirmation before running assessment on a new target */
    require_confirmation?: boolean;
}
export interface SecurityConfig {
    allowed_git_hosts: string[];
    scope?: ScopeConfig;
    /**
     * Git host policy — controls which git hosts are allowed for repo scanning.
     *   "allowlist": only hosts in the curated default list + allowed_git_hosts
     *   "allow_all": all hosts allowed (dangerous — use with caution)
     *
     * NOTE: Dual enforcement — this is the TS/TUI-side policy. The Python workers
     * enforce the same policy at runtime via GitSSRFConfig.from_config() in
     * config/constants.py. Both sides must be kept in sync.
     */
    git_host_policy?: GitHostPolicy;
}
export interface ValidationResult {
    valid: boolean;
    reason?: string;
    /** Human-readable message explaining the result */
    message: string;
    /** If true, DNS resolution succeeded */
    dnsReachable?: boolean;
}
/**
 * Check whether a git host is allowed by the configured policy.
 * When policy is "allow_all", all hosts pass.
 * When policy is "allowlist", the host must match the merged
 * default + configured allowlist (exact match or subdomain match).
 */
export declare function isGitHostAllowed(host: string, config?: GitHostPolicy): boolean;
export declare class TargetValidator {
    private config;
    private loaded;
    constructor(config?: Partial<SecurityConfig>);
    /**
     * Load scope/security configuration from argus.config.yaml.
     * Falls back to defaults if the file is missing or malformed.
     *
     * Reads both the top-level `security.git_host_policy` and the
     * scope-level `security.scope.git_host_policy`. The scope-level
     * field takes precedence when present.
     *
     * NOTE: Dual enforcement — Python side enforces the same policy
     * via GitSSRFConfig.from_config() in config/constants.py.
     */
    load(): SecurityConfig;
    /**
     * Validate a target before assessment execution.
     * Checks: blocked list → allowed list → DNS reachability
     */
    validateTarget(target: string): Promise<ValidationResult>;
    /**
     * Check if a git host is allowed under the configured policy.
     *
     * Uses the GitHostPolicy-based isGitHostAllowed() function which respects
     * both the curated default allowlist and the configured policy mode.
     *
     * When policy is "allow_all", all hosts pass.
     * When policy is "allowlist", the host must be in the merged default + configured list.
     *
     * NOTE: Dual enforcement — Python workers enforce the same policy at runtime
     * via GitSSRFConfig.from_config() in config/constants.py. The curated default
     * list is replicated in DEFAULT_GIT_HOSTS above and must stay in sync with
     * the Python-side default (constants.py GitSSRFConfig.host_allowlist).
     */
    isGitHostAllowed(hostname: string): boolean;
    /**
     * Check if scope has allowed_targets configured (scope enforcement is active).
     */
    hasScopeEnforcement(): boolean;
    /**
     * Check if user confirmation is required for this target.
     * Returns true when:
     *   - require_confirmation is true in scope config, AND
     *   - scope enforcement IS configured (allowed_targets list is non-empty or blocked list is non-empty)
     *   - the target is NOT in the allowed list (would already be approved)
     */
    requiresConfirmation(target: string): boolean;
    private extractHostname;
    /**
     * Simple glob matching supporting:
     *   - *.example.com — matches any subdomain of example.com (one level)
     *   - example.com — exact match
     *   - * — matches everything
     * No shell expansion — safe for untrusted patterns.
     */
    private matchesGlob;
}
export declare function getTargetValidator(): TargetValidator;
export declare function resetTargetValidator(): void;

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

import { join } from "path"
import { readFileSync } from "fs"
import { parse as YAML } from "yaml"
import { resolve } from "dns/promises"

/* ── Types ─────────────────────────────────────────────────────────── */

/**
 * Default curated list of allowed git hosts.
 * Matches the Python-side GitSSRFConfig.host_allowlist.
 */
const DEFAULT_GIT_HOSTS: readonly string[] = [
  "bitbucket.org",
  "gist.github.com",
  "git.kernel.org",
  "git.savannah.gnu.org",
  "git.savannah.nongnu.org",
  "git.sr.ht",
  "github.com",
  "gitlab.com",
  "gitlab.archlinux.org",
  "gitlab.freedesktop.org",
  "gitlab.gnome.org",
  "gitlab.kitware.com",
  "gitlab.xfce.org",
]

export interface GitHostPolicy {
  policy: "allowlist" | "allow_all"
  allowedHosts?: string[]
}

export interface ScopeConfig {
  /** Glob patterns for targets that ARE allowed (e.g. ["*.example.com"]) */
  allowed_targets?: string[]
  /** Glob patterns for targets that are NEVER allowed (e.g. ["*.internal.corp"]) */
  blocked_targets?: string[]
  /** If true, requires user confirmation before running assessment on a new target */
  require_confirmation?: boolean
}

export interface SecurityConfig {
  allowed_git_hosts: string[]
  scope?: ScopeConfig
  /**
   * Git host policy — controls which git hosts are allowed for repo scanning.
   *   "allowlist": only hosts in the curated default list + allowed_git_hosts
   *   "allow_all": all hosts allowed (dangerous — use with caution)
   *
   * NOTE: Dual enforcement — this is the TS/TUI-side policy. The Python workers
   * enforce the same policy at runtime via GitSSRFConfig.from_config() in
   * config/constants.py. Both sides must be kept in sync.
   */
  git_host_policy?: GitHostPolicy
}

export interface ValidationResult {
  valid: boolean
  reason?: string
  /** Human-readable message explaining the result */
  message: string
  /** If true, DNS resolution succeeded */
  dnsReachable?: boolean
}

/**
 * Check whether a git host is allowed by the configured policy.
 * When policy is "allow_all", all hosts pass.
 * When policy is "allowlist", the host must match the merged
 * default + configured allowlist (exact match or subdomain match).
 */
export function isGitHostAllowed(host: string, config?: GitHostPolicy): boolean {
  if (!config || config.policy === "allow_all") return true

  const allowlist = [...DEFAULT_GIT_HOSTS, ...(config.allowedHosts ?? [])]
  return allowlist.some(allowed =>
    host === allowed || host.endsWith("." + allowed)
  )
}

/* ── Defaults ──────────────────────────────────────────────────────── */

const DEFAULT_CONFIG: SecurityConfig = {
  allowed_git_hosts: [],
  scope: {
    allowed_targets: [],
    blocked_targets: [],
    require_confirmation: false,
  },
}

/* ── Target Validator ──────────────────────────────────────────────── */

export class TargetValidator {
  private config: SecurityConfig
  private loaded = false

  constructor(config?: Partial<SecurityConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    if (config) this.loaded = true
  }

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
  load(): SecurityConfig {
    if (this.loaded) return this.config

    try {
      const configPath = join(process.cwd(), "argus.config.yaml")
      const raw = readFileSync(configPath, "utf-8")
      const parsed = YAML(raw) as {
        security?: Partial<SecurityConfig> & {
          scope?: {
            mode?: string
            allowed_targets?: string[]
            blocked_targets?: string[]
            require_confirmation?: boolean
            git_host_policy?: string
            allowed_git_hosts?: string[]
          }
        }
      } | undefined

      if (parsed?.security) {
        const sec = parsed.security
        // Read git_host_policy from scope level first, fall back to top level
        const scopeGitPolicy = sec.scope?.git_host_policy
        const topGitPolicy = (sec as Record<string, unknown>).git_host_policy as string | undefined
        const gitPolicy = scopeGitPolicy ?? topGitPolicy ?? "allowlist"
        const gitHosts = sec.scope?.allowed_git_hosts ?? sec.allowed_git_hosts ?? []

        this.config = {
          allowed_git_hosts: gitHosts,
          scope: {
            allowed_targets: sec.scope?.allowed_targets ?? [],
            blocked_targets: sec.scope?.blocked_targets ?? [],
            require_confirmation: sec.scope?.require_confirmation ?? false,
          },
          git_host_policy: {
            policy: gitPolicy === "allow_all" ? "allow_all" : "allowlist",
            allowedHosts: gitHosts,
          },
        }
      }
    } catch {
      // Config file missing or invalid — use defaults silently
      // This is expected for fresh installs and CI environments
    }

    this.loaded = true
    return this.config
  }

  /**
   * Validate a target before assessment execution.
   * Checks: blocked list → allowed list → DNS reachability
   */
  async validateTarget(target: string): Promise<ValidationResult> {
    this.load()

    // Reject overly long targets (ReDoS protection, memory protection)
    const MAX_TARGET_LENGTH = 2048
    if (target.length > MAX_TARGET_LENGTH) {
      return {
        valid: false,
        reason: "target_too_long",
        message: `Target URL exceeds maximum length of ${MAX_TARGET_LENGTH} characters.`,
      }
    }

    // Validate URL scheme
    const allowedSchemes = ["http://", "https://", "ftp://"]
    const hasValidScheme = allowedSchemes.some((scheme) => target.toLowerCase().startsWith(scheme))
    if (!hasValidScheme) {
      return {
        valid: false,
        reason: "invalid_scheme",
        message: `Target must start with http://, https://, or ftp://`,
      }
    }

    const { scope } = this.config

    // 1. Blocked targets check (always enforced)
    if (scope?.blocked_targets && scope.blocked_targets.length > 0) {
      for (const pattern of scope.blocked_targets) {
        if (this.matchesGlob(target, pattern)) {
          return {
            valid: false,
            reason: "blocked_target",
            message: `Target "${target}" matches blocked pattern "${pattern}". Remove it from security.scope.blocked_targets in argus.config.yaml to proceed.`,
          }
        }
      }
    }

    // 2. Allowed targets check (only enforced when configured)
    if (scope?.allowed_targets && scope.allowed_targets.length > 0) {
      const isAllowed = scope.allowed_targets.some((pattern) =>
        this.matchesGlob(target, pattern),
      )
      if (!isAllowed) {
        return {
          valid: false,
          reason: "not_in_allowed_targets",
          message: `Target "${target}" is not in the allowed targets list. Add a matching pattern to security.scope.allowed_targets in argus.config.yaml or remove it to allow all targets.`,
        }
      }
    }

    // 3. DNS reachability check (informational — does not block)
    const hostname = this.extractHostname(target)
    let dnsReachable = false
    try {
      await resolve(hostname)
      dnsReachable = true
    } catch {
      dnsReachable = false
    }

    return {
      valid: true,
      dnsReachable,
      message: dnsReachable
        ? `Target "${target}" resolved to IP via DNS`
        : `Target "${target}" — DNS resolution failed for "${hostname}". Target may be unreachable or the hostname may be invalid.`,
    }
  }

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
  isGitHostAllowed(hostname: string): boolean {
    this.load()
    return isGitHostAllowed(hostname, this.config.git_host_policy)
  }

  /**
   * Check if scope has allowed_targets configured (scope enforcement is active).
   */
  hasScopeEnforcement(): boolean {
    this.load()
    const { scope } = this.config
    return (
      (!!scope?.allowed_targets && scope.allowed_targets.length > 0) ||
      (!!scope?.blocked_targets && scope.blocked_targets.length > 0)
    )
  }

  /**
   * Check if user confirmation is required for this target.
   * Returns true when:
   *   - require_confirmation is true in scope config, AND
   *   - scope enforcement IS configured (allowed_targets list is non-empty or blocked list is non-empty)
   *   - the target is NOT in the allowed list (would already be approved)
   */
  requiresConfirmation(target: string): boolean {
    this.load()
    const { scope } = this.config
    if (!scope?.require_confirmation) return false
    if (!this.hasScopeEnforcement()) return false

    // If target is explicitly in allowed list, no confirmation needed
    if (scope.allowed_targets && scope.allowed_targets.length > 0) {
      return !scope.allowed_targets.some((pattern) => this.matchesGlob(target, pattern))
    }

    return false
  }

  /* ── Helpers ─────────────────────────────────────────────────────── */

  private extractHostname(target: string): string {
    // Strip protocol
    let hostname = target.replace(/^https?:\/\//, "").replace(/^ftp:\/\//, "")
    // Strip path/port
    hostname = hostname.split("/")[0].split(":")[0]
    return hostname
  }

  /**
   * Simple glob matching supporting:
   *   - *.example.com — matches any subdomain of example.com (one level)
   *   - example.com — exact match
   *   - * — matches everything
   * No shell expansion — safe for untrusted patterns.
   */
  private matchesGlob(target: string, pattern: string): boolean {
    const targetLower = target.toLowerCase()
    const patternLower = pattern.toLowerCase()

    // Wildcard: matches everything
    if (patternLower === "*") return true

    // Wildcard prefix: *.example.com
    if (patternLower.startsWith("*.")) {
      const suffix = patternLower.slice(1) // ".example.com"
      return targetLower.endsWith(suffix) && targetLower.length > suffix.length
    }

    // Wildcard suffix: example.* (match any TLD)
    if (patternLower.endsWith(".*")) {
      const prefix = patternLower.slice(0, -2) // "example"
      return targetLower.startsWith(prefix) && targetLower.length > prefix.length + 1
    }

    // Exact match
    return targetLower === patternLower
  }
}

/** Singleton instance for app-wide use */
let _instance: TargetValidator | null = null

export function getTargetValidator(): TargetValidator {
  if (!_instance) {
    _instance = new TargetValidator()
  }
  return _instance
}

export function resetTargetValidator(): void {
  _instance = null
}

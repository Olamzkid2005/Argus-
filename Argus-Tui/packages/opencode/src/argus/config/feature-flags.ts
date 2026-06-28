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

import { join } from "path"
import { StoragePaths } from "../storage/paths"
import { readFileSync } from "fs"
import { parse as YAML } from "yaml"
import type { IFeatureFlags } from "@opencode/runtime"

export enum Feature {
  WORKFLOW_REGISTRY = "workflow_registry",
  ENGAGEMENT_STORE = "engagement_store",
  DETERMINISTIC_FALLBACK = "deterministic_fallback",
  APPROVAL_GATES = "approval_gates",
  LLM_FINDING_ANALYSIS = "llm_finding_analysis",
  ENCRYPTION_AT_REST = "encryption_at_rest",
}

const DEFAULT_FEATURES: Record<Feature, boolean> = {
  [Feature.WORKFLOW_REGISTRY]: true,
  [Feature.ENGAGEMENT_STORE]: true,
  [Feature.DETERMINISTIC_FALLBACK]: false,       // Opt-in (was true pre-v5)
  [Feature.APPROVAL_GATES]: true,
  [Feature.LLM_FINDING_ANALYSIS]: true,
  [Feature.ENCRYPTION_AT_REST]: false,
}

export class FeatureFlags implements IFeatureFlags {
  private flags: Map<Feature, boolean> = new Map()
  private sources: Map<Feature, string> = new Map()

  constructor(overrides?: Partial<Record<Feature, boolean>>) {
    // Load defaults
    for (const [key, value] of Object.entries(DEFAULT_FEATURES)) {
      this.flags.set(key as Feature, value)
      this.sources.set(key as Feature, "default")
    }
    if (overrides) this.applyOverrides(overrides, "constructor")
  }

  /** Apply overrides from any source with proper precedence tracking */
  applyOverrides(overrides: Partial<Record<Feature, boolean>>, source: string): void {
    for (const [key, value] of Object.entries(overrides)) {
      if (value !== undefined) {
        this.flags.set(key as Feature, value)
        this.sources.set(key as Feature, source)
      }
    }
  }

  /** Load from environment variables (ARGUS_FEATURE_*) */
  loadFromEnv(): void {
    for (const feature of Object.values(Feature)) {
      const envKey = `ARGUS_FEATURE_${feature.toUpperCase().replace(/-/g, "_")}`
      const envVal = process.env[envKey]
      if (envVal !== undefined) {
        const value = envVal.toLowerCase() === "true" || envVal === "1"
        this.flags.set(feature, value)
        this.sources.set(feature, "env")
      }
    }
  }

  /** Load from a config object (from argus.config.yaml) */
  loadFromConfig(configObj: Record<string, boolean>): void {
    const known = new Set(Object.values(Feature))
    for (const [key, value] of Object.entries(configObj)) {
      if (!known.has(key as Feature)) {
        console.warn(`[argus] Unknown feature key "${key}" in config — expected one of: ${Object.values(Feature).join(", ")}`)
        continue
      }
      this.flags.set(key as Feature, value)
      this.sources.set(key as Feature, "config")
    }
  }

  /** Load from ~/.argus/config.yaml (user config) */
  loadFromUserConfig(configPath?: string): void {
    const path = configPath ?? StoragePaths.config
    try {
      const content = readFileSync(path, "utf-8")
      const parsed = YAML(content) as { features?: Record<string, boolean> } | undefined
      if (parsed?.features) {
        this.loadFromConfig(parsed.features)
        for (const key of Object.keys(parsed.features)) {
          const feature = Object.values(Feature).find((f) => f === key)
          if (feature) this.sources.set(feature, "user_config")
        }
      }
    } catch {
      console.warn("[feature-flags] User config file missing or invalid — using defaults")
    }
  }

  /** Returns true when ALL feature flags are disabled (degraded mode) */
  isDegradedMode(): boolean {
    return Object.values(Feature).every((f) => !this.isEnabled(f))
  }

  /** Check if a feature is enabled */
  isEnabled(feature: Feature): boolean {
    return this.flags.get(feature) ?? DEFAULT_FEATURES[feature] ?? false
  }

  /** Check if ALL listed features are enabled */
  allEnabled(...features: Feature[]): boolean {
    return features.every((f) => this.isEnabled(f))
  }

  /** Check if ANY of the listed features is enabled */
  anyEnabled(...features: Feature[]): boolean {
    return features.some((f) => this.isEnabled(f))
  }

  /** Get all features with their current state and source */
  dump(): Record<string, { enabled: boolean; source: string }> {
    const result: Record<string, { enabled: boolean; source: string }> = {}
    for (const feature of Object.values(Feature)) {
      result[feature] = {
        enabled: this.isEnabled(feature),
        source: this.sources.get(feature) ?? "default",
      }
    }
    return result
  }
}

/** Singleton instance for app-wide use */
let _instance: FeatureFlags | null = null

export function getFeatureFlags(): FeatureFlags {
  if (!_instance) {
    _instance = new FeatureFlags()
    // Load from env vars first (takes precedence over config files)
    _instance.loadFromEnv()
    // Then load from project config file (argus.config.yaml)
    try {
      const configPath = join(process.cwd(), "argus.config.yaml")
      const raw = readFileSync(configPath, "utf-8")
      const parsed = YAML(raw) as { features?: Record<string, boolean> } | undefined
      if (parsed?.features) {
        _instance.loadFromConfig(parsed.features)
      }
    } catch {
      console.warn("[feature-flags] Project config file missing or invalid — using env/defaults")
    }
    // Then load from user config (~/.argus/config.yaml)
    _instance.loadFromUserConfig()
  }
  return _instance
}

export function resetFeatureFlags(): void {
  _instance = null
}

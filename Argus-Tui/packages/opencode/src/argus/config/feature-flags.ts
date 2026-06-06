/**
 * Feature Flag System (Task 4.1)
 *
 * All V5 features are **opt-in** — disabled by default for backward compatibility.
 * v5 behaves identically to v4 until explicitly configured.
 *
 * Precedence (highest to lowest):
 *   1. CLI flags (--enable-browser --enable-workflow-registry)
 *   2. Environment variables (ARGUS_FEATURE_*)
 *   3. Project config (./argus.config.yaml → features: {})
 *   4. User config (~/.argus/config.yaml → features: {})
 *   5. Built-in defaults (all false)
 */

import { homedir } from "os"
import { join } from "path"
import { readFileSync } from "fs"
import { parse as YAML } from "yaml"
import type { IFeatureFlags } from "../../opencode-runtime"

export enum Feature {
  BROWSER_VERIFICATION = "browser_verification",
  WORKFLOW_REGISTRY = "workflow_registry",
  ENGAGEMENT_STORE = "engagement_store",
  DETERMINISTIC_FALLBACK = "deterministic_fallback",
  APPROVAL_GATES = "approval_gates",
  LLM_FINDING_ANALYSIS = "llm_finding_analysis",
}

const DEFAULT_FEATURES: Record<Feature, boolean> = {
  [Feature.BROWSER_VERIFICATION]: false,
  [Feature.WORKFLOW_REGISTRY]: false,
  [Feature.ENGAGEMENT_STORE]: false,
  [Feature.DETERMINISTIC_FALLBACK]: true,       // Always-on safe default
  [Feature.APPROVAL_GATES]: false,
  [Feature.LLM_FINDING_ANALYSIS]: false,
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
    for (const [key, value] of Object.entries(configObj)) {
      const feature = Object.values(Feature).find((f) => f === key)
      if (feature !== undefined) {
        this.flags.set(feature, value)
        this.sources.set(feature, "config")
      }
    }
  }

  /** Load from ~/.argus/config.yaml (user config) */
  loadFromUserConfig(configPath?: string): void {
    const path = configPath ?? join(homedir(), ".argus", "config.yaml")
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
    } catch { /* config file missing or invalid — use defaults */ }
  }

  /** Apply CLI flag overrides */
  loadFromCLI(cliFlags: Record<string, boolean>): void {
    const featureMap: Record<string, Feature> = {
      "enable-browser": Feature.BROWSER_VERIFICATION,
      "enable-workflow-registry": Feature.WORKFLOW_REGISTRY,
      "enable-engagement-store": Feature.ENGAGEMENT_STORE,
      "enable-approval-gates": Feature.APPROVAL_GATES,
      "disable-deterministic": Feature.DETERMINISTIC_FALLBACK,
      "enable-llm-analysis": Feature.LLM_FINDING_ANALYSIS,
    }
    for (const [cliKey, feature] of Object.entries(featureMap)) {
      if (cliFlags[cliKey] !== undefined) {
        this.flags.set(feature, cliFlags[cliKey])
        this.sources.set(feature, "cli")
      }
    }
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
    _instance.loadFromEnv()
  }
  return _instance
}

export function resetFeatureFlags(): void {
  _instance = null
}

/**
 * Config Loader (Task 0.0.x / Option B)
 *
 * Reads ./argus.config.yaml and ~/.argus/config.yaml, validates
 * with Zod, and produces a typed config object. Single-source loading
 * for now (no deep-merge) — merge logic will be added when user config
 * is exercised.
 *
 * Precedence (future):  CLI flags > Env vars > Project config > User config > Defaults
 * Current: Project config only (feature flags + evidence settings).
 */
import { homedir } from "os"
import { join } from "path"
import { existsSync, readFileSync } from "fs"
import { z } from "zod"
import { parse as YAML } from "yaml"
import { Confidence } from "../shared/types"

// ── Schema ──
// Single source of truth: export the inferred type, never maintain a parallel interface.

const EvidenceConfigSchema = z.object({
  retention_days: z.number().int().positive().default(30),
  max_engagement_size_mb: z.number().positive().default(500),
  capture_har: z.boolean().default(false),
  capture_video: z.boolean().default(false),
  capture_threshold: z
    .number()
    .int()
    .min(0)
    .max(5)
    .default(Confidence.HIGH),
})

const FeaturesConfigSchema = z.record(z.boolean())

const ArgusConfigSchema = z.object({
  features: FeaturesConfigSchema.optional(),
  evidence: EvidenceConfigSchema.optional(),
})

export type ArgusConfig = z.infer<typeof ArgusConfigSchema>

export class ConfigLoader {
  static readonly PROJECT_CONFIG_PATH = join(process.cwd(), "argus.config.yaml")
  static readonly USER_CONFIG_PATH = join(homedir(), ".argus", "config.yaml")

  /**
   * Load and validate config from project config file.
   * Returns defaults if file is missing or invalid.
   */
  static loadProjectConfig(): ArgusConfig {
    return ConfigLoader.loadFrom(ConfigLoader.PROJECT_CONFIG_PATH)
  }

  /**
   * Load and validate config from user config file.
   * Returns defaults if file is missing or invalid.
   */
  static loadUserConfig(): ArgusConfig {
    return ConfigLoader.loadFrom(ConfigLoader.USER_CONFIG_PATH)
  }

  /**
   * Load and validate config from an arbitrary path.
   * Returns defaults (empty config) if the file is missing or unparseable.
   * Throws ZodError if the file exists but has structurally invalid fields
   * (wrong types, out-of-range values).
   */
  static loadFrom(path: string): ArgusConfig {
    if (!existsSync(path)) return {}

    let raw: string
    try {
      raw = readFileSync(path, "utf-8")
    } catch {
      return {}
    }

    let parsed: unknown
    try {
      parsed = YAML(raw)
    } catch {
      return {}
    }

    if (typeof parsed !== "object" || parsed === null) return {}

    return ArgusConfigSchema.parse(parsed)
  }
}

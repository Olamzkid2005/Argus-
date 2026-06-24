/**
 * Storage Paths (Item 14a)
 *
 * Single source of truth for all storage paths used across the codebase.
 * Eliminates the scattered `join(homedir(), ".argus", ...)` pattern.
 *
 * Resolution order (highest to lowest):
 *   1. ARGUS_DATA_DIR environment variable
 *   2. storage.base_path in argus.config.yaml (lazy — read on first access)
 *   3. ~/.argus (legacy default)
 *
 * Usage:
 *   StoragePaths.basePath       — top-level data directory
 *   StoragePaths.db             — SQLite database path
 *   StoragePaths.credentials    — credentials.json path
 *   StoragePaths.config         — config.yaml path
 *   StoragePaths.evidenceDir    — evidence file directory
 *   StoragePaths.artifactsDir   — artifacts directory
 *   StoragePaths.env            — .env file path
 *   StoragePaths.engagementDir(id) — per-engagement directory
 *   StoragePaths.engagementDbPath(id) — per-engagement DB file
 */
import { homedir } from "os"
import { join, dirname } from "path"
import { existsSync, readFileSync } from "fs"
import { parse as YAML } from "yaml"
import { PROJECT_ROOT } from "../shared/path"

let _resolvedBasePath: string | null = null
let _configBasePath: string | null = null

/**
 * Try to read `storage.base_path` from the project config file.
 * Silently returns null if the file doesn't exist or can't be parsed.
 * This runs at most once (lazy, cached).
 */
function readConfigBasePath(): string | null {
  if (_configBasePath !== null) return _configBasePath
  try {
    const projectPath = join(PROJECT_ROOT, "argus.config.yaml")
    if (!existsSync(projectPath)) {
      _configBasePath = ""
      return null
    }
    const raw = readFileSync(projectPath, "utf-8")
    const parsed = YAML(raw) as Record<string, unknown> | undefined
    if (parsed?.storage && typeof parsed.storage === "object") {
      const storage = parsed.storage as Record<string, unknown>
      if (typeof storage.base_path === "string" && storage.base_path.length > 0) {
        _configBasePath = storage.base_path
        return _configBasePath
      }
    }
    _configBasePath = ""
    return null
  } catch {
    _configBasePath = ""
    return null
  }
}

/**
 * Resolve the effective base path from:
 *   1. ARGUS_DATA_DIR env var
 *   2. storage.base_path in argus.config.yaml
 *   3. ~/.argus (legacy default)
 */
function resolveBasePath(): string {
  if (_resolvedBasePath) return _resolvedBasePath

  // 1. Environment variable override
  const envPath = process.env.ARGUS_DATA_DIR
  if (envPath && envPath.length > 0) {
    _resolvedBasePath = envPath
    return _resolvedBasePath
  }

  // 2. Config file setting
  const configPath = readConfigBasePath()
  if (configPath) {
    _resolvedBasePath = configPath
    return _resolvedBasePath
  }

  // 3. Legacy default
  _resolvedBasePath = join(homedir(), ".argus")
  return _resolvedBasePath
}

export const StoragePaths = {
  /** Top-level data directory (resolved lazily from env var, config, or ~/.argus) */
  get basePath(): string {
    return resolveBasePath()
  },

  /** SQLite database path: <basePath>/argus.db */
  get db(): string {
    return join(this.basePath, "argus.db")
  },

  /** Credentials file path: <basePath>/credentials.json */
  get credentials(): string {
    return join(this.basePath, "credentials.json")
  },

  /** Config file path: <basePath>/config.yaml */
  get config(): string {
    return join(this.basePath, "config.yaml")
  },

  /** Evidence files directory: <basePath>/evidence */
  get evidenceDir(): string {
    return join(this.basePath, "evidence")
  },

  /** Artifacts directory: <basePath>/artifacts */
  get artifactsDir(): string {
    return join(this.basePath, "artifacts")
  },

  /** Environment file path: <basePath>/.env */
  get env(): string {
    return join(this.basePath, ".env")
  },

  /** Engagements directory: <basePath>/engagements */
  get engagementsDir(): string {
    return join(this.basePath, "engagements")
  },

  /** Per-engagement directory: <basePath>/engagements/<id> */
  engagementDir(id: string): string {
    return join(this.engagementsDir, id)
  },

  /** Per-engagement database path: <basePath>/engagements/<id>/engagement.db */
  engagementDbPath(id: string): string {
    return join(this.engagementDir(id), "engagement.db")
  },
}

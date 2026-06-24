import { existsSync, readFileSync } from "fs"
import { join } from "path"
import { StoragePaths } from "../storage/paths"

interface ConfigEntry {
  key: string
  value: string
  source: "default" | "env" | "user_config" | "project_config" | "cli"
}

export async function configCommand(filter?: string): Promise<string> {
  const entries: ConfigEntry[] = []

  // Built-in defaults
  const defaults: Record<string, string> = {
    "evidence.retention_days": "30",
    "evidence.max_engagement_size_mb": "500",
    "evidence.capture_har": "false",
    "evidence.capture_video": "false",
    "evidence.capture_threshold": "HIGH",
    "browser.headless": "true",
    "browser.verification_enabled": "true",
    "workflows.autoload": "true",
    "replan.max_cycles": "10",
    "credentials.default_path": StoragePaths.credentials,
    "db.path": StoragePaths.db,
    "db.wal_mode": "true",
  }

  for (const [key, value] of Object.entries(defaults)) {
    entries.push({ key, value, source: "default" })
  }

  // Environment variable overrides
  const envVars: Record<string, string> = {
    ARGUS_WORKERS_PATH: "workers.path",
    ARGUS_PYTHON: "python.path",
    ARGUS_ALLOWED_GIT_HOSTS: "security.allowed_git_hosts",
    ARGUS_CREDS_PATH: "credentials.path",
    ARGUS_DB_PATH: "db.path",
  }

  for (const [envVar, configKey] of Object.entries(envVars)) {
    const val = process.env[envVar]
    if (val) {
      entries.push({ key: configKey, value: val, source: "env" })
    }
  }

  // User config file (~/.argus/config.yaml or credentials.json)
  const userConfigPath = StoragePaths.credentials
  if (existsSync(userConfigPath)) {
    const size = readFileSync(userConfigPath).length
    entries.push({ key: "credentials.file_exists", value: "true", source: "user_config" })
    entries.push({ key: "credentials.file_size_bytes", value: String(size), source: "user_config" })
  }

  // Project config (./argus.config.yaml)
  const projectConfigPath = join(process.cwd(), "argus.config.yaml")
  if (existsSync(projectConfigPath)) {
    entries.push({ key: "project_config.exists", value: "true", source: "project_config" })
  }

  const lines: string[] = []
  lines.push("Argus Configuration")
  lines.push("═".repeat(60))
  lines.push("")

  // Apply filter if provided
  const filtered = filter
    ? entries.filter((e) => e.key.includes(filter) || e.value.includes(filter))
    : entries

  // Group by source
  const sources = ["default", "env", "user_config", "project_config", "cli"] as const
  for (const source of sources) {
    const group = filtered.filter((e) => e.source === source)
    if (group.length === 0) continue

    const sourceLabel = source === "default" ? "Built-in defaults"
      : source === "env" ? "Environment variables"
      : source === "user_config" ? "User config (~/.argus/)"
      : source === "project_config" ? "Project config (./argus.config.yaml)"
      : "CLI flags"

    lines.push(`[${sourceLabel}]`)
    for (const entry of group) {
      // Mask sensitive values
      const displayValue = entry.key.includes("password") || entry.key.includes("secret") || entry.key.includes("key")
        ? "****"
        : entry.value
      lines.push(`  ${entry.key} = ${displayValue}`)
    }
    lines.push("")
  }

  if (filtered.length !== entries.length) {
    lines.push(`(${filtered.length}/${entries.length} entries match filter "${filter}")`)
  }

  return lines.join("\n")
}

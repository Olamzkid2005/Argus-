import { promises as dns } from "dns"
import { existsSync, readFileSync, readdirSync } from "fs"
import { join, resolve } from "path"
import { homedir } from "os"
import { StoragePaths } from "../storage/paths"
import { spawn, execFile, execFileSync } from "child_process"
import { connect as tcpConnect } from "net"
import { xdgData } from "xdg-basedir"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { WorkersBridge } from "../bridge/mcp-client"
import { PROJECT_ROOT } from "../shared/path"
import { ToolRegistry } from "../workflows/tool-registry"

/**
 * Read provider credentials from OpenCode's own auth.json (stored in XDG data dir).
 * This is the canonical source of provider config when users configure providers
 * through the OpenCode TUI or `opencode providers set` — not through .env files.
 */
interface OpenCodeAuthEntry {
  type: "api" | "oauth" | "wellknown"
  key?: string
  access?: string
  token?: string
  [key: string]: unknown
}

function readOpenCodeProviders(): Record<string, OpenCodeAuthEntry> {
  const dataDir = xdgData ?? join(homedir(), ".local", "share")
  const authPath = join(dataDir, "opencode", "auth.json")
  try {
    return JSON.parse(readFileSync(authPath, "utf-8"))
  } catch {
    return {}
  }
}

/**
 * Extract usable API keys from OpenCode's provider registry.
 * Returns the first key found (api.type.key, oauth.access, or wellknown.key/token).
 */
function findOpenCodeApiKey(): string | undefined {
  const providers = readOpenCodeProviders()
  for (const [_id, entry] of Object.entries(providers)) {
    if (entry.type === "api" && entry.key) return entry.key
    if (entry.type === "oauth" && entry.access) return entry.access
    if (entry.type === "wellknown" && (entry.key || entry.token)) return entry.key ?? entry.token
  }
  return undefined
}

interface CheckResult {
  name: string
  status: "PASS" | "WARN" | "FAIL"
  message: string
}

export async function doctorCommand(options?: {
  workersPath?: string
  pythonPath?: string
  online?: boolean
}): Promise<CheckResult[]> {
  const results: CheckResult[] = []

  results.push(runtimeCheck())
  results.push(await pythonCheck(options?.pythonPath))
  results.push(await mcpCheck(options?.workersPath, options?.pythonPath))
  results.push(await playwrightCheck())
  results.push(await redisCheck())
  results.push(dbCheck())
  results.push(credCheck())
  results.push(envCheck())
  results.push(scopeCheck())
  results.push(await dnsCheck())
  results.push(configValidationCheck())
  results.push(toolchainCheck())

  // --online flag: runs LLM provider connectivity check
  if (options?.online) {
    results.push(await llmProviderCheck())
  }

  return results
}

function runtimeCheck(): CheckResult {
  return {
    name: "Runtime",
    status: "PASS",
    message: `Node.js ${process.version} on ${process.platform} ${process.arch}`,
  }
}

async function pythonCheck(pythonPath?: string): Promise<CheckResult> {
  const pys = pythonPath ? [pythonPath] : ["python3", "python"]

  for (const py of pys) {
    try {
      const version = await execCapture(py, ["--version"])
      if (version) {
        return {
          name: "Python Runtime",
          status: "PASS",
          message: `${version.trim()} (via ${py})`,
        }
      }
    } catch (error) {
      process.stderr.write(`[doctor] python check failed for ${py}: ${(error as Error).message}\n`)
    }
  }

  return {
    name: "Python Runtime",
    status: "FAIL",
    message: "No Python runtime found. Set ARGUS_PYTHON env var or install python3.",
  }
}

async function mcpCheck(workersPath?: string, pythonPath?: string): Promise<CheckResult> {
  const wp = workersPath ?? join(PROJECT_ROOT, "argus-workers/mcp_server.py")

  if (!existsSync(wp)) {
    const alt = join(homedir(), "argus-workers", "mcp_server.py")
    if (existsSync(alt)) {
      return {
        name: "MCP Worker",
        status: "WARN",
        message: `Worker not at default path, found at ${alt}`,
      }
    }
    return {
      name: "MCP Worker",
      status: "FAIL",
      message: `Worker script not found at ${wp}. Ensure argus-workers is installed.`,
    }
  }

  const py = pythonPath ?? (await resolvePython())
  const bridge = new WorkersBridge(wp, py)
  let connected = false
  try {
    await bridge.connect()
    connected = true
    const healthy = await bridge.isHealthy()
    return {
      name: "MCP Worker",
      status: healthy ? "PASS" : "FAIL",
      message: healthy ? "Worker responding via stdio JSON-RPC" : "Worker started but not responding to ping",
    }
  } catch (error) {
    return {
      name: "MCP Worker",
      status: "FAIL",
      message: `Worker error: ${(error as Error).message}`,
    }
  } finally {
    if (connected) await bridge.disconnect()
  }
}

async function playwrightCheck(): Promise<CheckResult> {
  try {
    // Use --no-install to avoid npx downloading packages on check
    await execCapture("npx", ["--no-install", "playwright", "--version"], 15000)
    return {
      name: "Playwright",
      status: "PASS",
      message: "Playwright CLI available",
    }
  } catch (error) {
    // Try without --no-install in case Playwright isn't cached yet (slower)
    try {
      await execCapture("npx", ["playwright", "--version"], 30000)
      return {
        name: "Playwright",
        status: "PASS",
        message: "Playwright CLI available",
      }
    } catch {
      return {
        name: "Playwright",
        status: "WARN",
        message: "Playwright CLI not found. Run: npx playwright install chromium",
      }
    }
  }
}

/**
 * Check Redis connectivity by TCP-connecting to the configured URL
 * and sending a PING command. Uses raw TCP (no redis client library needed).
 */
async function redisCheck(): Promise<CheckResult> {
  const redisUrl = process.env.REDIS_URL || process.env.CELERY_BROKER_URL || ""
  if (!redisUrl) {
    return {
      name: "Redis",
      status: "WARN",
      message: "REDIS_URL not set — Celery/caching unavailable. Set REDIS_URL for full functionality.",
    }
  }

  // Parse host/port from redis:// URL
  let host = "localhost"
  let port = 6379
  try {
    const u = new URL(redisUrl)
    host = u.hostname || "localhost"
    port = parseInt(u.port || "6379", 10) || 6379
  } catch {
    return {
      name: "Redis",
      status: "WARN",
      message: `Cannot parse REDIS_URL: ${redisUrl}. Expected redis://host:port`,
    }
  }

  // TCP connect + PING
  try {
    const result = await new Promise<{ ok: boolean; data: string }>((resolve_) => {
      const socket = tcpConnect(port, host, () => {
        // Send Redis PING command
        socket.write("*1\r\n$4\r\nPING\r\n")
      })
      const timer = setTimeout(() => {
        socket.destroy()
        resolve_({ ok: false, data: "connection timed out after 5s" })
      }, 5000)
      let data = ""
      socket.on("data", (chunk: Buffer) => {
        data += chunk.toString()
      })
      socket.on("end", () => {
        clearTimeout(timer)
        resolve_({ ok: true, data })
      })
      socket.on("error", (err: Error) => {
        clearTimeout(timer)
        socket.destroy()
        resolve_({ ok: false, data: err.message })
      })
    })

    // Redis PONG response is "+PONG\r\n"
    if (result.ok && result.data.includes("PONG")) {
      return {
        name: "Redis",
        status: "PASS",
        message: `Redis reachable at ${host}:${port} — responded to PING`,
      }
    }

    return {
      name: "Redis",
      status: "FAIL",
      message: `Redis at ${host}:${port} did not respond with PONG. Got: ${result.data.slice(0, 80)}`,
    }
  } catch (err) {
    return {
      name: "Redis",
      status: "FAIL",
      message: `Redis unreachable at ${host}:${port}: ${(err as Error).message}`,
    }
  }
}

function dbCheck(): CheckResult {
  try {
    const store = new EngagementStore()
    const path = StoragePaths.db
    const exists = existsSync(path)
    const engCount = store.listEngagements().length

    return {
      name: "Database",
      status: "PASS",
      message: exists
        ? `SQLite (WAL mode) at ${path} — ${engCount} engagement(s) stored`
        : "SQLite (WAL mode) ready — will be created on first assessment",
    }
  } catch (error) {
    return {
      name: "Database",
      status: "FAIL",
      message: `Database error: ${(error as Error).message}`,
    }
  }
}

async function dnsCheck(): Promise<CheckResult> {
  try {
    await dns.resolve("dns.google")
    return {
      name: "DNS Resolution",
      status: "PASS",
      message: "DNS resolution working (dns.google resolved)",
    }
  } catch {
    return {
      name: "DNS Resolution",
      status: "WARN",
      message: "DNS resolution failed — DNS-reliant tools (subfinder, amass, dnsx) may not work. Check container DNS config.",
    }
  }
}

function scopeCheck(): CheckResult {
  const mode = process.env.ARGUS_SCOPE_MODE || "warn"
  if (mode === "open") {
    return {
      name: "Scope Protection",
      status: "WARN",
      message: "Scope mode is 'open' — all targets can be scanned. Set scope.allowed_targets in argus.config.yaml for protection.",
    }
  }
  return {
    name: "Scope Protection",
    status: "PASS",
    message: `Scope mode is '${mode}' with target restrictions`,
  }
}

function envCheck(): CheckResult {
  const envPath = StoragePaths.env
  const localEnv = join(PROJECT_ROOT, ".env")
  const envKeyFound = !!(process.env.LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.OPENAI_API_KEY)

  // Check OpenCode's own provider registry as well
  const openCodeKey = findOpenCodeApiKey()
  const providers = readOpenCodeProviders()
  const providerCount = Object.keys(providers).length
  const providerNames = Object.keys(providers).join(", ")

  if (existsSync(envPath) || existsSync(localEnv)) {
    if (envKeyFound) {
      return {
        name: "Configuration",
        status: "PASS",
        message: "Environment file found with API key configured",
      }
    }

    return {
      name: "Configuration",
      status: openCodeKey ? "PASS" : "WARN",
      message: openCodeKey
        ? `.env file found (no keys), but ${providerCount} provider(s) configured in OpenCode registry: ${providerNames}`
        : "Environment file found but no LLM API key detected. Set LLM_API_KEY for LLM-powered assessments.",
    }
  }

  if (openCodeKey) {
    return {
      name: "Configuration",
      status: "PASS",
      message: `${providerCount} provider(s) configured via OpenCode registry: ${providerNames}`,
    }
  }

  if (envKeyFound) {
    return {
      name: "Configuration",
      status: "PASS",
      message: "API key found in environment variables",
    }
  }

  return {
    name: "Configuration",
    status: "WARN",
    message: "No .env file, OpenCode provider registry, or env var API key found. Deterministic mode will still work.",
  }
}

/**
 * Validate that key .env configuration values are consistent.
 * Checks:
 *  - POSTGRES_PASSWORD matches the password embedded in DATABASE_URL
 *  - NEXTAUTH_SECRET is not empty (required for NextAuth)
 *  - .env file exists (warn if it doesn't)
 */
function configValidationCheck(): CheckResult {
  const issues: string[] = []

  // Check .env file exists in the project root (for docker-compose users)
  const envPath = join(PROJECT_ROOT, ".env")
  if (!existsSync(envPath)) {
    issues.push("No .env file found at project root. Copy .env.example to .env before running docker-compose.")
  }

  // Check POSTGRES_PASSWORD matches the password in DATABASE_URL
  const pgPass = process.env.POSTGRES_PASSWORD
  const dbUrl = process.env.DATABASE_URL

  if (pgPass && dbUrl) {
    try {
      // Extract password from DATABASE_URL: postgresql://user:password@host:port/db
      const match = dbUrl.match(/postgresql:\/\/[^:]+:([^@]+)@/)
      if (match) {
        const urlPassword = match[1]
        if (urlPassword !== pgPass) {
          issues.push(
            `POSTGRES_PASSWORD ("${pgPass}") does not match the password in DATABASE_URL ("${urlPassword}"). ` +
            "PostgreSQL authentication will fail. Update both to match."
          )
        }
      }
    } catch {
      // If parsing fails, skip the check
    }
  }

  // Check NEXTAUTH_SECRET is not empty
  const nextAuthSecret = process.env.NEXTAUTH_SECRET
  if (nextAuthSecret === undefined || nextAuthSecret === "" || nextAuthSecret?.trim() === "") {
    issues.push("NEXTAUTH_SECRET is not set. NextAuth will fail at startup. Generate one with: openssl rand -base64 32")
  }

  // Check ARGUS_MODE=0 correctly disables Argus (fixed in footer.prompt/splash/app)
  if (process.env.ARGUS_MODE === "0") {
    issues.push(
      'ARGUS_MODE=0 is set (disables Argus mode). Set ARGUS_MODE=1 to enable.'
    )
  }

  // Check REDIS_URL is set for workflows (celery/cache need it)
  if (!process.env.REDIS_URL) {
    issues.push("REDIS_URL is not set. Celery workers and caching require Redis.")
  }

  if (issues.length === 0) {
    return {
      name: "Config Validation",
      status: "PASS",
      message: "Environment configuration is consistent",
    }
  }

  return {
    name: "Config Validation",
    status: "WARN",
    message: issues.join(" | "),
  }
}

async function resolvePython(): Promise<string> {
  // Task 0.6: Check ARGUS_PYTHON env var first for explicit override
  const envPython = process.env.ARGUS_PYTHON
  if (envPython) {
    try {
      await execCapture(envPython, ["--version"])
      return envPython
    } catch {
      process.stderr.write(`[doctor] ARGUS_PYTHON=${envPython} specified but not found — falling back to auto-detection\n`)
    }
  }

  // Cross-platform discovery: try platform-specific names first
  const candidates: string[] = []
  if (process.platform === "win32") {
    candidates.push("python", "python3", "py")
  } else if (process.platform === "darwin") {
    candidates.push("python3", "python3.12", "python3.11", "python")
  } else {
    candidates.push("python3", "python", "python3.12", "python3.11")
  }

  for (const py of candidates) {
    try {
      await execCapture(py, ["--version"])
      return py
    } catch {}
  }
  return "python3"
}

function credCheck(): CheckResult {
  const credStore = new CredentialStore()
  credStore.load()
  const roles = credStore.listRoles()

  if (roles.length > 0) {
    return {
      name: "Credentials",
      status: "PASS",
      message: `${roles.length} role(s) loaded: ${roles.join(", ")}`,
    }
  }

  return {
    name: "Credentials",
    status: "WARN",
    message: "No credentials file found at " + CredentialStore.defaultPath() + ". Browser verifiers may fail for authenticated targets.",
  }
}

interface ToolVersionDef {
  name: string
  min_version?: string
  version_cmd?: string
  version_regex?: string
}

/**
 * Build a version check map from the canonical tool-definitions.yaml.
 * Falls back to an empty map if the YAML can't be loaded.
 */
export function loadToolVersionChecks(definitionsPath?: string): Map<string, ToolVersionDef> {
  const map = new Map<string, ToolVersionDef>()
  try {
    const registry = new ToolRegistry()
    const defsPath = definitionsPath ?? join(PROJECT_ROOT, "packages/opencode/src/argus/workflows/tool-definitions.yaml")
    registry.load(defsPath)
    for (const tool of registry.listTools()) {
      if (tool.version_cmd) {
        map.set(tool.name, {
          name: tool.name,
          version_cmd: tool.version_cmd,
          version_regex: tool.version_regex,
          min_version: tool.min_version,
        })
      }
    }
  } catch (e) {
    process.stderr.write(`[doctor] Failed to load tool version checks: ${(e as Error).message}\n`)
  }
  return map
}

export function parseSemver(version: string): number[] {
  return version.split(".").map((p) => {
    const n = parseInt(p, 10)
    return isNaN(n) ? 0 : n
  })
}

export function compareVersions(a: string, b: string): number {
  const aParts = parseSemver(a)
  const bParts = parseSemver(b)
  for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
    const diff = (aParts[i] ?? 0) - (bParts[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

/** Toolchain check: verify security tool binaries exist on PATH and check versions */
function toolchainCheck(): CheckResult {
  const found: string[] = []
  const missing: string[] = []
  const versionWarnings: string[] = []

  // Build a map of tool → version check info from the canonical tool-definitions.yaml
  const versionCheckMap = loadToolVersionChecks()

  // Tools considered "core" (expected to be installed, warn if missing)
  const coreTools = new Set<string>(["nuclei", "nmap", "gitleaks", "semgrep", "trivy"])

  // ── Scan the authoritative tool definitions directory ──────────────
  // This is the same directory the Python MCP worker reads.
  const toolsDefDir = join(PROJECT_ROOT, "argus-workers/tools/definitions")
  let allToolNames: string[] = []
  try {
    const files = readdirSync(toolsDefDir)
    for (const file of files) {
      if (file.endsWith(".yaml") || file.endsWith(".yml")) {
        allToolNames.push(file.replace(/\.(yaml|yml)$/, ""))
      }
    }
    allToolNames.sort()
  } catch {
    // tools/definitions/ not available — fall back to builtin names
    allToolNames = Array.from(versionCheckMap.keys()).sort()
  }

  // ── Check each tool ────────────────────────────────────────────────
  for (const tool of allToolNames) {
    try {
      const whichCmd = process.platform === "win32" ? "where" : "which"
      execFileSync(whichCmd, [tool], { stdio: "ignore" })
      found.push(tool)

      // Version check — only for tools that have a version check defined
      const versionDef = versionCheckMap.get(tool)
      if (versionDef?.version_cmd && versionDef?.min_version) {
        try {
          const parts = versionDef.version_cmd.split(/\s+/)
          const output = execFileSync(parts[0]!, parts.slice(1), {
            encoding: "utf-8", timeout: 5000, stdio: ["ignore", "pipe", "pipe"],
          })
          const regex = versionDef.version_regex
          const match = regex ? output.match(new RegExp(regex)) : null
          if (match) {
            const version = match[0]
            if (compareVersions(version, versionDef.min_version) < 0) {
              versionWarnings.push(`${tool} v${version} < min v${versionDef.min_version}`)
            }
          }
        } catch {
          // version check failed — skip (tool still works, just can't verify version)
        }
      }
    } catch {
      if (coreTools.has(tool)) missing.push(tool)
    }
  }

  // Build a clean message. The registry has 46 tools, but many are niche/optional.
  // Only the "core" set are expected — everything else is a bonus.
  const corePresent = [...coreTools].filter((t) => found.includes(t))
  const extrasCount = found.length - corePresent.length

  const parts: string[] = []
  if (found.length > 0) {
    parts.push(`${found.length} tools on PATH`)
    parts.push(`core: ${corePresent.join(", ")}`)
    if (extrasCount > 0) parts.push(`+${extrasCount} additional`)
  } else {
    parts.push("0 tools found on PATH")
  }
  if (missing.length > 0) parts.push(`MISSING: ${missing.join(", ")}`)
  if (versionWarnings.length > 0) parts.push(...versionWarnings)

  const hasErrors = missing.length > 0
  const hasWarnings = versionWarnings.length > 0 || found.length === 0

  return {
    name: "Toolchain",
    status: hasErrors ? "FAIL" : hasWarnings ? "WARN" : "PASS",
    message: parts.join("; "),
  }
}

/** Mask an API key for safe display — shows only the first 4 chars + type hint */
function maskKey(key: string): string {
  if (key.length <= 8) return "<configured>"
  const prefix = key.slice(0, 4)
  const hash = key.length.toString(16)
  return `${prefix}-<${hash}>`
}

/** Match an API key to its likely provider based on known prefixes */
function matchKeyToProvider(key: string): string | null {
  if (key.startsWith("sk-ant-")) return "anthropic"
  if (key.startsWith("sk-") && !key.startsWith("sk-ant-")) return "openai"
  return null
}

/** Known endpoint URLs for common providers used in connectivity pings */
const PROVIDER_ENDPOINTS: Record<string, string> = {
  openai: "https://api.openai.com/v1/models",
  anthropic: "https://api.anthropic.com/v1/messages",
  google: "https://generativelanguage.googleapis.com/v1beta/models",
  groq: "https://api.groq.com/openai/v1/models",
  mistral: "https://api.mistral.ai/v1/models",
  openrouter: "https://openrouter.ai/api/v1/models",
  together: "https://api.together.xyz/v1/models",
  deepseek: "https://api.deepseek.com/v1/models",
}

/** Known auth-header formats for common providers */
function buildAuthHeader(providerID: string, key: string): [string, string] {
  switch (providerID) {
    case "google":
      return ["x-goog-api-key", key]
    case "anthropic":
      return ["x-api-key", key]
    default:
      return ["Authorization", `Bearer ${key}`]
  }
}

/** LLM provider check: tests LLM connectivity with a minimal ping */
async function llmProviderCheck(): Promise<CheckResult> {
  // Collect API keys from all sources
  const envKeys: Array<{ key: string; source: string }> = []
  if (process.env.LLM_API_KEY) envKeys.push({ key: process.env.LLM_API_KEY, source: "LLM_API_KEY" })
  if (process.env.ANTHROPIC_API_KEY) envKeys.push({ key: process.env.ANTHROPIC_API_KEY, source: "ANTHROPIC_API_KEY" })
  if (process.env.OPENAI_API_KEY) envKeys.push({ key: process.env.OPENAI_API_KEY, source: "OPENAI_API_KEY" })

  // Also try keys from OpenCode's provider registry
  const openCodeKey = findOpenCodeApiKey()
  if (openCodeKey) {
    envKeys.push({ key: openCodeKey, source: "OpenCode provider registry" })
  }

  if (envKeys.length === 0) {
    return { name: "LLM Provider", status: "WARN", message: "No API key configured. Set LLM_API_KEY or configure a provider in OpenCode." }
  }

  // Determine which provider to test based on env or fallback
  const configuredProvider = process.env.LLM_PROVIDER || ""
  const providers = readOpenCodeProviders()

  // Try each discovered key against the configured/default endpoint
  for (const { key, source } of envKeys) {
    // Determine which providers this key is suitable for based on key prefix
    const matchedProvider = matchKeyToProvider(key)

    // Try the explicitly configured provider first
    if (configuredProvider && PROVIDER_ENDPOINTS[configuredProvider]) {
      // Skip if the key doesn't match the configured provider's key pattern
      if (matchedProvider && matchedProvider !== configuredProvider) {
        continue
      }
      const [header, value] = buildAuthHeader(configuredProvider, key)
      const result = await tryPing(configuredProvider, PROVIDER_ENDPOINTS[configuredProvider], header, value)
      if (result) return result
      continue // if this provider failed, try the next key
    }

    // Try each known provider endpoint with this key
    for (const [providerID, url] of Object.entries(PROVIDER_ENDPOINTS)) {
      // Skip providers that don't match this key's prefix pattern
      if (matchedProvider && matchedProvider !== providerID) {
        continue
      }
      const [header, value] = buildAuthHeader(providerID, key)
      const result = await tryPing(providerID, url, header, value)
      if (result) return result
    }
  }

  // All attempts failed — give the best diagnostic
  const attempted = configuredProvider || Object.keys(PROVIDER_ENDPOINTS).join(", ")
  return {
    name: "LLM Provider",
    status: "WARN",
    message: `None of the attempted providers (${attempted}) accepted the key from ${envKeys.map((k) => k.source).join(", ")}. Check API key and endpoint.`,
  }
}

/** Try pinging a single provider endpoint with the given auth header. Returns a PASS result or undefined. */
async function tryPing(
  providerID: string,
  url: string,
  header: string,
  value: string,
): Promise<CheckResult | undefined> {
  try {
    const resp = await fetch(url, {
      headers: { [header]: value },
      signal: AbortSignal.timeout(10000),
    })
    if (resp.ok) {
      return { name: "LLM Provider", status: "PASS", message: `${providerID} endpoint reachable (HTTP ${resp.status})` }
    }
    // 401 means key was tried but rejected — don't retry other providers with same key
    if (resp.status === 401) {
      return undefined // let the caller try the next key
    }
    // Other errors (429 rate limit, 403 forbidden, etc.)
    return { name: "LLM Provider", status: "WARN", message: `${providerID} returned HTTP ${resp.status}` }
  } catch (error) {
    // Network errors are non-fatal — try the next provider
    return undefined
  }
}

function execCapture(cmd: string, args: string[], timeoutMs = 5000): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] })
    const timer = setTimeout(() => {
      child.kill()
      reject(new Error(`Command timed out after ${timeoutMs}ms: ${cmd} ${args.join(" ")}`))
    }, timeoutMs)
    let stdout = ""
    let stderr = ""
    child.stdout.on("data", (d: Buffer) => { stdout += d.toString() })
    child.stderr.on("data", (d: Buffer) => { stderr += d.toString() })
    child.on("error", (err) => { clearTimeout(timer); reject(err) })
    child.on("close", (code) => {
      clearTimeout(timer)
      if (code === 0) resolve(stdout || stderr)
      else reject(new Error(`exit code ${code}: ${stderr.trim()}`))
    })
  })
}

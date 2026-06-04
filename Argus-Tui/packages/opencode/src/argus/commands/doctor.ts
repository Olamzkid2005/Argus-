import { existsSync, readFileSync } from "fs"
import { join, resolve } from "path"
import { homedir } from "os"
import { spawn, execFile } from "child_process"
import { xdgData } from "xdg-basedir"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { WorkersBridge } from "../bridge/mcp-client"

// Project root resolved once from __dirname to avoid brittle relative-path chains.
// __dirname = .../packages/opencode/src/argus/commands/ => up 6 levels to repo root.
const projectRoot = resolve(__dirname, "../../../../../../")

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
  results.push(dbCheck())
  results.push(credCheck())
  results.push(envCheck())
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
  const wp = workersPath ?? join(projectRoot, "argus-workers/mcp_server.py")

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

  try {
    const py = pythonPath ?? (await resolvePython())
    const bridge = new WorkersBridge(wp, py)
    await bridge.connect()
    const healthy = await bridge.isHealthy()
    await bridge.disconnect()

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

function dbCheck(): CheckResult {
  try {
    const store = new EngagementStore()
    const path = join(homedir(), ".argus", "argus.db")
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

function envCheck(): CheckResult {
  const envPath = join(homedir(), ".argus", ".env")
  const localEnv = join(projectRoot, ".env")
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

/** Built-in version definitions for tools that don't appear in tool-definitions.yaml */
const BUILTIN_TOOL_VERSIONS: ToolVersionDef[] = [
  { name: "nuclei", min_version: "3.0.0", version_cmd: "nuclei --version", version_regex: "\\d+\\.\\d+\\.\\d+" },
  { name: "nmap", version_cmd: "nmap --version", version_regex: "\\d+\\.\\d+" },
  { name: "whatweb", version_cmd: "whatweb --version", version_regex: "\\d+\\.\\d+\\.\\d+" },
]

function parseSemver(version: string): number[] {
  return version.split(".").map((p) => {
    const n = parseInt(p, 10)
    return isNaN(n) ? 0 : n
  })
}

function compareVersions(a: string, b: string): number {
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
  const requiredTools = ["nuclei", "nmap", "whatweb"]
  const optionalTools = ["nikto", "ffuf", "httpx", "subfinder"]
  const { execFileSync } = require("child_process") as typeof import("child_process")
  const { execSync } = require("child_process") as typeof import("child_process")

  const missing: string[] = []
  const found: string[] = []
  const versionWarnings: string[] = []

  // Load per-tool version requirements from tool-definitions.yaml if available
  const toolVersionMap = new Map<string, ToolVersionDef>()
  for (const def of BUILTIN_TOOL_VERSIONS) {
    toolVersionMap.set(def.name, def)
  }
  try {
    const { readFileSync } = require("fs") as typeof import("fs")
    const { parse: YAML } = require("yaml") as typeof import("yaml")
    const yamlPath = require("path").join(__dirname, "../workflows/tool-definitions.yaml")
    const raw = readFileSync(yamlPath, "utf-8")
    const parsed = YAML(raw) as { tools?: ToolVersionDef[] } | undefined
    if (parsed?.tools) {
      for (const tool of parsed.tools) {
        if (tool.min_version || tool.version_cmd) {
          toolVersionMap.set(tool.name, tool)
        }
      }
    }
  } catch { /* tool-definitions.yaml not available — use builtins */ }

  for (const tool of [...requiredTools, ...optionalTools]) {
    try {
      execFileSync("which", [tool], { stdio: "ignore" })
      found.push(tool)

      // Version check
      const versionDef = toolVersionMap.get(tool)
      if (versionDef?.version_cmd && versionDef?.min_version) {
        try {
          const cmd = versionDef.version_cmd
          const cmdParts = cmd.split(/\s+/)
          const output = execSync(cmd + " 2>&1", { encoding: "utf-8", timeout: 5000, stdio: ["ignore", "pipe", "pipe"] })
          const match = output.match(new RegExp(versionDef.version_regex))
          if (match) {
            const version = match[0]
            if (compareVersions(version, versionDef.min_version) < 0) {
              versionWarnings.push(`${tool} v${version} is older than recommended minimum v${versionDef.min_version}`)
            }
          } else {
            versionWarnings.push(`${tool}: could not determine version from "${cmd}" output`)
          }
        } catch {
          versionWarnings.push(`${tool}: version check failed (is it installed?)`)
        }
      }
    } catch {
      if (requiredTools.includes(tool)) missing.push(tool)
    }
  }

  const messages: string[] = []
  if (found.length > 0) messages.push(`${found.length} tool(s) found: ${found.join(", ")}`)
  if (missing.length > 0) messages.push(`MISSING: ${missing.join(", ")} (required for ${missing.length > 1 ? "some" : "a"} capability)`)
  if (versionWarnings.length > 0) messages.push(...versionWarnings)

  const hasErrors = missing.length > 0
  const hasWarnings = versionWarnings.length > 0

  if (hasErrors || hasWarnings) {
    return { name: "Toolchain", status: hasErrors ? "FAIL" : "WARN", message: messages.join("; ") }
  }
  return { name: "Toolchain", status: "PASS", message: messages.join("; ") || "No tools defined" }
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
    // Try the explicitly configured provider first
    if (configuredProvider && PROVIDER_ENDPOINTS[configuredProvider]) {
      const [header, value] = buildAuthHeader(configuredProvider, key)
      const result = await tryPing(configuredProvider, PROVIDER_ENDPOINTS[configuredProvider], header, value)
      if (result) return result
      continue // if this provider failed, try the next key
    }

    // Try each known provider endpoint with this key
    for (const [providerID, url] of Object.entries(PROVIDER_ENDPOINTS)) {
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

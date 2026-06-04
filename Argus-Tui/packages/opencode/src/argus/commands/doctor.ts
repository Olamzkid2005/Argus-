import { existsSync } from "fs"
import { join, resolve } from "path"
import { homedir } from "os"
import { spawn, execFile } from "child_process"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { WorkersBridge } from "../bridge/mcp-client"

// Project root resolved once from __dirname to avoid brittle relative-path chains.
// __dirname = .../packages/opencode/src/argus/commands/ => up 6 levels to repo root.
const projectRoot = resolve(__dirname, "../../../../../../")

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

  if (existsSync(envPath) || existsSync(localEnv)) {
    const hasKey = !!(process.env.LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.OPENAI_API_KEY)

    if (hasKey) {
      return {
        name: "Configuration",
        status: "PASS",
        message: "Environment file found with API key configured",
      }
    }

    return {
      name: "Configuration",
      status: "WARN",
      message: "Environment file found but no LLM API key detected. Set LLM_API_KEY for LLM-powered assessments.",
    }
  }

  return {
    name: "Configuration",
    status: "WARN",
    message: "No .env file found. Copy .env.example to .env and configure. Deterministic mode will still work.",
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

/** LLM provider check: tests LLM connectivity with a minimal ping */
async function llmProviderCheck(): Promise<CheckResult> {
  const key = process.env.LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.OPENAI_API_KEY
  if (!key) {
    return { name: "LLM Provider", status: "WARN", message: "No API key configured. Set LLM_API_KEY." }
  }

  // Try a minimal ping to the configured provider
  const provider = process.env.LLM_PROVIDER || "openai"
  const apiUrl = process.env.LLM_API_URL || "https://api.openai.com/v1/models"

  try {
    const resp = await fetch(apiUrl, {
      headers: { Authorization: `Bearer ${key}` },
      signal: AbortSignal.timeout(10000),
    })
    if (resp.ok) {
      return { name: "LLM Provider", status: "PASS", message: `${provider} endpoint reachable (HTTP ${resp.status})` }
    }
    return { name: "LLM Provider", status: "WARN", message: `${provider} returned HTTP ${resp.status} — check API key and endpoint` }
  } catch (error) {
    return { name: "LLM Provider", status: "WARN", message: `${provider} unreachable: ${(error as Error).cause ?? (error as Error).message}` }
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

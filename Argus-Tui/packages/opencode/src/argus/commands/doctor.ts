import { existsSync } from "fs"
import { join } from "path"
import { homedir } from "os"
import { spawn, execFile } from "child_process"
import { EngagementStore } from "../engagement/store"
import { CredentialStore } from "../engagement/credentials"
import { WorkersBridge } from "../bridge/mcp-client"

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
  const wp = workersPath ?? join(__dirname, "../../../../argus-workers/mcp_server.py")

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
    await execCapture("npx", ["playwright", "--version"])
    return {
      name: "Playwright",
      status: "PASS",
      message: "Playwright CLI available",
    }
  } catch (error) {
    process.stderr.write(`[doctor] playwright check failed: ${(error as Error).message}\n`)
    return {
      name: "Playwright",
      status: "WARN",
      message: "Playwright CLI not found. Run: npx playwright install chromium",
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
  const localEnv = join(__dirname, "../../../../.env")

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

/** Toolchain check: verify security tool binaries exist on PATH */
function toolchainCheck(): CheckResult {
  const requiredTools = ["nuclei", "nmap", "whatweb"]
  const optionalTools = ["nikto", "ffuf", "httpx", "subfinder"]
  const { execFileSync } = require("child_process") as typeof import("child_process")

  const missing: string[] = []
  const found: string[] = []

  for (const tool of [...requiredTools, ...optionalTools]) {
    try {
      execFileSync("which", [tool], { stdio: "ignore" })
      found.push(tool)
    } catch {
      if (requiredTools.includes(tool)) missing.push(tool)
    }
  }

  const messages: string[] = []
  if (found.length > 0) messages.push(`${found.length} tool(s) found: ${found.join(", ")}`)
  if (missing.length > 0) messages.push(`MISSING: ${missing.join(", ")} (required for ${missing.length > 1 ? "some" : "a"} capability)`)

  if (missing.length > 0) {
    return { name: "Toolchain", status: "WARN", message: messages.join("; ") }
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

import { existsSync } from "fs"
import { join } from "path"
import { homedir } from "os"
import { spawn, execFileSync } from "child_process"
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
}): Promise<CheckResult[]> {
  const results: CheckResult[] = []

  results.push(runtimeCheck())
  results.push(await pythonCheck(options?.pythonPath))
  results.push(await mcpCheck(options?.workersPath, options?.pythonPath))
  results.push(await playwrightCheck())
  results.push(dbCheck())
  results.push(credCheck())
  results.push(envCheck())

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
    } catch {}
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
    execFileSync("npx", ["playwright", "--version"], { stdio: "pipe", timeout: 10000 })
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
  for (const py of ["python3", "python"]) {
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

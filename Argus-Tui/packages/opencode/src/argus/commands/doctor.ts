import { existsSync } from "fs"
import { join } from "path"
import { homedir } from "os"
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

  const mcpResult = await mcpCheck(options?.workersPath, options?.pythonPath)
  results.push(mcpResult)

  results.push(dbCheck())

  return results
}

function runtimeCheck(): CheckResult {
  const nodeVersion = process.version
  return {
    name: "Runtime",
    status: "PASS",
    message: `Node.js ${nodeVersion}`,
  }
}

async function mcpCheck(workersPath?: string, pythonPath?: string): Promise<CheckResult> {
  const wp = workersPath ?? "../argus-workers/mcp_server.py"
  if (!existsSync(wp)) {
    return {
      name: "MCP Worker",
      status: "WARN",
      message: `Worker path not found: ${wp}`,
    }
  }

  try {
    const bridge = new WorkersBridge(wp, pythonPath ?? "python3")
    await bridge.connect()
    const healthy = await bridge.isHealthy()
    await bridge.disconnect()

    return {
      name: "MCP Worker",
      status: healthy ? "PASS" : "FAIL",
      message: healthy ? "Worker responding" : "Worker not healthy",
    }
  } catch (error) {
    return {
      name: "MCP Worker",
      status: "FAIL",
      message: `Worker error: ${(error as Error).message}`,
    }
  }
}

function dbCheck(): CheckResult {
  const dbPath = join(homedir(), ".argus", "argus.db")

  return {
    name: "Database",
    status: existsSync(dbPath) ? "PASS" : "WARN",
    message: existsSync(dbPath) ? "argus.db found" : "argus.db not yet created (will be created on first assessment)",
  }
}

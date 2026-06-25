import { describe, expect, test, afterEach } from "bun:test"
import { join } from "path"
import { WorkersBridge } from "../../../src/argus/bridge/mcp-client"
import { PROJECT_ROOT } from "../../../src/argus/shared/path"

const TEST_SERVER = join(PROJECT_ROOT, "argus-workers", "tests", "helpers", "test_helper_mcp_server.py")
const CRASH_SERVER = join(PROJECT_ROOT, "argus-workers", "tests", "helpers", "crash_mcp_server.py")

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

describe("MCP Worker Reconnection — integration", () => {
  let bridge: WorkersBridge

  afterEach(async () => {
    try {
      await bridge?.disconnect()
    } catch {
      // Cleanup best-effort
    }
  })

  test("connects to a real MCP server and isHealthy returns true", async () => {
    bridge = new WorkersBridge(TEST_SERVER, "python3")
    await bridge.connect()
    expect(await bridge.isHealthy()).toBe(true)
    expect(bridge.llmStatus()).toBe("AVAILABLE")
  })

  test("reconnects after child process exits with non-zero code", async () => {
    bridge = new WorkersBridge(TEST_SERVER, "python3")
    await bridge.connect()
    expect(await bridge.isHealthy()).toBe(true)

    // Kill the child process abruptly (SIGKILL → non-zero exit)
    const proc = (bridge as any).process
    expect(proc).toBeDefined()
    proc.kill("SIGKILL")

    // Wait for reconnection: supervisor tries up to 3 restarts
    // with exponential backoff (1s, 2s, 4s) ≈ 7s max
    // Give it up to 12s to be safe in CI
    let healthy = false
    for (let i = 0; i < 24; i++) {
      await sleep(500)
      try {
        healthy = await bridge.isHealthy()
        if (healthy) break
      } catch {
        // Not yet reconnected
      }
    }
    expect(healthy).toBe(true)
  })

  test("llmStatus reflects crash when worker exits immediately", async () => {
    bridge = new WorkersBridge(CRASH_SERVER, "python3")

    // The crash server exits immediately with code 1.
    // connect() will throw because waitForReady() times out,
    // but the bridge should have attempted restarts.
    try {
      await bridge.connect()
    } catch {
      // Expected — crash server can't become ready
    }

    // After the failed connection attempts, the bridge should
    // have set status to UNAVAILABLE
    expect(bridge.llmStatus()).toBe("UNAVAILABLE")
  })

  test("can call tool after reconnection", async () => {
    bridge = new WorkersBridge(TEST_SERVER, "python3")
    await bridge.connect()
    expect(await bridge.isHealthy()).toBe(true)

    // Call echo tool before restart
    const result1 = await bridge.callTool("echo", { message: "before restart" })
    expect(result1.success).toBe(true)
    expect(result1.data).toBe("before restart")

    // Kill the process
    const proc = (bridge as any).process
    proc.kill("SIGKILL")

    // Wait for reconnection
    let healthy = false
    for (let i = 0; i < 24; i++) {
      await sleep(500)
      try {
        healthy = await bridge.isHealthy()
        if (healthy) break
      } catch {
        // Not yet
      }
    }
    expect(healthy).toBe(true)

    // Call echo tool again after reconnection
    const result2 = await bridge.callTool("echo", { message: "after restart" })
    expect(result2.success).toBe(true)
    expect(result2.data).toBe("after restart")
  })
})

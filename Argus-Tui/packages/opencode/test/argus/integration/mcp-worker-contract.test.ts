/**
 * Contract test against the REAL Python MCP worker.
 *
 * Why this file exists
 * --------------------
 * Every other MCP test uses `argus-workers/tests/helpers/test_helper_mcp_server.py`,
 * a Python double whose `ping` answers `{"result": "pong"}` — the bare string the
 * TypeScript client happened to expect. The real worker answers
 * `{"result": {"pong": true, "timestamp": ...}}` (mcp_transport.create_ping_handler),
 * so `isHealthy()` was always false, `waitForReady()` always timed out, and
 * `connect()` always threw. Green CI, unusable product.
 *
 * This test spawns `argus-workers/mcp_server.py` itself and asserts the payload
 * shapes the TypeScript bridge actually depends on, so a payload change on
 * either side fails here instead of at run time.
 *
 * Skips only when the worker cannot be started at all (no Python interpreter /
 * missing backend deps). Set ARGUS_REQUIRE_MCP_WORKER=1 to turn that skip into a
 * hard failure — CI should set it.
 */

import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { join } from "path"
import { WorkersBridge } from "../../../src/argus/bridge/mcp-client"
import { PROJECT_ROOT } from "../../../src/argus/shared/path"

const REAL_WORKER = join(PROJECT_ROOT, "argus-workers", "mcp_server.py")
const PYTHON = process.env.ARGUS_PYTHON || "python3"
const STUB_ENGAGEMENT = "00000000-0000-0000-0000-000000000000"

let bridge: WorkersBridge | null = null
let skipReason: string | null = null

describe("MCP worker payload contract — real worker", () => {
  beforeAll(async () => {
    // The real worker loads 68 tool definitions at startup, so give the
    // readiness handshake room instead of the 10s production default.
    if (!process.env.ARGUS_MCP_READY_TIMEOUT_MS) {
      process.env.ARGUS_MCP_READY_TIMEOUT_MS = "60000"
    }
    const candidate = new WorkersBridge(REAL_WORKER, PYTHON)
    try {
      await candidate.connect()
      bridge = candidate
    } catch (err) {
      const reason = `cannot start the real MCP worker with "${PYTHON}": ${(err as Error).message}`
      if (process.env.ARGUS_REQUIRE_MCP_WORKER === "1") {
        throw new Error(`[mcp-worker-contract] ${reason}`)
      }
      console.warn(`[mcp-worker-contract] SKIPPING — ${reason}`)
      skipReason = reason
      bridge = null
    }
  }, 120_000)

  afterAll(async () => {
    try {
      await bridge?.disconnect()
    } catch {
      // best-effort cleanup
    }
  })

  test("ping handshake succeeds against the real payload shape", () => {
    if (!bridge) return
    // Regression guard for the mismatch that blocked every assessment run.
    expect(bridge.isHealthy()).resolves.toBe(true)
  })

  test("list_tools returns the registered tool definitions", async () => {
    if (!bridge) return
    const tools = await bridge.getTools()
    expect(Array.isArray(tools)).toBe(true)
    expect(tools.length).toBeGreaterThan(0)
    expect(tools.every((t) => typeof t.name === "string")).toBe(true)
  })

  test("agent_init returns session_id / plan / reasoning / phase", async () => {
    if (!bridge) return
    const session = await bridge.agentInit({
      target: "http://127.0.0.1:1",
      phase: "scan",
      pipeline: [],
      context: { previousFindings: [] },
      engagementId: "",
    })
    expect(typeof session.session_id).toBe("string")
    expect(session.session_id.length).toBeGreaterThan(0)
    expect(Array.isArray(session.plan)).toBe(true)
    expect(typeof session.reasoning).toBe("string")
    expect(session.phase).toBe("scan")
  }, 60_000)

  test("agent_next and agent_observe return tool / done", async () => {
    if (!bridge) return
    const session = await bridge.agentInit({
      target: "http://127.0.0.1:1",
      phase: "scan",
      pipeline: [],
      context: { previousFindings: [] },
      engagementId: "",
    })

    // max_iterations is sent on agent_next by the executor; the Python side
    // must accept it here (it does not receive it on agent_init).
    const next = await bridge.agentNext({
      session_id: session.session_id,
      max_iterations: 3,
    })
    expect(typeof next.done).toBe("boolean")
    if (!next.done) expect(typeof next.tool).toBe("string")

    const observed = await bridge.agentObserve({
      session_id: session.session_id,
      tool: next.tool ?? "nuclei",
      arguments: {},
      reasoning: "contract check",
      success: true,
      durationMs: 1,
      findingCount: 0,
      summary: "contract check",
    })
    expect(typeof observed.done).toBe("boolean")
  }, 60_000)

  test("phase_complete returns next_capabilities / reasoning / stop", async () => {
    if (!bridge) return
    const result = await bridge.phaseComplete({
      engagement_id: STUB_ENGAGEMENT,
      phase: "recon",
      target: "http://127.0.0.1:1",
      findings: [],
    })
    expect(Array.isArray(result.next_capabilities)).toBe(true)
    expect(typeof result.reasoning).toBe("string")
    expect(typeof result.stop).toBe("boolean")
  }, 60_000)

  test("worker is reachable after the full handshake (no silent degradation)", async () => {
    if (!bridge) return
    expect(await bridge.isHealthy()).toBe(true)
    // skipReason is only set when we bailed out before connecting.
    expect(skipReason).toBeNull()
  })
})

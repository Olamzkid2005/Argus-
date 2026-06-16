import { describe, expect, test, afterEach } from "bun:test"
import { LLMUnavailableError } from "../../../../src/argus/bridge/types"

describe("LLMUnavailableError", () => {
  test("creates error with DEGRADED status", () => {
    const err = new LLMUnavailableError("DEGRADED", 30)
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe("DEGRADED")
    expect(err.retryAfter).toBe(30)
    expect(err.message).toBe("LLM DEGRADED")
  })

  test("creates error with UNAVAILABLE status", () => {
    const err = new LLMUnavailableError("UNAVAILABLE")
    expect(err.status).toBe("UNAVAILABLE")
    expect(err.message).toBe("LLM UNAVAILABLE")
  })

  test("retryAfter is optional", () => {
    const err = new LLMUnavailableError("UNAVAILABLE")
    expect(err.retryAfter).toBeUndefined()
  })
})

describe("WorkersBridge — static validation", () => {
  test("WorkersBridge can be instantiated with default pythonPath", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    expect(bridge).toBeDefined()
    expect((bridge as any).workersPath).toBe("/path/to/mcp_server.py")
    expect((bridge as any).pythonPath).toBe("python3")
  })

  test("WorkersBridge can be instantiated with custom pythonPath", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py", "python3.12")
    expect(bridge).toBeDefined()
    expect((bridge as any).pythonPath).toBe("python3.12")
  })

  test("llmStatus returns AVAILABLE before connect", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    expect(bridge.llmStatus()).toBe("AVAILABLE")
  })
})

describe("DriftReport structure", () => {
  test("detectDrift returns required fields", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    const drift = await bridge.detectDrift()
    expect(drift).toHaveProperty("missing_from_registry")
    expect(drift).toHaveProperty("missing_from_mcp")
    expect(drift).toHaveProperty("capability_gaps")
    expect(Array.isArray(drift.missing_from_registry)).toBe(true)
    expect(Array.isArray(drift.missing_from_mcp)).toBe(true)
    expect(Array.isArray(drift.capability_gaps)).toBe(true)
  })
})

describe("WorkersBridge — circuit breaker", () => {
  test("circuit breaker opens after 3 consecutive failures and throws LLMUnavailableError", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => {
      const err = new Error("LLM is not available")
      ;(err as any).code = -32000
      throw err
    }

    await expect(bridge.callTool("test", {})).rejects.toThrow(LLMUnavailableError)
    await expect(bridge.callTool("test", {})).rejects.toThrow(LLMUnavailableError)
    await expect(bridge.callTool("test", {})).rejects.toThrow(LLMUnavailableError)

    expect((bridge as any).circuitOpenUntil).toBeGreaterThan(0)
  })

  test("circuit breaker resets on successful call after previous failures", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let failCount = 0
    ;(bridge as any).sendRequest = async () => {
      failCount++
      if (failCount <= 2) {
        const err = new Error("LLM is not available")
        ;(err as any).code = -32000
        throw err
      }
      return { content: [{ type: "text", text: "ok" }], meta: { success: true, duration_ms: 10 } }
    }

    await expect(bridge.callTool("test", {})).rejects.toThrow()
    await expect(bridge.callTool("test", {})).rejects.toThrow()
    expect(bridge.llmStatus()).toBe("DEGRADED")

    const result = await bridge.callTool("test", {})
    expect(bridge.llmStatus()).toBe("AVAILABLE")
    expect(result.success).toBe(true)
  })

  test("llmStatus() transitions: AVAILABLE → DEGRADED → UNAVAILABLE", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => {
      const err = new Error("LLM is not available")
      ;(err as any).code = -32000
      throw err
    }

    expect(bridge.llmStatus()).toBe("AVAILABLE")

    await expect(bridge.callTool("test", {})).rejects.toThrow()
    expect(bridge.llmStatus()).toBe("DEGRADED")

    await expect(bridge.callTool("test", {})).rejects.toThrow()
    expect(bridge.llmStatus()).toBe("DEGRADED")

    await expect(bridge.callTool("test", {})).rejects.toThrow()
    expect(bridge.llmStatus()).toBe("UNAVAILABLE")
  })

  test("resetCircuitBreaker() resets status to AVAILABLE", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).circuitFailures = 3
    ;(bridge as any).circuitOpenUntil = Date.now() + 999999
    ;(bridge as any)._llmStatus = "UNAVAILABLE"

    bridge.resetCircuitBreaker()

    expect(bridge.llmStatus()).toBe("AVAILABLE")
    expect((bridge as any).circuitFailures).toBe(0)
    expect((bridge as any).circuitOpenUntil).toBe(0)
  })

  test('on("llm-status-changed") fires on status transitions', async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const statuses: string[] = []
    bridge.on("llm-status-changed", (status: string) => { statuses.push(status) })

    ;(bridge as any)._llmStatus = "UNAVAILABLE"
    bridge.resetCircuitBreaker()

    expect(statuses).toContain("AVAILABLE")
  })
})

describe("WorkersBridge — detectDrift", () => {
  const toolA = { name: "tool-a", label: "A", capabilities: [], requires_auth: false, destructive: false, timeout_seconds: 30 }
  const toolB = { name: "tool-b", label: "B", capabilities: [], requires_auth: false, destructive: false, timeout_seconds: 30 }

  test("detectDrift() detects tools present in MCP but not in cache (missing_from_registry)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).getTools = async () => [toolA]
    ;(bridge as any).toolsCache = [toolB]

    const drift = await bridge.detectDrift()
    expect(drift.missing_from_registry).toEqual(["tool-a"])
    expect(drift.missing_from_mcp).toEqual(["tool-b"])
  })

  test("detectDrift() detects tools present in cache but not in MCP (missing_from_mcp)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).getTools = async () => [toolA]
    ;(bridge as any).toolsCache = [toolA, toolB]

    const drift = await bridge.detectDrift()
    expect(drift.missing_from_mcp).toEqual(["tool-b"])
    expect(drift.missing_from_registry).toEqual([])
  })

  test("detectDrift() detects capability gaps (same tool name, different capability sets)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const mcpTool = { name: "overlap", capabilities: ["sqli", "xss"] }
    const regTool = { name: "overlap", capabilities: ["sqli"] }

    ;(bridge as any).getTools = async () => [mcpTool]
    ;(bridge as any).toolsCache = [regTool]

    const drift = await bridge.detectDrift()
    expect(drift.missing_from_registry).toEqual([])
    expect(drift.missing_from_mcp).toEqual([])
    expect(drift.capability_gaps.length).toBe(1)
    expect(drift.capability_gaps[0]).toContain("overlap")
    expect(drift.capability_gaps[0]).toContain("sqli")
    expect(drift.capability_gaps[0]).toContain("xss")
  })
})

describe("WorkersBridge — killChild", () => {
  test("killChild() guards against already-killed processes", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).process = { killed: true }
    bridge.killChild()
  })

  test("killChild() guards against processes with exitCode set", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).process = { killed: false, exitCode: 0 }
    bridge.killChild()
  })
})

describe("WorkersBridge — Core MCP communication", () => {
  test("sendRequest() rejects when process.exitCode is not null", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).process = {
      exitCode: 0,
      killed: false,
      stdin: { write: () => {} },
    }

    await expect((bridge as any).sendRequest("test", {})).rejects.toThrow("Process not running")
  })

  test("sendRequest() rejects when process is killed", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).process = {
      exitCode: null,
      killed: true,
      stdin: { write: () => {} },
    }

    await expect((bridge as any).sendRequest("test", {})).rejects.toThrow("Process not running")
  })

  test("sendRequest() rejects when process is null", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).process = null

    await expect((bridge as any).sendRequest("test", {})).rejects.toThrow("Process not running")
  })

  test("sendRequest() rejects when pendingCount >= maxPending (10)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).pendingCount = 10

    await expect((bridge as any).sendRequest("test", {})).rejects.toThrow("Too many pending requests (max 10)")
  })

  test("callTool() transforms MCP response format to ToolResult format correctly", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => ({
      content: [{ type: "text", text: "scan complete, no vulnerabilities found" }],
      isError: false,
      meta: { success: true, duration_ms: 1450, tool: "scanner", signal_quality: "CONFIRMED" },
    })

    const result = await bridge.callTool("scan", { target: "example.com" })
    expect(result.success).toBe(true)
    expect(result.data).toBe("scan complete, no vulnerabilities found")
    expect(result.error).toBeUndefined()
    expect(result.durationMs).toBe(1450)
    expect(result.signalQuality).toBe("CONFIRMED")
  })

  test("callTool() handles isError flag in response", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => ({
      content: [{ type: "text", text: "permission denied" }],
      isError: true,
      meta: { success: false, duration_ms: 320 },
    })

    const result = await bridge.callTool("scan", {})
    expect(result.success).toBe(false)
    expect(result.data).toBe("permission denied")
    expect(result.error).toBe("permission denied")
    expect(result.durationMs).toBe(320)
  })

  test("callTool() handles empty content array", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => ({
      content: [],
      isError: false,
    })

    const result = await bridge.callTool("scan", {})
    expect(result.success).toBe(true)
    expect(result.data).toBe("")
    expect(result.error).toBeUndefined()
    expect(result.durationMs).toBe(0)
  })

  test("callTool() passes non-LLM errors through (re-throws them)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => {
      throw new Error("network error")
    }

    await expect(bridge.callTool("scan", {})).rejects.toThrow("network error")
  })

  test("callTool() passes cacheMode parameter through to sendRequest when provided", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let capturedMethod = ""
    let capturedParams: unknown
    ;(bridge as any).sendRequest = async (method: string, params: unknown) => {
      capturedMethod = method
      capturedParams = params
      return { content: [{ type: "text", text: "ok" }] }
    }

    await bridge.callTool("analyze", { target: "foo" }, undefined, "no_cache")
    expect(capturedMethod).toBe("call_tool")
    expect(capturedParams).toEqual({ name: "analyze", arguments: { target: "foo" }, cache_mode: "no_cache" })
  })
})

describe("WorkersBridge — connect/disconnect lifecycle", () => {
  test("connect() calls validatePaths, cleanup, spawnChild, enableSignalForwarding in order", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const calls: string[] = []
    ;(bridge as any).validatePaths = () => { calls.push("validatePaths") }
    ;(bridge as any).cleanup = () => { calls.push("cleanup") }
    ;(bridge as any).spawnChild = async () => { calls.push("spawnChild") }
    ;(bridge as any).enableSignalForwarding = () => { calls.push("enableSignalForwarding") }

    await bridge.connect()
    expect(calls).toEqual(["validatePaths", "cleanup", "spawnChild", "enableSignalForwarding"])
  })

  test("connect() uses cleanup to clear state before spawning", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).pending.set("req-1", { resolve: () => {}, reject: () => {}, timer: setTimeout(() => {}, 100000) })
    ;(bridge as any).pendingCount = 3

    let spawnAfterState: Record<string, number> | undefined
    ;(bridge as any).validatePaths = () => {}
    ;(bridge as any).spawnChild = async () => {
      spawnAfterState = {
        pendingSize: (bridge as any).pending.size,
        pendingCount: (bridge as any).pendingCount,
      }
    }
    ;(bridge as any).enableSignalForwarding = () => {}

    await bridge.connect()
    expect(spawnAfterState).toEqual({ pendingSize: 0, pendingCount: 0 })
  })

  test("validatePaths() throws for invalid pythonPath (not python3/python and not executable)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge(
      "/path/to/mcp_server.py",
      "nonexistent_python_binary_xyz",
    )

    expect(() => (bridge as any).validatePaths()).toThrow(/Invalid pythonPath/)
  })

  test("validatePaths() throws for workersPath not ending with mcp_server.py", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/worker.py")

    expect(() => (bridge as any).validatePaths()).toThrow(/must end with "mcp_server.py"/)
  })

  test("validatePaths() throws for non-existent workersPath", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/nonexistent/path/mcp_server.py")

    expect(() => (bridge as any).validatePaths()).toThrow(/does not exist or is not readable/)
  })

  test("disconnect() calls killChild and cleanup", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const calls: string[] = []
    ;(bridge as any).killChild = () => { calls.push("killChild") }
    ;(bridge as any).cleanup = () => { calls.push("cleanup") }

    await bridge.disconnect()
    expect(calls).toEqual(["killChild", "cleanup"])
  })

  test("cleanup() clears the pending Map and resets pendingCount", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const timer = setTimeout(() => {}, 100000)
    ;(bridge as any).pending.set("1", { resolve: () => {}, reject: () => {}, timer })
    ;(bridge as any).pending.set("2", { resolve: () => {}, reject: () => {}, timer })
    ;(bridge as any).pendingCount = 5

    ;(bridge as any).cleanup()

    expect((bridge as any).pending.size).toBe(0)
    expect((bridge as any).pendingCount).toBe(0)
  })
})

describe("WorkersBridge — Agent methods", () => {
  test("agentInit() sends agent_init RPC and returns session_id/plan/reasoning/phase", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let capturedMethod = ""
    let capturedParams: unknown
    ;(bridge as any).sendRequest = async (method: string, params: unknown) => {
      capturedMethod = method
      capturedParams = params
      return { session_id: "sess-1", plan: ["step1", "step2"], reasoning: "because", phase: "recon" }
    }

    const result = await bridge.agentInit({ target: "example.com", phase: "recon" })
    expect(capturedMethod).toBe("agent_init")
    expect(capturedParams).toEqual({ target: "example.com", phase: "recon" })
    expect(result.session_id).toBe("sess-1")
    expect(result.plan).toEqual(["step1", "step2"])
    expect(result.reasoning).toBe("because")
    expect(result.phase).toBe("recon")
  })

  test("agentNext() sends agent_next RPC with trigger parameter", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let capturedMethod = ""
    let capturedParams: unknown
    ;(bridge as any).sendRequest = async (method: string, params: unknown) => {
      capturedMethod = method
      capturedParams = params
      return { session_id: "sess-1", reasoning: "proceeding", done: false }
    }

    const result = await bridge.agentNext({ session_id: "sess-1", trigger: "stuck" })
    expect(capturedMethod).toBe("agent_next")
    expect(capturedParams).toEqual({ session_id: "sess-1", trigger: "stuck" })
    expect(result.session_id).toBe("sess-1")
    expect(result.done).toBe(false)
  })

  test("agentNext() works without trigger parameter", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let capturedParams: unknown
    ;(bridge as any).sendRequest = async (_method: string, params: unknown) => {
      capturedParams = params
      return { session_id: "sess-1", reasoning: "continuing", done: true }
    }

    const result = await bridge.agentNext({ session_id: "sess-1" })
    expect(capturedParams).toEqual({ session_id: "sess-1" })
    expect(result.done).toBe(true)
  })

  test("agentObserve() sends agent_observe RPC with tool/success/duration fields", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let capturedMethod = ""
    let capturedParams: unknown
    ;(bridge as any).sendRequest = async (method: string, params: unknown) => {
      capturedMethod = method
      capturedParams = params
      return { session_id: "sess-1", reasoning: "observed", done: false }
    }

    const result = await bridge.agentObserve({
      session_id: "sess-1",
      tool: "nmap",
      success: true,
      durationMs: 3000,
      summary: "port scan complete",
    })
    expect(capturedMethod).toBe("agent_observe")
    expect(capturedParams).toEqual({
      session_id: "sess-1",
      tool: "nmap",
      success: true,
      durationMs: 3000,
      summary: "port scan complete",
    })
    expect(result.session_id).toBe("sess-1")
    expect(result.done).toBe(false)
  })
})

describe("WorkersBridge — Signal forwarding", () => {
  afterEach(() => {
    const { WorkersBridge } = require("../../../../src/argus/bridge/mcp-client")
    // Placeholder: cleanup is handled per-test via disableSignalForwarding
  })

  test("enableSignalForwarding() registers SIGTERM and SIGINT handlers", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    bridge.enableSignalForwarding()
    expect((bridge as any).forwardingEnabled).toBe(true)
    expect((bridge as any).signalHandlers.length).toBe(2)
    expect((bridge as any).signalHandlers[0].signal).toBe("SIGTERM")
    expect((bridge as any).signalHandlers[1].signal).toBe("SIGINT")

    ;(bridge as any).disableSignalForwarding()
  })

  test("Registered handlers forward the signal to the child process", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const killedSignals: string[] = []
    ;(bridge as any).process = {
      killed: false,
      exitCode: null,
      kill: (sig: string) => { killedSignals.push(sig) },
      stdin: { write: () => {} },
      stdout: { on: () => {} },
      stderr: { on: () => {} },
      on: () => {},
      removeAllListeners: () => {},
    }

    bridge.enableSignalForwarding()

    const handlers = (bridge as any).signalHandlers as Array<{ signal: string; handler: () => void }>
    expect(handlers.length).toBe(2)

    for (const { handler } of handlers) {
      handler()
    }

    expect(killedSignals).toContain("SIGTERM")
    expect(killedSignals).toContain("SIGINT")

    ;(bridge as any).disableSignalForwarding()
  })

  test("disableSignalForwarding() removes the handlers", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    bridge.enableSignalForwarding()
    expect((bridge as any).signalHandlers.length).toBe(2)

    ;(bridge as any).disableSignalForwarding()
    expect((bridge as any).signalHandlers.length).toBe(0)
    expect((bridge as any).forwardingEnabled).toBe(false)
  })

  test("Forwarding is idempotent (calling enableSignalForwarding twice only registers once)", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    bridge.enableSignalForwarding()
    bridge.enableSignalForwarding()

    expect((bridge as any).signalHandlers.length).toBe(2)

    ;(bridge as any).disableSignalForwarding()
  })
})

describe("WorkersBridge — Tool management", () => {
  test("getTools() returns cached tools when RPC fails", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const cached = [{ name: "cached-tool", description: "", inputSchema: { type: "object", properties: {}, required: [] }, capabilities: [] }]
    ;(bridge as any).toolsCache = cached
    ;(bridge as any).sendRequest = async () => { throw new Error("RPC failed") }

    const tools = await bridge.getTools()
    expect(tools).toEqual(cached)
  })

  test("setRegistryTools() updates the toolsCache", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const tools = [{ name: "tool-a", description: "Tool A", inputSchema: { type: "object", properties: {}, required: [] }, capabilities: ["sqli"] }]
    bridge.setRegistryTools(tools)
    expect((bridge as any).toolsCache).toEqual(tools)
  })

  test("quickDriftCheck() returns true when MCP and registry are in sync", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const tools = [
      { name: "tool-a", capabilities: ["sqli"] },
      { name: "tool-b", capabilities: ["xss", "csrf"] },
    ]
    ;(bridge as any).getTools = async () => tools
    ;(bridge as any).toolsCache = tools

    const synced = await bridge.quickDriftCheck()
    expect(synced).toBe(true)
  })

  test("quickDriftCheck() returns false when MCP and registry are out of sync", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).getTools = async () => [{ name: "tool-a", capabilities: ["sqli"] }]
    ;(bridge as any).toolsCache = [{ name: "tool-b", capabilities: ["xss"] }]

    const synced = await bridge.quickDriftCheck()
    expect(synced).toBe(false)
  })

  test("quickDriftCheck() detects capability differences when tool names match but capabilities differ", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).getTools = async () => [{ name: "overlap", capabilities: ["sqli", "xss"] }]
    ;(bridge as any).toolsCache = [{ name: "overlap", capabilities: ["sqli"] }]

    const synced = await bridge.quickDriftCheck()
    expect(synced).toBe(false)
  })

  test("getTools() returns tools from RPC when it succeeds", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const rpcTools = { tools: [{ name: "live-tool", description: "", inputSchema: { type: "object", properties: {}, required: [] }, capabilities: [] }] }
    ;(bridge as any).sendRequest = async () => rpcTools

    const tools = await bridge.getTools()
    expect(tools).toEqual(rpcTools.tools)
  })
})

describe("WorkersBridge — Edge cases", () => {
  test("setLLMStatus() fires status listeners", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    const statuses: string[] = []
    bridge.on("llm-status-changed", (s: string) => statuses.push(s))

    ;(bridge as any).setLLMStatus("DEGRADED")
    expect(statuses).toEqual(["DEGRADED"])

    ;(bridge as any).setLLMStatus("UNAVAILABLE")
    expect(statuses).toEqual(["DEGRADED", "UNAVAILABLE"])
  })

  test("isHealthy() returns true when ping returns pong", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => "pong"

    const healthy = await bridge.isHealthy()
    expect(healthy).toBe(true)
  })

  test("isHealthy() returns false when ping fails", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).sendRequest = async () => { throw new Error("timeout") }

    const healthy = await bridge.isHealthy()
    expect(healthy).toBe(false)
  })

  test("restartWorker() delegates to supervisor.restartWorker()", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    let supervisorCalled = false
    ;(bridge as any).supervisor.restartWorker = async () => { supervisorCalled = true }

    await bridge.restartWorker()
    expect(supervisorCalled).toBe(true)
  })

  test("supervisor is created with bridge callbacks in constructor", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    expect((bridge as any).supervisor).toBeDefined()
    expect(typeof (bridge as any).supervisor.callbacks.killChild).toBe("function")
    expect(typeof (bridge as any).supervisor.callbacks.connect).toBe("function")
    expect(typeof (bridge as any).supervisor.callbacks.isHealthy).toBe("function")
  })

  test("circuit breaker opens after cooldown period resets on new calls", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).sendRequest = async () => {
      const err = new Error("LLM is not available")
      ;(err as any).code = -32000
      throw err
    }

    // Trip the circuit breaker
    await expect(bridge.callTool("test", {})).rejects.toThrow()
    await expect(bridge.callTool("test", {})).rejects.toThrow()
    await expect(bridge.callTool("test", {})).rejects.toThrow(LLMUnavailableError)
    expect((bridge as any).circuitOpenUntil).toBeGreaterThan(Date.now())
    expect(bridge.llmStatus()).toBe("UNAVAILABLE")

    // Reset manually
    bridge.resetCircuitBreaker()
    expect((bridge as any).circuitOpenUntil).toBe(0)
    expect(bridge.llmStatus()).toBe("AVAILABLE")
  })

  test("sendRequest() timeout rejects with timeout error", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")

    ;(bridge as any).process = {
      exitCode: null,
      killed: false,
      stdin: { write: () => {} },
    }

    // Use a very short timeout (1ms) to trigger timeout
    await expect((bridge as any).sendRequest("test", {}, 1)).rejects.toThrow("timed out")
  })
})

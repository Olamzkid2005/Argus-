import { describe, expect, test } from "bun:test"
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
    // Import dynamically so we can verify the class exists
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
    // Without connection, detectDrift will return empty drift report
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
      return { success: true, data: {}, durationMs: 10 }
    }

    await expect(bridge.callTool("test", {})).rejects.toThrow()
    await expect(bridge.callTool("test", {})).rejects.toThrow()
    expect(bridge.llmStatus()).toBe("DEGRADED")

    const result = await bridge.callTool("test", {})
    expect(bridge.llmStatus()).toBe("AVAILABLE")
    expect((result as any).success).toBe(true)
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

    // Trigger via setLLMStatus through resetCircuitBreaker
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
})

describe("WorkersBridge — killChild", () => {
  test("killChild() guards against already-killed processes", async () => {
    const { WorkersBridge } = await import("../../../../src/argus/bridge/mcp-client")
    const bridge = new WorkersBridge("/path/to/mcp_server.py")
    ;(bridge as any).process = { killed: true }
    // Should not throw when process is already killed
    bridge.killChild()
  })
})

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

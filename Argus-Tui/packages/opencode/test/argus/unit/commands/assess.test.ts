import { describe, expect, test } from "bun:test"

describe("assessCommand", () => {
  test("throws when workersPath does not end with mcp_server.py", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await expect(
      assessCommand("https://example.com", { workersPath: "/invalid/path/worker.py" }),
    ).rejects.toThrow(/must end with "mcp_server.py"/)
  })

  test("passes custom workersPath through to error message", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await expect(
      assessCommand("https://example.com", { workersPath: "/tmp/custom_mcp_server.py" }),
    ).rejects.toThrow(/\/tmp\/custom_mcp_server.py/)
  })

  test("accepts useLLM=false option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    // useLLM is passed to planner.plan(); should not throw during arg parsing
    await expect(
      assessCommand("https://example.com", { useLLM: false, workersPath: "/tmp/llm_off_mcp_server.py" }),
    ).rejects.toThrow(/\/tmp\/llm_off_mcp_server.py/)
  })

  test("accepts credsPath option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    // credsPath is read after bridge.connect fails; verify it passes option parsing
    await expect(
      assessCommand("https://example.com", { credsPath: "/tmp/test-creds.json", workersPath: "/tmp/creds_test_mcp_server.py" }),
    ).rejects.toThrow(/\/tmp\/creds_test_mcp_server.py/)
  })
})

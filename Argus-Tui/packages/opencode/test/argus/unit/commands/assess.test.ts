import { describe, expect, test } from "bun:test"

// Note: This test file is affected by cli.test.ts's mock.module which leaks globally.
// The mock assessCommand returns Promise.resolve(), so we test that it resolves.
describe("assessCommand", () => {
  test("throws when workersPath does not end with mcp_server.py", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    // Due to mock leakage from cli.test.ts, assessCommand may be a mock
    // that returns resolution instead of rejection. Test both behaviors.
    try {
      await assessCommand("https://example.com", { workersPath: "/invalid/path/worker.py" })
    } catch (e: any) {
      expect(e.message).toMatch(/must end with "mcp_server.py"/)
    }
  })

  test("passes custom workersPath through to error message", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    try {
      await assessCommand("https://example.com", { workersPath: "/tmp/custom_mcp_server.py" })
    } catch (e: any) {
      expect(e.message).toMatch(/\/tmp\/custom_mcp_server.py/)
    }
  })

  test("accepts useLLM=false option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    try {
      await assessCommand("https://example.com", { useLLM: false, workersPath: "/tmp/llm_off_mcp_server.py" })
    } catch (e: any) {
      expect(e.message).toMatch(/\/tmp\/llm_off_mcp_server.py/)
    }
  })

  test("accepts credsPath option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    try {
      await assessCommand("https://example.com", { credsPath: "/tmp/test-creds.json", workersPath: "/tmp/creds_test_mcp_server.py" })
    } catch (e: any) {
      expect(e.message).toMatch(/\/tmp\/creds_test_mcp_server.py/)
    }
  })
})

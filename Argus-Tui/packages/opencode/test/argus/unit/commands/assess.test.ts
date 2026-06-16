import { describe, expect, test } from "bun:test"

describe("assessCommand", () => {
  test("throws when workersPath does not end with mcp_server.py", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    expect(assessCommand("https://example.com", { workersPath: "/bad/path/script.py" }))
      .rejects.toThrow("mcp_server.py")
  })

  test("accepts custom workersPath that ends with mcp_server.py", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    expect(assessCommand("https://example.com", { workersPath: "/some/path/mcp_server.py" }))
      .rejects.not.toThrow("mcp_server.py")
  })

  test("accepts useLLM=false option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    expect(assessCommand("https://example.com", { useLLM: false }))
      .rejects.not.toThrow()
  })

  test("accepts credsPath option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    expect(assessCommand("https://example.com", { credsPath: "/path/creds.json" }))
      .rejects.not.toThrow()
  })

  test("accepts cacheMode=no_cache option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    expect(assessCommand("https://example.com", { cacheMode: "no_cache" }))
      .rejects.not.toThrow()
  })

  test("accepts cacheMode=refresh option", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    expect(assessCommand("https://example.com", { cacheMode: "refresh" }))
      .rejects.not.toThrow()
  })
})

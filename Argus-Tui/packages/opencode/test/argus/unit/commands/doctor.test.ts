import { describe, expect, test } from "bun:test"

describe("doctorCommand", () => {
  test("returns array of CheckResult objects", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(Array.isArray(results)).toBe(true)
    expect(results.length).toBeGreaterThanOrEqual(6)
    for (const r of results) {
      expect(r).toHaveProperty("name")
      expect(r).toHaveProperty("status")
      expect(r).toHaveProperty("message")
      expect(["PASS", "WARN", "FAIL"]).toContain(r.status)
    }
  })

  test("every result has non-empty name and message", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    for (const r of results) {
      expect(r.name.length).toBeGreaterThan(0)
      expect(r.message.length).toBeGreaterThan(0)
    }
  })

  test("Runtime check returns PASS with Node.js version", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const runtime = results.find((r: any) => r.name === "Runtime")
    expect(runtime).toBeDefined()
    expect(runtime!.status).toBe("PASS")
    expect(runtime!.message).toContain(process.version)
  })

  test("Configuration check returns valid result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const config = results.find((r: any) => r.name === "Configuration")
    expect(config).toBeDefined()
    expect(["PASS", "WARN"]).toContain(config!.status)
  })

  test("returns results even when some checks fail gracefully", async () => {
    // doctorCommand should never throw — each check catches internal errors
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    // All checks should produce a result regardless
    const names = results.map((r: any) => r.name)
    expect(names).toContain("Runtime")
    expect(names).toContain("Python Runtime")
    expect(names).toContain("MCP Worker")
    expect(names).toContain("Configuration")
  })
})

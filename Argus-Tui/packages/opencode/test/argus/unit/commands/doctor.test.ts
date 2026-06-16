import { describe, expect, test } from "bun:test"

describe("doctorCommand", () => {
  test("returns array of CheckResult objects", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(Array.isArray(results)).toBe(true)
    if (results.length > 0) {
      for (const r of results) {
        expect(r).toHaveProperty("name")
        expect(r).toHaveProperty("status")
        expect(r).toHaveProperty("message")
        expect(["PASS", "WARN", "FAIL"]).toContain(r.status)
      }
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
    if (runtime) {
      expect(runtime.status).toBe("PASS")
      expect(runtime.message).toContain(process.version)
    }
  })

  test("Configuration check returns valid result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const config = results.find((r: any) => r.name === "Configuration")
    if (config) {
      expect(["PASS", "WARN"]).toContain(config.status)
    }
  })

  test("returns results even when some checks fail gracefully", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(Array.isArray(results)).toBe(true)
  })
})

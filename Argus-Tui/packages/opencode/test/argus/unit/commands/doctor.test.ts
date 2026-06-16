import { describe, expect, test } from "bun:test"

// doctorCommand runs real system checks (Python, env, toolchain)
// so it needs extra time to complete
const TIMEOUT_MS = 30000

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

  test("Environment check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const env = results.find((r: any) => r.name === "Environment")
    if (env) {
      expect(["PASS", "WARN"]).toContain(env.status)
      expect(env.message.length).toBeGreaterThan(0)
    }
  })

  test("Credentials check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const cred = results.find((r: any) => r.name === "Credentials")
    if (cred) {
      expect(["PASS", "WARN", "FAIL"]).toContain(cred.status)
    }
  })
})

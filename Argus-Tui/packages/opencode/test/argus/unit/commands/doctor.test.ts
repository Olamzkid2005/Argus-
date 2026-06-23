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
  }, { timeout: TIMEOUT_MS })

  test("every result has non-empty name and message", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    for (const r of results) {
      expect(r.name.length).toBeGreaterThan(0)
      expect(r.message.length).toBeGreaterThan(0)
    }
  }, { timeout: TIMEOUT_MS })

  test("Runtime check returns PASS with version info", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const runtime = results.find((r: any) => r.name === "Runtime")!
    expect(runtime).toBeDefined()
    expect(runtime.status).toBe("PASS")
    // Bun reports as Node.js, so accept either runtime name
    expect(runtime.message).toMatch(/(Node\.js|Bun)/)
  }, { timeout: TIMEOUT_MS })

  test("Configuration check returns valid result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const config = results.find((r: any) => r.name === "Configuration")!
    expect(config).toBeDefined()
    expect(["PASS", "WARN"]).toContain(config.status)
  }, { timeout: TIMEOUT_MS })

  test("returns results even when some checks fail gracefully", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(Array.isArray(results)).toBe(true)
  }, { timeout: TIMEOUT_MS })

  test("Config validation check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const val = results.find((r: any) => r.name === "Config Validation")!
    expect(val).toBeDefined()
    expect(["PASS", "WARN"]).toContain(val!.status)
    expect(val!.message.length).toBeGreaterThan(0)
  }, { timeout: TIMEOUT_MS })

  test("Credentials check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const cred = results.find((r: any) => r.name === "Credentials")!
    expect(cred).toBeDefined()
    expect(["PASS", "WARN", "FAIL"]).toContain(cred!.status)
  }, { timeout: TIMEOUT_MS })

  test("MCP Worker check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const mcp = results.find((r: any) => r.name === "MCP Worker")!
    expect(mcp).toBeDefined()
    expect(["PASS", "WARN", "FAIL"]).toContain(mcp!.status)
  }, { timeout: TIMEOUT_MS })

  test("Python Runtime check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const py = results.find((r: any) => r.name === "Python Runtime")!
    expect(py).toBeDefined()
    expect(["PASS", "FAIL"]).toContain(py!.status)
    expect(py!.message.length).toBeGreaterThan(0)
  }, { timeout: TIMEOUT_MS })

  test("Redis check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const redis = results.find((r: any) => r.name === "Redis")!
    expect(redis).toBeDefined()
    expect(["PASS", "WARN", "FAIL"]).toContain(redis!.status)
  }, { timeout: TIMEOUT_MS })

  test("Toolchain check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const toolchain = results.find((r: any) => r.name === "Toolchain")!
    expect(toolchain).toBeDefined()
    expect(["PASS", "WARN", "FAIL"]).toContain(toolchain!.status)
    expect(toolchain!.message.length).toBeGreaterThan(0)
  }, { timeout: TIMEOUT_MS })

  test("Playwright check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const pw = results.find((r: any) => r.name === "Playwright")!
    expect(pw).toBeDefined()
    expect(["PASS", "WARN"]).toContain(pw!.status)
  }, { timeout: TIMEOUT_MS })

  test("Database check returns a result", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const db = results.find((r: any) => r.name === "Database")!
    expect(db).toBeDefined()
    expect(["PASS", "FAIL"]).toContain(db!.status)
  }, { timeout: TIMEOUT_MS })

  test("returns 10 results by default", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(results.length).toBe(10)
  }, { timeout: TIMEOUT_MS })

  test("--online adds LLM Provider check (11 results)", async () => {
    const { doctorCommand } = await import("../../../../src/argus/commands/doctor")
    const results = await doctorCommand({ online: true })
    expect(results.length).toBe(11)

    const llm = results.find((r: any) => r.name === "LLM Provider")!
    expect(llm).toBeDefined()
    expect(["PASS", "WARN"]).toContain(llm!.status)
  }, { timeout: TIMEOUT_MS })

})

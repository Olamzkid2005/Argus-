/**
 * Integration test for doctorCommand (argus diagnostics).
 *
 * Runs the real doctorCommand and validates that all system checks
 * produce well-structured results. These tests interact with the
 * actual filesystem, PATH, and environment variables, so they
 * reflect real-world behavior.
 */
import { describe, expect, test } from "bun:test"

const TIMEOUT_MS = 30000

describe("doctor full-pipeline integration", () => {
  test("doctorCommand returns exactly 10 checks by default", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(results.length).toBe(10)
  }, { timeout: TIMEOUT_MS })

  test("all 10 checks have valid name, status, and message", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()

    const expectedNames = [
      "Runtime",
      "Python Runtime",
      "MCP Worker",
      "Playwright",
      "Redis",
      "Database",
      "Credentials",
      "Configuration",
      "Config Validation",
      "Toolchain",
    ]

    for (const name of expectedNames) {
      const check = results.find((r: any) => r.name === name)
      expect(check).toBeDefined()
      expect(["PASS", "WARN", "FAIL"]).toContain(check!.status)
      expect(check!.message.length).toBeGreaterThan(0)
    }
  }, { timeout: TIMEOUT_MS })

  test("Runtime check always passes with version info", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const runtime = results.find((r: any) => r.name === "Runtime")!
    expect(runtime.status).toBe("PASS")
    expect(runtime.message).toMatch(/(Node\.js|Bun)/)
  }, { timeout: TIMEOUT_MS })

  test("Python Runtime check returns PASS or FAIL (never WARN)", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const py = results.find((r: any) => r.name === "Python Runtime")!
    expect(["PASS", "FAIL"]).toContain(py!.status)
    if (py!.status === "PASS") {
      expect(py!.message).toMatch(/Python/)
    }
  }, { timeout: TIMEOUT_MS })

  test("MCP Worker check returns PASS, WARN, or FAIL", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const mcp = results.find((r: any) => r.name === "MCP Worker")!
    expect(["PASS", "WARN", "FAIL"]).toContain(mcp!.status)
    expect(mcp!.message.length).toBeGreaterThan(0)
  }, { timeout: TIMEOUT_MS })

  test("Playwright check returns PASS or WARN (never FAIL)", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const pw = results.find((r: any) => r.name === "Playwright")!
    expect(["PASS", "WARN"]).toContain(pw!.status)
  }, { timeout: TIMEOUT_MS })

  test("Redis check returns PASS, WARN, or FAIL depending on env", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const redis = results.find((r: any) => r.name === "Redis")!
    expect(["PASS", "WARN", "FAIL"]).toContain(redis!.status)
  }, { timeout: TIMEOUT_MS })

  test("Database check returns PASS or FAIL", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const db = results.find((r: any) => r.name === "Database")!
    expect(["PASS", "FAIL"]).toContain(db!.status)
  }, { timeout: TIMEOUT_MS })

  test("Credentials check returns PASS or WARN", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const cred = results.find((r: any) => r.name === "Credentials")!
    expect(["PASS", "WARN"]).toContain(cred!.status)
  }, { timeout: TIMEOUT_MS })

  test("Configuration check returns PASS or WARN", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const config = results.find((r: any) => r.name === "Configuration")!
    expect(["PASS", "WARN"]).toContain(config!.status)
  }, { timeout: TIMEOUT_MS })

  test("Config Validation check returns PASS or WARN (no .env by default)", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const val = results.find((r: any) => r.name === "Config Validation")!
    expect(["PASS", "WARN"]).toContain(val!.status)
    expect(val!.message.length).toBeGreaterThan(0)
  }, { timeout: TIMEOUT_MS })

  test("Toolchain check returns PASS, WARN, or FAIL", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const toolchain = results.find((r: any) => r.name === "Toolchain")!
    expect(["PASS", "WARN", "FAIL"]).toContain(toolchain!.status)
    expect(toolchain!.message).toMatch(/tools on PATH|0 tools found/)
  }, { timeout: TIMEOUT_MS })

  test("--online flag adds LLM Provider check (total 11)", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand({ online: true })
    expect(results.length).toBe(11)
    const llm = results.find((r: any) => r.name === "LLM Provider")!
    expect(llm).toBeDefined()
    expect(["PASS", "WARN"]).toContain(llm!.status)
  }, { timeout: TIMEOUT_MS })

  test("all checks are returned in the expected order", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const names = results.map((r: any) => r.name)
    expect(names[0]).toBe("Runtime")
    expect(names[1]).toBe("Python Runtime")
    expect(names[2]).toBe("MCP Worker")
    expect(names[3]).toBe("Playwright")
    expect(names[4]).toBe("Redis")
    expect(names[5]).toBe("Database")
    expect(names[6]).toBe("Credentials")
    expect(names[7]).toBe("Configuration")
    expect(names[8]).toBe("Config Validation")
    expect(names[9]).toBe("Toolchain")
  }, { timeout: TIMEOUT_MS })

  test("status strings are never empty", async () => {
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    for (const r of results) {
      expect(r.status.length).toBeGreaterThan(0)
      expect(r.message.length).toBeGreaterThan(0)
    }
  }, { timeout: TIMEOUT_MS })
})

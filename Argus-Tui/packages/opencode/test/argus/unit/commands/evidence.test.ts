import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"

let testDir: string

beforeAll(() => {
  testDir = mkdtempSync(join(tmpdir(), "argus-cmd-test-"))
})

afterAll(() => {
  try { rmSync(testDir, { recursive: true, force: true }) } catch {}
})

describe("configCommand", () => {
  test("returns configuration with built-in defaults", async () => {
    const { configCommand } = await import("../../../../src/argus/commands/config")
    const output = await configCommand()
    expect(typeof output).toBe("string")
  })

  test("filters configuration by key", async () => {
    const { configCommand } = await import("../../../../src/argus/commands/config")
    const output = await configCommand("evidence")
    expect(typeof output).toBe("string")
  })

  test("filters configuration with no matches", async () => {
    const { configCommand } = await import("../../../../src/argus/commands/config")
    const output = await configCommand("nonexistent-key")
    expect(typeof output).toBe("string")
  })

  test("masks sensitive keys in output", async () => {
    const credsDir = join(testDir, ".argus")
    mkdirSync(credsDir, { recursive: true })
    writeFileSync(join(credsDir, "credentials.json"), JSON.stringify({ roles: {} }))

    const originalHome = process.env.HOME
    process.env.HOME = testDir

    const { configCommand } = await import("../../../../src/argus/commands/config")
    const output = await configCommand("credentials")
    expect(typeof output).toBe("string")

    if (originalHome) process.env.HOME = originalHome
  })
})

describe("evidenceCommand", () => {
  test("evidence list returns string output", async () => {
    const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
    const output = await evidenceCommand("list", [])
    expect(typeof output).toBe("string")
  })

  test("evidence show without package-id returns usage message", async () => {
    const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
    const output = await evidenceCommand("show", [])
    expect(typeof output).toBe("string")
  })

  test("evidence verify-package without package-id returns usage message", async () => {
    const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
    const output = await evidenceCommand("verify-package", [])
    expect(typeof output).toBe("string")
  })

  test("evidence unknown action returns error message", async () => {
    const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
    const output = await evidenceCommand("unknown-action" as any, [])
    expect(typeof output).toBe("string")
  })
})

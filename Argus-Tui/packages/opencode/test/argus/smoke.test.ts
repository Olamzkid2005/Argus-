/**
 * Argus CLI Smoke Test
 *
 * Fast sanity checks that verify the application boots, imports resolve,
 * and basic CLI paths work — without requiring real infrastructure.
 * Designed to run in CI in under 30 seconds.
 */
import { describe, it, expect, beforeAll } from "bun:test"
import { $ } from "bun"
import path from "path"

const ARGUS_ENTRY = path.resolve(import.meta.dirname, "../../src/argus/index.ts")

describe("CLI entry point", () => {
  it("--help exits 0 and shows platform name", async () => {
    const proc = Bun.spawn(["bun", "run", ARGUS_ENTRY, "--help"], {
      env: { ...process.env, ARGUS_MODE: "0" },
    })
    const text = await new Response(proc.stdout).text()
    expect(proc.exitCode).toBe(0)
    expect(text).toContain("assess")
    expect(text).toContain("doctor")
    expect(text).toContain("report")
  })

  it("--version exits 0", async () => {
    const proc = Bun.spawn(["bun", "run", ARGUS_ENTRY, "--version"], {
      env: { ...process.env, ARGUS_MODE: "0" },
    })
    const text = await new Response(proc.stdout).text()
    expect(proc.exitCode).toBe(0)
    expect(text.length).toBeGreaterThan(0)
  })

  it("engagements returns empty state gracefully", async () => {
    const proc = Bun.spawn(["bun", "run", ARGUS_ENTRY, "engagements"], {
      env: { ...process.env, ARGUS_MODE: "0" },
    })
    const text = await new Response(proc.stdout).text()
    expect(proc.exitCode).toBe(0)
  })

  it("config shows configuration without crashing", async () => {
    const proc = Bun.spawn(["bun", "run", ARGUS_ENTRY, "config"], {
      env: { ...process.env, ARGUS_MODE: "0" },
    })
    const text = await new Response(proc.stdout).text()
    expect(proc.exitCode).toBe(0)
    expect(text.length).toBeGreaterThan(0)
  })
})

describe("import resolution", () => {
  it("imports core argus modules without error", async () => {
    const code = `
      const engagement = await import("@/argus/engagement/store")
      const cli = await import("@/argus/cli")
      const commands = await import("@/argus/commands/doctor")
      const logo = await import("@/argus/logo")
      console.log("OK")
    `
    const proc = Bun.spawn(["bun", "run", "-e", code], {
      env: { ...process.env, ARGUS_MODE: "0" },
      cwd: path.resolve(import.meta.dirname, "../.."),
    })
    const text = await new Response(proc.stdout).text()
    expect(proc.exitCode).toBe(0)
    expect(text.trim()).toBe("OK")
  })

  it("imports CLI framework modules", async () => {
    const code = `
      const y = await import("yargs")
      const ui = await import("@/argus/ui")
      console.log("OK")
    `
    const proc = Bun.spawn(["bun", "run", "-e", code], {
      env: { ...process.env, ARGUS_MODE: "0" },
      cwd: path.resolve(import.meta.dirname, "../.."),
    })
    const text = await new Response(proc.stdout).text()
    expect(proc.exitCode).toBe(0)
    expect(text.trim()).toBe("OK")
  })
})

/**
 * Argus CLI Smoke Test
 *
 * Fast sanity checks that verify the application boots, imports resolve,
 * and basic CLI paths work — without requiring real infrastructure.
 * Designed to run in CI in under 30 seconds.
 */
import { describe, it, expect, beforeAll, afterAll } from "bun:test"
import path from "path"
import { tmpdir } from "../fixture/fixture"

let tmpDirPath: string
let tmpDispose: () => Promise<void>

beforeAll(async () => {
  const tmp = await tmpdir()
  tmpDirPath = tmp.path
  tmpDispose = () => tmp[Symbol.asyncDispose]()
})

afterAll(async () => {
  await tmpDispose?.()
})

const ARGUS_ENTRY = path.resolve(import.meta.dirname, "../../src/argus/index.ts")

async function runArgus(args: string[], cwd?: string): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  const proc = Bun.spawn(["bun", "run", ARGUS_ENTRY, ...args], {
    stdio: ["ignore", "pipe", "pipe"],
    ...(cwd ? { cwd } : {}),
    env: { ...process.env, ARGUS_MODE: "0", CI: "true", HOME: tmpDirPath },
  })
  const [stdout, stderr] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text()])
  const exitCode = await proc.exited
  return { stdout, stderr, exitCode }
}

async function runBunEval(code: string): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  const proc = Bun.spawn(["bun", "-e", code], {
    stdio: ["ignore", "pipe", "pipe"],
    cwd: path.resolve(import.meta.dirname, "../.."),
    env: { ...process.env, ARGUS_MODE: "0", HOME: tmpDirPath },
  })
  const [stdout, stderr] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text()])
  const exitCode = await proc.exited
  return { stdout, stderr, exitCode }
}

describe("CLI entry point", () => {
  it("--help exits 0 and prints output", async () => {
    const { exitCode, stdout, stderr } = await runArgus(["--help"])
    expect(exitCode).toBe(0)
    expect(stdout.length + stderr.length).toBeGreaterThan(0)
  })

  it("--version exits 0", async () => {
    const { exitCode, stdout, stderr } = await runArgus(["--version"])
    expect(exitCode).toBe(0)
    expect(stdout.length + stderr.length).toBeGreaterThan(0)
  })

  it("engagements handles empty state gracefully", async () => {
    const { exitCode } = await runArgus(["engagements"])
    expect(exitCode).toBe(0)
  })

  it("config shows configuration without crashing", async () => {
    const { exitCode, stdout, stderr } = await runArgus(["config"])
    expect(exitCode).toBe(0)
    expect(stdout.length + stderr.length).toBeGreaterThan(0)
  })

  // Step 2 acceptance: `assess --autonomous` must refuse to start when the
  // scope mode is not an enforced allowlist, and the refusal must be visible to
  // an unattended driver as a non-zero exit code.
  it("assess --autonomous refuses to start under scope mode 'warn'", async () => {
    const { mkdtempSync, writeFileSync, rmSync } = await import("fs")
    const os = await import("os")
    const joinPath = await import("path")
    const dir = mkdtempSync(joinPath.join(os.tmpdir(), "argus-smoke-scope-"))
    writeFileSync(joinPath.join(dir, "argus.config.yaml"), "security:\n  scope:\n    mode: warn\n", "utf-8")
    try {
      const { exitCode, stderr } = await runArgus(
        ["assess", "http://127.0.0.1:9", "--autonomous", "--deterministic"],
        dir,
      )
      expect(exitCode).toBe(1)
      expect(stderr).toContain("must be explicitly set to 'allowlist'")
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

describe("import resolution", () => {
  it("core argus modules import without error", async () => {
    const { exitCode, stdout, stderr } = await runBunEval(
      `import "@/argus/engagement/store"; import "@/argus/cli"; import "@/argus/commands/doctor"; import "@/argus/logo"; console.log("OK")`,
    )
    if (exitCode !== 0) console.error("import stderr:", stderr)
    expect(exitCode).toBe(0)
    expect(stdout.trim()).toBe("OK")
  })

  it("CLI framework modules import without error", async () => {
    const { exitCode, stdout, stderr } = await runBunEval(
      `import "@/argus/ui"; console.log("OK")`,
    )
    if (exitCode !== 0) console.error("import stderr:", stderr)
    expect(exitCode).toBe(0)
    expect(stdout.trim()).toBe("OK")
  })
})

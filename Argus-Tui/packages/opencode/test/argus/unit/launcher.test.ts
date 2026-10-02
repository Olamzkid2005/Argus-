import { describe, expect, test } from "bun:test"
import path from "node:path"
import { tmpdir } from "../../fixture/fixture"
import { launchTui, spawnForeground } from "../../../src/argus/launcher"
import { MCP_WORKER_PATH } from "../../../src/argus/shared/path"
import { WorkflowRegistry } from "../../../src/argus/workflows/registry"

// Only the process boundary is substituted: no worker, model, or assessment
// runs while checking which UI the real launcher selects.
describe("Argus launcher", () => {
  test("bare argus opens the full-screen TUI in the caller's workspace", () => {
    const calls: string[][] = []
    launchTui([], (command, args, options) => {
      expect(command).toBe(process.execPath)
      expect(args).toContain("--conditions=browser")
      expect(args.some((arg) => arg.endsWith("/src/index.ts"))).toBe(true)
      expect(args).not.toContain("--interactive")
      expect(args.filter((arg) => arg === "run")).toHaveLength(1)
      expect(options.cwd).toBe(process.cwd())
      expect(options.env?.ARGUS_MODE).toBe("1")
      expect(options.env?.OPENCODE_ROUTE).toBe('{"type":"home"}')
      expect(options.stdio).toBe("inherit")
      calls.push(args)
    })
    expect(calls).toHaveLength(1)
  })

  test("forwards TUI options and explicitly loads Solid from another workspace", async () => {
    await using tmp = await tmpdir()
    const cwd = process.cwd()
    try {
      process.chdir(tmp.path)
      launchTui(["--model", "test/model"], (_, args, options) => {
        expect(options.cwd).toBe(tmp.path)
        expect(args.slice(-2)).toEqual(["--model", "test/model"])
        const preload = args[args.indexOf("--preload") + 1]
        expect(path.isAbsolute(preload)).toBe(true)
        expect(Bun.file(preload).size).toBeGreaterThan(0)
      })
      expect(await Bun.file(MCP_WORKER_PATH).exists()).toBe(true)
      expect(new WorkflowRegistry().loadAll().length).toBeGreaterThan(0)
    } finally {
      process.chdir(cwd)
    }
  })

  test("a failed spawn reports failure and removes signal listeners", async () => {
    const before = ["SIGINT", "SIGTERM", "SIGHUP"].map((signal) => process.listenerCount(signal))
    const code = process.exitCode
    try {
      const child = spawnForeground("/nonexistent/argus-test-binary", [], { stdio: "ignore" })
      await new Promise<void>((resolve) => child.once("close", () => resolve()))
      expect(process.exitCode).toBe(1)
      expect(["SIGINT", "SIGTERM", "SIGHUP"].map((signal) => process.listenerCount(signal))).toEqual(before)
    } finally {
      process.exitCode = code ?? 0
    }
  })

  test("foreground completion preserves nonzero status and cleans up signal listeners", async () => {
    const before = ["SIGINT", "SIGTERM", "SIGHUP"].map((signal) => process.listenerCount(signal))
    const code = process.exitCode
    try {
      const child = spawnForeground(process.execPath, ["-e", "process.exit(7)"], { stdio: "ignore" })
      await new Promise<void>((resolve) => child.once("close", () => resolve()))
      expect(process.exitCode).toBe(7)
      expect(["SIGINT", "SIGTERM", "SIGHUP"].map((signal) => process.listenerCount(signal))).toEqual(before)
    } finally {
      process.exitCode = code ?? 0
    }
  })
})

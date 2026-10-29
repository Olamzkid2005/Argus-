import { describe, expect, test } from "bun:test"
import path from "node:path"
import { tmpdir } from "../../fixture/fixture"
import { resolveDefaultPython } from "../../../src/argus/bridge/mcp-client"

const binary = path.resolve(import.meta.dir, "../../../bin/argus")

// `argus doctor` is a one-shot command: it must print every check and exit.
//
// Regression: resolving the planner's model reads the OpenCode provider
// registry, which lazily boots the whole runtime. That runtime owns long-lived
// watchers and timers by design, so after the summary line the CLI sat there
// until it was killed. A health check that never returns cannot verify an
// environment, and it also made this check impossible to automate.
//
// The Python assertion is the second half: the doctor used to search for an
// interpreter on its own (bare `python3`) while the worker bridge preferred the
// repo virtualenv, so `/doctor` reported a healthy/dependent runtime that the
// worker never used.
describe("argus doctor CLI", () => {
  test("prints its health checks and exits in an isolated environment", async () => {
    await using home = await tmpdir()
    // Never query the real OS keychain during a health check.
    await Bun.write(path.join(home.path, "argus/config.yaml"), "storage:\n  encryption:\n    enabled: false\n")
    const child = Bun.spawn([process.execPath, binary, "doctor"], {
      cwd: home.path,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        PATH: process.env.PATH ?? "",
        HOME: home.path,
        XDG_CONFIG_HOME: path.join(home.path, "config"),
        XDG_DATA_HOME: path.join(home.path, "data"),
        XDG_STATE_HOME: path.join(home.path, "state"),
        XDG_CACHE_HOME: path.join(home.path, "cache"),
        ARGUS_DATA_DIR: path.join(home.path, "argus"),
        ARGUS_KEYCHAIN_SERVICE: `argus-doctor-test-${process.pid}`,
        ARGUS_ALLOW_AMBIENT_LLM_ENV: "0",
        OPENCODE_DISABLE_PROJECT_CONFIG: "1",
        OPENCODE_DISABLE_AUTOUPDATE: "1",
        OPENCODE_DISABLE_MODELS_FETCH: "1",
        OPENCODE_AUTH_CONTENT: "{}",
        OPENCODE_DB: ":memory:",
        TERM: "xterm-256color",
      },
    })
    // Read both pipes while the child runs so a chatty boot log cannot fill
    // them and deadlock the very hang this test is looking for.
    const stdout = new Response(child.stdout).text()
    const stderr = new Response(child.stderr).text()

    let killed = false
    const timer = setTimeout(() => {
      killed = true
      child.kill("SIGKILL")
    }, 120_000)
    let code: number
    try {
      code = await child.exited
    } finally {
      clearTimeout(timer)
    }
    const output = (await stdout) + (await stderr)

    expect(killed).toBe(false)
    expect(code === 0 || code === 1).toBe(true)
    // The summary proves the run reached the end of the check list.
    expect(output).toMatch(/\d+ passed, \d+ warnings, \d+ failed/)
    for (const name of ["[Runtime]", "[Python Runtime]", "[MCP Worker]", "[Toolchain]"]) {
      expect(output).toContain(name)
    }
    // The check must describe the interpreter the worker bridge will spawn.
    expect(output).toContain(`(via ${resolveDefaultPython()})`)
  }, 150_000)
})

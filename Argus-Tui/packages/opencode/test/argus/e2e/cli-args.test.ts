import { describe, expect, test } from "bun:test"
import path from "node:path"
import { tmpdir } from "../../fixture/fixture"

const binary = path.resolve(import.meta.dir, "../../../bin/argus")

async function runCli(args: string[]): Promise<{ code: number; output: string }> {
  await using home = await tmpdir()
  const child = Bun.spawn([process.execPath, binary, ...args], {
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
      ARGUS_KEYCHAIN_SERVICE: `argus-cli-args-${process.pid}`,
      OPENCODE_DISABLE_PROJECT_CONFIG: "1",
      OPENCODE_DISABLE_AUTOUPDATE: "1",
      OPENCODE_DISABLE_MODELS_FETCH: "1",
      OPENCODE_AUTH_CONTENT: "{}",
      OPENCODE_DB: ":memory:",
    },
  })
  const stdout = new Response(child.stdout).text()
  const stderr = new Response(child.stderr).text()
  const code = await child.exited
  return { code, output: (await stdout) + (await stderr) }
}

// Two ways a CLI silently does nothing, both seen while verifying the assess
// exit path:
//
//  * `--no-cache` is a documented option, but yargs' boolean-negation turned it
//    into an unknown `cache` argument under `.strict()`;
//  * the failure handler printed help and left the exit status at 0, so an
//    unattended driver read "unknown argument" as a completed command.
describe("argus CLI argument handling", () => {
  test("accepts the documented --no-cache flag", async () => {
    const { code, output } = await runCli(["assess", "--no-cache"])

    expect(output).not.toContain("Unknown argument")
    // Reaching "missing target" proves parsing accepted the flag and handed
    // control to the command rather than to the usage screen.
    expect(output).toContain("Not enough non-option arguments")
    expect(code).toBe(1)
  }, 120_000)

  test("a usage error exits nonzero", async () => {
    const { code, output } = await runCli(["assess"])

    expect(output).toContain("[Argus] Not enough non-option arguments")
    expect(code).toBe(1)
  }, 120_000)
})

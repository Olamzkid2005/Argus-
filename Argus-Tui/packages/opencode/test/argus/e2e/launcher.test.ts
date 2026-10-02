import { describe, expect, test } from "bun:test"
import path from "node:path"
import { tmpdir } from "../../fixture/fixture"
import { PROJECT_ROOT } from "../../../src/argus/shared/path"
import { testProviderConfig } from "../../lib/test-provider"

const binary = path.resolve(import.meta.dir, "../../../bin/argus")

// A real PTY catches wrong command routing, missing Solid transforms, a home
// without a prompt, and terminal shutdown failures that spawn stubs cannot.
//
// SLOW / FLAKY GATE: cold start builds the whole CLI/worker/TUI module graph,
// measured at ~24s idle and well past 180s under heavy developer-machine load.
// Bun's PTY never answers terminal capability queries, so OpenTUI falls back to
// timeouts and first paint is not deterministic. Keep the 180s/240s budget below
// and do not treat this as a fast CI gate; the deterministic prompt assertion
// lives in the in-process home-mount test in test/cli/tui/app-lifecycle.test.ts.
describe("bare Argus terminal", () => {
  for (const workspace of ["repository", "separate"] as const) {
    test(`opens a responsive assessment prompt from the ${workspace} workspace`, async () => {
      await using home = await tmpdir()
      await using other = await tmpdir()
      // Never query the real OS keychain during terminal startup tests.
      await Bun.write(path.join(home.path, "argus/config.yaml"), "storage:\n  encryption:\n    enabled: false\n")
      const chunks: string[] = []
      const decoder = new TextDecoder()
      let ready!: () => void
      const prompt = new Promise<void>((resolve) => {
        ready = resolve
      })
      // The shutdown path can repaint the frame it is leaving, so output after
      // our own SIGTERM must not count as a responsive prompt.
      let dying = false
      let tail = ""
      await using terminal = new Bun.Terminal({
        cols: 120,
        rows: 50,
        data(_, bytes) {
          const text = decoder.decode(bytes, { stream: true })
          chunks.push(text)
          tail = (tail + text).slice(-32)
          if (!dying && tail.includes("/assess")) ready()
        },
      })
      const child = Bun.spawn([process.execPath, binary], {
        cwd: workspace === "repository" ? PROJECT_ROOT : other.path,
        terminal,
        env: {
          PATH: process.env.PATH ?? "",
          HOME: home.path,
          OPENCODE_TEST_HOME: home.path,
          OPENCODE_TEST_MANAGED_CONFIG_DIR: path.join(home.path, "managed"),
          XDG_CONFIG_HOME: path.join(home.path, "config"),
          XDG_DATA_HOME: path.join(home.path, "data"),
          XDG_STATE_HOME: path.join(home.path, "state"),
          XDG_CACHE_HOME: path.join(home.path, "cache"),
          ARGUS_DATA_DIR: path.join(home.path, "argus"),
          ARGUS_KEYCHAIN_SERVICE: `argus-launcher-test-${process.pid}`,
          ARGUS_ALLOW_AMBIENT_LLM_ENV: "0",
          ARGUS_LLM_TRANSPORT: "direct",
          OPENCODE_DISABLE_PROJECT_CONFIG: "1",
          OPENCODE_PURE: "1",
          OPENCODE_DISABLE_AUTOUPDATE: "1",
          OPENCODE_DISABLE_MODELS_FETCH: "1",
          OPENCODE_MODELS_PATH: path.resolve(import.meta.dir, "../../tool/fixtures/models-api.json"),
          OPENCODE_AUTH_CONTENT: "{}",
          OPENCODE_DB: ":memory:",
          TERM: "xterm-256color",
          OPENCODE_CONFIG_CONTENT: JSON.stringify({
            ...testProviderConfig("http://127.0.0.1:1/v1"),
            model: "test/test-model",
            enabled_providers: ["test"],
          }),
        },
      })
      // Cold start loads the whole CLI/worker/TUI module graph and builds the
      // home frame: measured from ~20s idle to well past 90s under developer
      // machine load, so failing late is the only way to keep this gate honest.
      const timeout = setTimeout(() => {
        dying = true
        child.kill("SIGTERM")
      }, 180_000)
      try {
        await Promise.race([
          prompt,
          child.exited.then(async (code) => {
            const log = await Bun.file(path.join(home.path, "data/opencode/log/dev.log"))
              .text()
              .catch(() => "no log")
            throw new Error(
              `Argus exited before its prompt (${code}): ${chunks
                .join("")
                .replace(/\x1b\[[0-9;?<>]*[a-zA-Z]/g, "")
                .replace(/ +/g, " ")
                .trim()
                .slice(-6000)}\n${log.slice(-7000)}`,
            )
          }),
        ])
        // Exercise prompt input and the app's local exit command only.
        terminal.write("/exit\r")
        expect(await child.exited).toBe(0)
        const output = chunks.join("")
        expect(output).toContain("/assess")
        expect(output).not.toContain("Starting assessment")
        expect(output).not.toContain("ErrorBoundary")
      } finally {
        clearTimeout(timeout)
        if (child.exitCode === null) child.kill("SIGTERM")
        await child.exited
      }
    }, 240_000)
  }
})

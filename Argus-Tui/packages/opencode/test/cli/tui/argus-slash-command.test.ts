import { afterEach, expect, spyOn, test } from "bun:test"
import { TextareaRenderable } from "@opentui/core"
import { createTestRenderer } from "@opentui/core/testing"
import { Global } from "@opencode-ai/core/global"
import { Effect } from "effect"
import { mkdir } from "node:fs/promises"
import path from "node:path"
import { pollWithTimeout } from "../../lib/effect"
import { tmpdir } from "../../fixture/fixture"
import { createTuiResolvedConfig } from "../../fixture/tui-runtime"
import { createEventSource, createFetch, directory, json } from "../../fixture/tui-sdk"
import type { TuiHandle } from "../../../src/cli/cmd/tui/app"

type Setup = Awaited<ReturnType<typeof createTestRenderer>>
type Tmp = Awaited<ReturnType<typeof tmpdir>>

// Argus home renders its own logo, stats, and prompt, so the internal plugins
// that add home widgets are disabled to keep the frame and focus predictable.
const disabledInternalPlugins = {
  "internal:home-footer": false,
  "internal:home-tips": false,
  "internal:sidebar-context": false,
  "internal:sidebar-mcp": false,
  "internal:sidebar-lsp": false,
  "internal:sidebar-todo": false,
  "internal:sidebar-files": false,
  "internal:sidebar-footer": false,
  "internal:plugin-manager": false,
  "internal:session-v2-debug": false,
  "which-key": false,
}

const provider = {
  id: "test",
  name: "Test",
  source: "config",
  env: [],
  models: {
    "test-model": {
      id: "test-model",
      providerID: "test",
      name: "Test Model",
      api: { id: "test-model", url: "http://test", npm: "@ai-sdk/openai-compatible" },
      capabilities: { reasoning: false, toolcall: true, attachment: false, temperature: true },
      cost: { input: 0, output: 0, cache: { read: 0, write: 0 } },
      limit: { context: 100000, output: 10000 },
      status: "active",
      options: {},
    },
  },
}

const agent = {
  name: "build",
  description: "Build agent",
  mode: "primary",
  builtIn: true,
  permission: [],
  tools: {},
  options: {},
}

let active: { handle?: TuiHandle; setup?: Setup; restore?: () => void; tmp?: Tmp } | undefined

afterEach(async () => {
  const current = active
  active = undefined
  await current?.handle?.exit().catch(() => {})
  await current?.handle?.done.catch(() => {})
  await current?.handle?.ready.catch(() => {})
  if (current?.setup && !current.setup.renderer.isDestroyed) current.setup.renderer.destroy()
  current?.restore?.()
  await Bun.sleep(20)
  await current?.tmp?.[Symbol.asyncDispose]()
})

test("pasting /config and pressing enter once runs the command", async () => {
  const app = await startTui()
  app.theme.resolve("dark")
  await app.handle.ready

  const textarea = await Effect.runPromise(
    pollWithTimeout(
      Effect.promise(async () => {
        await app.setup.renderOnce()
        const editor = app.setup.renderer.currentFocusedEditor
        return editor instanceof TextareaRenderable ? editor : undefined
      }),
      "Argus prompt did not take focus",
    ),
  )

  // The terminal sends a bracketed paste for a real paste.
  await app.setup.mockInput.pasteBracketedText("/config")
  await Effect.runPromise(
    pollWithTimeout(
      Effect.promise(async () => {
        await app.setup.renderOnce()
        // The prompt asks the keymap for submit/tab while the autocomplete is
        // open, so this is the state where Enter used to re-fill the command.
        const capture = (textarea.traits as { capture?: readonly string[] }).capture
        return capture?.includes("submit") ? true : undefined
      }),
      "slash autocomplete did not open for the pasted command",
    ),
  )

  app.setup.mockInput.pressEnter()

  const submitted = await Effect.runPromise(
    pollWithTimeout(
      Effect.promise(async () => {
        await app.setup.renderOnce()
        return app.submitted.length > 0 ? app.submitted : undefined
      }),
      "one enter did not run the pasted command",
    ),
  )

  const text = submitted.map((body) => JSON.stringify(body)).join("\n")
  expect(submitted).toHaveLength(1)
  expect(text).toContain("Argus Configuration")
  expect(text).toContain("evidence.retention_days")
  expect(textarea.plainText).toBe("")
})

async function startTui() {
  const previous = {
    mode: process.env.ARGUS_MODE,
    route: process.env.OPENCODE_ROUTE,
    data: process.env.ARGUS_DATA_DIR,
  }
  process.env.ARGUS_MODE = "1"
  process.env.OPENCODE_ROUTE = '{"type":"home"}'

  const tmp = await tmpdir()
  await Bun.write(path.join(tmp.path, "config.yaml"), "storage:\n  encryption:\n    enabled: false\n")
  process.env.ARGUS_DATA_DIR = tmp.path

  const restorePaths = await isolateGlobalPaths(tmp.path)
  const setup = await createTestRenderer({
    width: 120,
    height: 50,
    useThread: false,
    maxFps: Number.POSITIVE_INFINITY,
  })
  const theme = deferred<"dark" | "light" | null>()
  const waitForThemeMode = spyOn(setup.renderer, "waitForThemeMode").mockImplementation(() => theme.promise)
  setup.renderer.once("destroy", () => theme.resolve(null))

  const submitted: unknown[] = []
  const calls = createFetch((url) => {
    // A connected provider and an agent are required before the prompt will
    // submit; Argus slash commands are dispatched after that gate.
    if (url.pathname === "/config/providers") return json({ providers: [provider], default: { test: "test-model" } })
    if (url.pathname === "/provider") return json({ all: [provider], default: { test: "test-model" }, connected: [] })
    if (url.pathname === "/agent") return json([agent])
  })
  const events = createEventSource()
  // The app posts Argus command output as a session message; capture those.
  const fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : undefined
    const url = new URL(request ? request.url : String(input))
    const method = request?.method ?? init?.method ?? "GET"
    if (method !== "POST") return calls.fetch(input)
    if (url.pathname === "/session") return json({ id: "ses_test" })
    if (!/^\/session\/[^/]+\/(message|prompt)$/.test(url.pathname)) return calls.fetch(input)
    submitted.push(JSON.parse(request ? await request.clone().text() : String(init?.body ?? "")))
    return json({})
  }) as typeof globalThis.fetch

  const { tui } = await import("../../../src/cli/cmd/tui/app")
  const handle = tui({
    url: "http://test",
    renderer: setup.renderer,
    config: createTuiResolvedConfig({ plugin_enabled: disabledInternalPlugins }),
    directory,
    fetch,
    events: events.source,
    args: {},
  })
  active = {
    handle,
    setup,
    tmp,
    restore: () => {
      waitForThemeMode.mockRestore()
      restorePaths()
      if (previous.mode === undefined) delete process.env.ARGUS_MODE
      else process.env.ARGUS_MODE = previous.mode
      if (previous.route === undefined) delete process.env.OPENCODE_ROUTE
      else process.env.OPENCODE_ROUTE = previous.route
      if (previous.data === undefined) delete process.env.ARGUS_DATA_DIR
      else process.env.ARGUS_DATA_DIR = previous.data
    },
  }

  return { handle, setup, theme, submitted }
}

async function isolateGlobalPaths(root: string) {
  const previous = {
    config: Global.Path.config,
    state: Global.Path.state,
  }
  Global.Path.config = path.join(root, "config")
  Global.Path.state = path.join(root, "state")
  await mkdir(Global.Path.config, { recursive: true })
  await mkdir(Global.Path.state, { recursive: true })
  await Bun.write(path.join(Global.Path.state, "kv.json"), JSON.stringify({ animations_enabled: false }))

  return () => {
    Global.Path.config = previous.config
    Global.Path.state = previous.state
  }
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

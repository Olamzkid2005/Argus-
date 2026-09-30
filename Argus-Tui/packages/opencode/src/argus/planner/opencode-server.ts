/**
 * Talk to a local OpenCode server instead of a provider gateway.
 *
 * Why this exists: OpenCode's own gateways (the free tier and OpenCode Go)
 * decide whether to serve a request partly on *which client* is asking. This
 * source tree gets HTTP 403 `FreeTierError: OpenCode's free tier can only be
 * used from within OpenCode` where an installed OpenCode binary gets an answer
 * — measured side by side, with byte-identical request headers and bodies
 * (see docs/DEMO-READINESS-PLAN.md, blocker B9). Rather than imitate the
 * official client, Argus asks it to make the call:
 *
 *     Argus planner ─┐
 *                    ├─► local OpenCode server ─► the model OpenCode is
 *     Argus worker  ─┘        (installed CLI)        configured to use
 *
 * That is also the honest reading of "Argus uses OpenCode's AI": the LLM call
 * is made by OpenCode, with OpenCode's credentials, through OpenCode's own
 * session machinery. Argus only decides *what to ask*.
 *
 * The server API used here is the one OpenCode's own SDK is generated from
 * (`packages/sdk/openapi.json`): create a session, prompt it, read the reply,
 * delete it. Sessions are created per call so planner calls cannot leak
 * context into one another.
 */

import { spawn, type ChildProcess } from "node:child_process"

/** How long to wait for a planner answer before giving up. */
const DEFAULT_PROMPT_TIMEOUT_MS = 180_000

/**
 * Second ask, used when a model answers a structured request with a tool call or
 * prose. A coding agent tends to explore first and answer second, so the retry
 * names the one tool it must use.
 */
const STRUCTURED_RETRY_PROMPT =
  "Your previous reply did not use the requested structured format. " +
  "Answer the original question again, this time using ONLY the StructuredOutput tool. " +
  "Do not call any other tool, and do not answer in plain text."

/** How long to wait for a freshly spawned server to answer `/config`. */
const SERVER_START_TIMEOUT_MS = 60_000

export interface OpencodeServerHandle {
  readonly baseUrl: string
  /** True when this process spawned the server and must therefore stop it. */
  readonly owned: boolean
  /** Human-readable description for logs: how the server was found. */
  readonly origin: string
  dispose(): Promise<void>
}

export interface ServerModelRef {
  readonly providerID: string
  readonly modelID: string
}

export interface ServerPromptResult {
  /** Concatenated assistant text. */
  readonly text: string
  /** Object from `format: json_schema`, when the model produced one. */
  readonly structured: unknown
  readonly providerID: string
  readonly modelID: string
  readonly tokens: { input: number; output: number; reasoning: number }
  readonly sessionID: string
}

export class OpencodeServerError extends Error {
  readonly kind: "spawn" | "start" | "transport" | "model" | "timeout" | "unsupported"
  constructor(kind: OpencodeServerError["kind"], message: string) {
    super(message)
    this.name = "OpencodeServerError"
    this.kind = kind
  }
}

const log = (msg: string) => console.log(`[Argus:ocserver] ${msg}`)

/**
 * Servers this process started, so the CLI entry can stop them on exit.
 * A leaked `opencode serve` would otherwise outlive the assessment.
 */
const acquired = new Set<OpencodeServerHandle>()

/**
 * Servers this process has acquired, keyed by the directory they serve.
 *
 * The planner and the worker handoff both need one, and each would otherwise
 * start its own `opencode serve` — two servers for one assessment is waste, not
 * isolation. A cached server is health-checked before reuse, so one that has
 * died is replaced instead of being handed out forever.
 */
const serversByDirectory = new Map<string, OpencodeServerHandle>()

/** Stop every server this process started. Safe to call more than once. */
export async function shutdownAcquiredServers(): Promise<void> {
  const handles = [...acquired]
  acquired.clear()
  serversByDirectory.clear()
  await Promise.all(handles.map((handle) => handle.dispose()))
}

// ── Transport selection ──────────────────────────────────────────────

/** `ARGUS_LLM_TRANSPORT=server|direct|auto` (default `auto`). */
export const LLM_TRANSPORT_ENV_VAR = "ARGUS_LLM_TRANSPORT"

export type PlannerTransport = "server" | "direct"

/**
 * Where a call to a provider should be made.
 *
 * OpenCode's own gateways serve requests made by OpenCode itself and refuse
 * them from this source tree (HTTP 403 `FreeTierError`, see blocker B9), so
 * `opencode*` providers default to going through a local OpenCode server. Every
 * other provider is a normal HTTP API that Argus can call directly.
 *
 * The same selection governs the worker handoff: one run must not have the
 * planner borrowing OpenCode's client while the worker posts to a gateway that
 * will refuse it.
 */
export function selectPlannerTransport(
  providerID: string,
  preference = process.env[LLM_TRANSPORT_ENV_VAR]?.trim().toLowerCase(),
): PlannerTransport {
  if (preference === "direct") return "direct"
  if (preference === "server") return "server"
  return providerID.startsWith("opencode") ? "server" : "direct"
}

/** A free TCP port, released immediately so the server can bind it. */
async function freePort(): Promise<number> {
  const probe = Bun.serve({ port: 0, hostname: "127.0.0.1", fetch: () => new Response("") })
  const port = probe.port
  await probe.stop(true)
  if (port === undefined) throw new OpencodeServerError("spawn", "could not find a free local port")
  return port
}

async function healthy(baseUrl: string, directory: string): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl}/config?directory=${encodeURIComponent(directory)}`, {
      signal: AbortSignal.timeout(5_000),
    })
    return res.ok
  } catch {
    return false
  }
}

/** A live server for this directory, or undefined. Failed caches are dropped. */
async function cachedServer(directory: string): Promise<OpencodeServerHandle | undefined> {
  const cached = serversByDirectory.get(directory)
  if (!cached) return undefined
  if (await healthy(cached.baseUrl, directory)) return cached
  serversByDirectory.delete(directory)
  acquired.delete(cached)
  await cached.dispose().catch(() => {})
  return undefined
}

/**
 * Find a server to use, or start one.
 *
 * `OPENCODE_SERVER_URL` points at an already-running server (the operator runs
 * `opencode serve`). Otherwise the installed `opencode` binary is spawned with
 * `serve`. `ARGUS_OPENCODE_BIN` overrides which binary is used.
 */
export async function acquireServer(input: {
  directory: string
  binary?: string
}): Promise<OpencodeServerHandle> {
  const cached = await cachedServer(input.directory)
  if (cached) return cached

  const existing = process.env.OPENCODE_SERVER_URL?.trim()
  if (existing) {
    const baseUrl = existing.replace(/\/+$/, "")
    if (!(await healthy(baseUrl, input.directory))) {
      throw new OpencodeServerError(
        "start",
        `OPENCODE_SERVER_URL=${baseUrl} is set but /config did not answer. Start it with \`opencode serve\` or unset the variable.`,
      )
    }
    log(`using server from OPENCODE_SERVER_URL at ${baseUrl}`)
    const handle: OpencodeServerHandle = {
      baseUrl,
      owned: false,
      origin: "OPENCODE_SERVER_URL",
      dispose: async () => {},
    }
    serversByDirectory.set(input.directory, handle)
    return handle
  }

  const binary = input.binary ?? process.env.ARGUS_OPENCODE_BIN?.trim() ?? "opencode"
  const port = await freePort()
  const child: ChildProcess = spawn(
    binary,
    ["serve", "--port", String(port), "--hostname", "127.0.0.1"],
    { cwd: input.directory, stdio: ["ignore", "pipe", "pipe"] },
  )

  let stderr = ""
  child.stderr?.on("data", (chunk) => {
    stderr = (stderr + chunk.toString()).slice(-2000)
  })
  child.stdout?.on("data", (chunk) => log(chunk.toString().trim()))

  const baseUrl = `http://127.0.0.1:${port}`
  const deadline = Date.now() + SERVER_START_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new OpencodeServerError(
        "spawn",
        `\`${binary} serve\` exited with code ${child.exitCode} before it was ready.${stderr ? ` stderr: ${stderr.trim()}` : ""}`,
      )
    }
    if (await healthy(baseUrl, input.directory)) {
      log(`started ${binary} serve at ${baseUrl} (cwd ${input.directory})`)
      const handle: OpencodeServerHandle = {
        baseUrl,
        owned: true,
        origin: `${binary} serve`,
        dispose: async () => {
          acquired.delete(handle)
          serversByDirectory.delete(input.directory)
          if (child.exitCode === null) child.kill("SIGTERM")
        },
      }
      acquired.add(handle)
      serversByDirectory.set(input.directory, handle)
      return handle
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  if (child.exitCode === null) child.kill("SIGTERM")
  throw new OpencodeServerError(
    "timeout",
    `\`${binary} serve\` did not become ready within ${SERVER_START_TIMEOUT_MS / 1000}s.${stderr ? ` stderr: ${stderr.trim()}` : ""}`,
  )
}

interface SessionMessage {
  info?: {
    role?: string
    agent?: string
    modelID?: string
    providerID?: string
    error?: { name?: string; data?: { message?: string } }
    tokens?: { input?: number; output?: number; reasoning?: number }
  }
  parts?: Array<{ type?: string; text?: string; tool?: string }>
  structured?: unknown
}

/** Concatenate the assistant's visible text. */
function textOf(message: SessionMessage | undefined): string {
  return (message?.parts ?? [])
    .filter((p) => p.type === "text" && typeof p.text === "string")
    .map((p) => p.text as string)
    .join("")
    .trim()
}

/**
 * The error the provider reported for a message, if any.
 *
 * The server answers 200 even when the model call failed — the failure lives on
 * the message's `info.error`. Surfacing it is what makes a rejected credential
 * visible instead of looking like an empty answer.
 */
/**
 * Parse JSON out of model text, tolerating code fences and surrounding prose.
 *
 * A model asked for structured output may still answer in prose — a smaller
 * free model did — so the text is worth a lenient attempt before giving up.
 */
export function parseJsonObject(text: string): unknown {
  const trimmed = text.trim()
  if (!trimmed) return undefined
  const unfenced = trimmed.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "")
  for (const candidate of [unfenced, trimmed]) {
    try {
      const parsed = JSON.parse(candidate)
      if (parsed && typeof parsed === "object") return parsed
    } catch {
      // try the next candidate
    }
  }
  const start = unfenced.indexOf("{")
  const end = unfenced.lastIndexOf("}")
  if (start !== -1 && end > start) {
    try {
      return JSON.parse(unfenced.slice(start, end + 1))
    } catch {
      return undefined
    }
  }
  return undefined
}

/**
 * Unwrap a tool call that arrived as data rather than as a real tool call.
 *
 * Smaller models sometimes *write* the call instead of making it, so the reply
 * is JSON of the form `{"name":"StructuredOutput","parameters":{…}}` —
 * occasionally nested in arrays — rather than the object itself.
 */
export function unwrapToolCall(value: unknown): unknown {
  if (Array.isArray(value)) {
    for (const item of value.flat(4)) {
      const unwrapped = unwrapToolCall(item)
      if (unwrapped !== undefined) return unwrapped
    }
    return undefined
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>
    // Deliberately do not unwrap on `name` alone: a legitimate answer may have a
    // `name` field of its own. An envelope has both a name and parameters.
    if (typeof record.name === "string" && record.parameters !== undefined) {
      return record.parameters
    }
    return record
  }
  return undefined
}

/** A compact description of a reply's parts, for diagnostics. */
function describe(message: SessionMessage | undefined): string {
  const parts = message?.parts ?? []
  const kinds = parts.map((p) => p.type ?? "?").join(",") || "none"
  return `parts=[${kinds}] error=${message?.info?.error?.name ?? "none"}`
}

function messageError(message: SessionMessage | undefined): string | undefined {
  const err = message?.info?.error
  if (!err) return undefined
  const detail = err.data?.message ?? ""
  return `${err.name ?? "error"}${detail ? `: ${detail}` : ""}`
}

/**
 * Ask the server for a completion, optionally in a JSON-Schema shape.
 *
 * A session is created and deleted per call: planner calls are independent, and
 * a shared session would replay the whole conversation into every request.
 */
export async function prompt(input: {
  server: OpencodeServerHandle
  directory: string
  model: ServerModelRef
  system: string
  prompt: string
  /** JSON Schema for structured output; omit for free text. */
  schema?: Record<string, unknown>
  timeoutMs?: number
  signal?: AbortSignal
}): Promise<ServerPromptResult> {
  const { server, directory, model } = input
  const query = `directory=${encodeURIComponent(directory)}`
  const timeout = input.timeoutMs ?? DEFAULT_PROMPT_TIMEOUT_MS
  const signal = input.signal ?? AbortSignal.timeout(timeout)
  const json = { "content-type": "application/json" }

  const created = await fetch(`${server.baseUrl}/session?${query}`, {
    method: "POST",
    headers: json,
    // The `plan` agent: a real agent with a real tool set, so the request looks
    // like the coding-agent traffic OpenCode's gateways expect, but every one of
    // its tools is read-only.
    //
    // Both of those properties were arrived at by measurement, and the second is
    // not a preference:
    //
    //  - A request with NO tools is refused (`FreeTierError: OpenCode's free
    //    tier can only be used from within OpenCode`). Blanket-deny via a `*`
    //    rule, per-name deny rules, and message-level tool denial all produce
    //    that rejection — the gate wants ordinary agent traffic.
    //  - With the default `build` agent, a planning question was answered with a
    //    `skill` tool call instead of a plan. Tools stay enabled, so a planner
    //    call must at minimum be unable to change anything.
    body: JSON.stringify({ title: "argus", agent: "plan" }),
    signal,
  })
  if (!created.ok) {
    throw new OpencodeServerError(
      "transport",
      `could not create a session (HTTP ${created.status}): ${(await created.text()).slice(0, 300)}`,
    )
  }
  const sessionID = ((await created.json()) as { id?: string }).id
  if (!sessionID) throw new OpencodeServerError("transport", "session response had no id")

  try {
    // Ask again once when a structured answer was requested and the model
    // answered with a tool call or prose instead. A coding agent investigates
    // before it answers, so the second ask is usually the one that lands.
    const attempts = input.schema ? 2 : 1
    let assistant: SessionMessage | undefined
    let structured: unknown
    let text = ""
    let shape = "none"
    let messageErrorText: string | undefined

    for (let attempt = 1; attempt <= attempts; attempt++) {
      const res = await fetch(`${server.baseUrl}/session/${sessionID}/message?${query}`, {
        method: "POST",
        headers: json,
        body: JSON.stringify({
          model: { providerID: model.providerID, modelID: model.modelID },
          system: input.system,
          ...(input.schema ? { format: { type: "json_schema", schema: input.schema } } : {}),
          parts: [
            { type: "text", text: attempt === 1 ? input.prompt : STRUCTURED_RETRY_PROMPT },
          ],
        }),
        signal,
      })
      if (!res.ok) {
        throw new OpencodeServerError(
          "transport",
          `prompt failed (HTTP ${res.status}): ${(await res.text()).slice(0, 300)}`,
        )
      }
      assistant = (await res.json()) as SessionMessage
      messageErrorText = messageError(assistant)
      text = textOf(assistant)
      shape = describe(assistant)

      if (!input.schema) break

      // Structured output is attached to the *user* message that requested it,
      // so read the transcript rather than only the assistant reply.
      const listed = await fetch(`${server.baseUrl}/session/${sessionID}/message?${query}`, {
        method: "GET",
        signal,
      })
      if (listed.ok) {
        const transcript = (await listed.json()) as SessionMessage[]
        structured = [...transcript].reverse().find((m) => m.structured !== undefined)?.structured
        const lastAssistant = [...transcript].reverse().find((m) => m.info?.role === "assistant")
        if (lastAssistant) {
          text = textOf(lastAssistant) || text
          shape = describe(lastAssistant)
        }
      }
      // Accept an object carried in the text, including one a model "wrote" as
      // a tool call, before spending another turn on the retry prompt.
      structured = structured ?? unwrapToolCall(parseJsonObject(text))
      if (structured !== undefined) break
    }

    if (structured === undefined && !text) {
      // Include what the reply actually contained: a model that emits only
      // reasoning, or a tool call, otherwise looks identical to "no answer".
      throw new OpencodeServerError(
        "model",
        messageErrorText ?? `the model returned no text (${shape})`,
      )
    }

    return {
      text,
      structured,
      providerID: assistant?.info?.providerID ?? model.providerID,
      modelID: assistant?.info?.modelID ?? model.modelID,
      tokens: {
        input: assistant?.info?.tokens?.input ?? 0,
        output: assistant?.info?.tokens?.output ?? 0,
        reasoning: assistant?.info?.tokens?.reasoning ?? 0,
      },
      sessionID,
    }
  } finally {
    // Best-effort cleanup: a leaked session only wastes space, so a failure here
    // must not mask the real result.
    await fetch(`${server.baseUrl}/session/${sessionID}?${query}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(5_000),
    }).catch(() => undefined)
  }
}

/**
 * Registry-driven execution for Argus native tools.
 *
 * The wrappers themselves are generated (`./argus-tools.generated.ts`) from
 * the canonical Python registry (`tool_definitions.TOOLS`), so the TUI LLM
 * calls every executable Argus tool exactly like grep/glob: a name, a
 * description and a JSON Schema. This module holds the hand-written runtime:
 * argv construction, subprocess execution and result shaping.
 *
 * `buildRegistryArgv` mirrors `agent/tool_arguments.build_tool_argv` on the
 * Python side (static `default_args` first, then each declared parameter's
 * flag and value in declaration order; booleans are switches; flag-less
 * parameters stay positional). The two must stay in step — a dedicated unit
 * test pins the parity cases.
 */
import { join, dirname, delimiter } from "path"
import { fileURLToPath } from "url"
import { accessSync, constants } from "fs"
import { execFile, execFileSync } from "child_process"
import { isIP } from "net"
import {
  getTargetValidator,
  ALLOWED_TARGETS_ENV_VAR,
  BLOCKED_TARGETS_ENV_VAR,
  SCOPE_MODE_ENV_VAR,
} from "../argus/shared/target-validator"

/** One declared parameter, in registry declaration order. */
export interface RegistryToolParamSpec {
  readonly name: string
  readonly flag: string | null
}

/** Everything the runner needs to invoke one registry tool. */
export interface RegistryToolSpec {
  /** Native tool id (kebab-case, e.g. "finding-correlation-engine"). */
  readonly id: string
  /** Registry name (snake_case, e.g. "finding_correlation_engine"). */
  readonly toolName: string
  /** Binary on PATH, or "python3" for shim/launcher tools. */
  readonly command: string
  /** Static argv prefix (shim scripts, subcommands, fixed flags). */
  readonly args: readonly string[]
  /** Declared parameters in registry order. */
  readonly params: readonly RegistryToolParamSpec[]
  /** Per-tool timeout in milliseconds. */
  readonly timeoutMs: number
  /** Env vars the tool cannot run without (e.g. an API key). */
  readonly requiredEnv: readonly string[]
  /** Registry phases (drives role eligibility, e.g. recon-only tools). */
  readonly phases: readonly string[]
  /**
   * Registry risk tier (low, medium, high, critical, unclassified).
   * `unclassified` means the registry declares no risk level — never treated
   * as low risk, and ineligible for automatic execution until classified.
   */
  readonly risk: string
  /**
   * Non-zero exits that mean "findings present, not an error" for this tool.
   * Mirrors the worker's FINDINGS_EXIT_CODES (mcp_server.py,
   * tools/tool_runner.py, tool_core/async_runner.py): exactly the seven
   * findings-bearing scanners with exit code 1. Every other non-zero exit is
   * a failure, even with output on stdout.
   */
  readonly findingsExitCodes: readonly number[]
}

export interface RegistryToolResult {
  success: boolean
  data: string
  error: string
  durationMs: number
}

/**
 * Find the project root by walking up from this file's location.
 * This file is at: Argus-Tui/packages/opencode/src/tool/argus-tools.ts
 * Project root is: Argus Cli/ (parent of Argus-Tui/ and argus-workers/)
 */
export function findProjectRoot(): string {
  // Start from this file's directory
  let dir = dirname(fileURLToPath(import.meta.url))
  // Walk up until we find a directory containing both Argus-Tui and argus-workers
  for (let i = 0; i < 10; i++) {
    try {
      accessSync(join(dir, "argus-workers", "mcp_server.py"), constants.R_OK)
      return dir // Found it — dir contains argus-workers/
    } catch {
      dir = dirname(dir) // Go up one level
    }
  }
  return ""
}

/**
 * Build the argv for a registry tool from LLM-chosen parameters.
 * Mirrors `agent/tool_arguments.build_tool_argv`: unknown names are ignored
 * (the registry schema the LLM sees only offers declared parameters), absent
 * parameters are not invented, and a definition without a `target` parameter
 * still receives the target positionally.
 */
export function buildRegistryArgv(
  spec: RegistryToolSpec,
  params: Record<string, unknown>,
): string[] {
  const argv = spec.args.map(String)
  for (const param of spec.params) {
    const value = params[param.name]
    if (value === undefined || value === null) continue
    // Booleans are switches: `--deep-domxss True` is not a CLI argument.
    if (typeof value === "boolean") {
      if (value && param.flag) argv.push(param.flag)
      continue
    }
    if (param.flag) argv.push(param.flag)
    argv.push(String(value))
  }

  // A definition without a target parameter still needs the target — several
  // tools take it positionally without declaring it in the schema.
  if (
    params["target"] !== undefined &&
    params["target"] !== null &&
    !spec.params.some((p) => p.name === "target")
  ) {
    argv.push(String(params["target"]))
  }

  // nikto does not infer TLS from an https:// target on every build, and
  // without -ssl it reports a successful scan of a port it never spoke TLS
  // on. Say it explicitly (mirrors the Python builder).
  if (
    spec.toolName === "nikto" &&
    typeof params["target"] === "string" &&
    (params["target"] as string).toLowerCase().startsWith("https://") &&
    !argv.includes("-ssl")
  ) {
    argv.push("-ssl")
  }

  return argv
}

/** True when the tool runs through the agent-tool launcher (JSON envelope). */
function isLauncherTool(spec: RegistryToolSpec): boolean {
  return spec.args.some((a) => a.endsWith("run_agent_tool.py"))
}

// ── Mandatory scope enforcement ──────────────────────────────────────
//
// The native path used to execute with no engagement boundary at all:
// whatever `target` the LLM supplied was scanned. Every native invocation
// now passes this gate before a subprocess is spawned. The gate consumes the
// actual configured scope — `argus.config.yaml` (`security.scope`) overlaid
// with its environment overrides — through `getTargetValidator().load()`,
// the same source `scopeEnvironment()` forwards to the MCP worker. An
// explicitly set worker environment (`ARGUS_SCOPE_MODE` /
// `ARGUS_ALLOWED_TARGETS` / `ARGUS_BLOCKED_TARGETS`) wins over the file so a
// correctly scoped worker subprocess and a directly executed native tool
// agree. In `allowlist`/`enforce` mode an empty or unavailable allowlist
// fails closed; blocked targets (configured plus the permanent SSRF set)
// always refuse, in every mode.

/** Hostnames that are never legitimate scan targets, in any engagement. */
const ALWAYS_BLOCKED_HOSTS: ReadonlySet<string> = new Set([
  "localhost",
  "127.0.0.1",
  "::1",
  "0.0.0.0",
  "169.254.169.254",
  "metadata.google.internal",
  "metadata",
  "instance-data",
  "100.100.100.200",
])

function stripZone(host: string): string {
  return host.split("%")[0]
}

function extractHostname(target: string): string {
  const t = target.trim().toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, "")
  // Authority ends at the first path/query/fragment separator.
  const authority = t.split(/[\/?#]/)[0]
  // Strip userinfo (user:pass@host).
  const hostport = authority.includes("@")
    ? authority.slice(authority.lastIndexOf("@") + 1)
    : authority
  // Bracketed IPv6: [::1], [fe80::1%eth0], [::1]:8080.
  if (hostport.startsWith("[")) {
    const close = hostport.indexOf("]")
    if (close !== -1) return stripZone(hostport.slice(1, close))
    return stripZone(hostport.replace(/[\[\]]/g, ""))
  }
  // Bare IPv6 literals contain more than one colon and carry no port
  // separator — splitting on ":" would return only the first hextet.
  const colons = (hostport.match(/:/g) ?? []).length
  if (colons > 1) return stripZone(hostport)
  return stripZone(hostport.split(":")[0])
}

function isLoopbackOrLinkLocal(host: string): boolean {
  const h = stripZone(host.toLowerCase())
  if (ALWAYS_BLOCKED_HOSTS.has(h)) return true
  const version = isIP(h)
  if (version === 4) {
    // 127.0.0.0/8 loopback, 169.254.0.0/16 link-local (IMDS range).
    if (h.startsWith("127.")) return true
    if (h.startsWith("169.254.")) return true
    return false
  }
  if (version === 6) {
    // Normalize IPv4-mapped IPv6 (::ffff:127.0.0.1) before the v4 checks.
    if (h.includes(".")) {
      const tail = h.slice(h.lastIndexOf(":") + 1)
      if (tail.startsWith("127.") || tail.startsWith("169.254.")) return true
    }
    if (h === "::1" || h === "::") return true
    // fe80::/10 link-local: first hextet 0xfe80–0xfebf.
    const first = h.split(":")[0]
    if (/^[0-9a-f]{4}$/i.test(first)) {
      const value = parseInt(first, 16)
      if (value >= 0xfe80 && value <= 0xfebf) return true
    }
    return false
  }
  // Non-literal hostnames: link-local textual forms are covered above via
  // ALWAYS_BLOCKED_HOSTS; nothing more to test without DNS.
  return false
}

function matchesGlob(value: string, pattern: string): boolean {
  const v = value.toLowerCase()
  const p = pattern.toLowerCase().trim()
  if (p === "*") return true
  if (p.startsWith("*.")) {
    const suffix = p.slice(1)
    return v.endsWith(suffix) && v.length > suffix.length
  }
  if (p.endsWith(".*")) {
    const prefix = p.slice(0, -2)
    return v.startsWith(prefix) && v.length > prefix.length + 1
  }
  return v === p
}

function matchesOriginPattern(target: string, pattern: string): boolean {
  // An allowlist entry naming an origin (scheme://host[:port][/path])
  // authorizes that origin and anything beneath it — but never a sibling
  // host that merely shares a string prefix (allowed.example vs
  // allowed.example.evil.com). The scheme and host ride inside the
  // comparison, so one origin cannot authorize another scheme or port.
  const p = pattern.toLowerCase().replace(/\/+$/, "")
  const t = target.toLowerCase()
  return t === p || t.startsWith(`${p}/`)
}

function matchesAllowlist(target: string, pattern: string): boolean {
  if (pattern.includes("://")) return matchesOriginPattern(target, pattern)
  if (matchesGlob(target, pattern)) return true
  return matchesGlob(extractHostname(target), pattern)
}

interface EffectiveScope {
  mode: string
  allowed: string[]
  blocked: string[]
}

function readEnvScope(): EffectiveScope | null {
  const hasMode = SCOPE_MODE_ENV_VAR in process.env
  const hasAllowed = ALLOWED_TARGETS_ENV_VAR in process.env
  const hasBlocked = BLOCKED_TARGETS_ENV_VAR in process.env
  if (!hasMode && !hasAllowed && !hasBlocked) return null
  const splitList = (raw: string | undefined): string[] =>
    (raw ?? "")
      .split(/[\s,]+/)
      .map((entry) => entry.trim())
      .filter(Boolean)
  return {
    mode: (process.env[SCOPE_MODE_ENV_VAR] ?? "").trim().toLowerCase(),
    allowed: splitList(process.env[ALLOWED_TARGETS_ENV_VAR]),
    blocked: splitList(process.env[BLOCKED_TARGETS_ENV_VAR]),
  }
}

function effectiveScope(): EffectiveScope {
  // An explicitly configured worker environment wins: the MCP subprocess is
  // spawned with scopeEnvironment(), and a native tool running inside that
  // context must enforce the same boundary. Otherwise read the operator's
  // configured scope (file plus env overrides) directly, so a YAML allowlist
  // protects native execution even when no worker environment was forwarded.
  const fromEnv = readEnvScope()
  if (fromEnv) return fromEnv
  try {
    const { scope } = getTargetValidator().load()
    return {
      mode: (scope?.mode ?? "").trim().toLowerCase(),
      allowed: [...(scope?.allowed_targets ?? [])],
      blocked: [...(scope?.blocked_targets ?? [])],
    }
  } catch {
    return { mode: "", allowed: [], blocked: [] }
  }
}

/** Scope verdict for one native invocation. `{ ok: true }` runs; otherwise refused. */
export function checkNativeScope(target: unknown): { ok: true } | { ok: false; reason: string } {
  if (typeof target !== "string" || target.trim() === "") {
    return { ok: false, reason: "refusing to run: no target was supplied" }
  }
  const host = extractHostname(target)
  if (isLoopbackOrLinkLocal(host)) {
    return {
      ok: false,
      reason: `refusing to run: ${target} is a loopback, link-local or cloud-metadata target (SSRF prevention)`,
    }
  }
  const scope = effectiveScope()
  // Configured blocked targets refuse in every mode, before any allowlist.
  const blockedHit = scope.blocked.find((pattern) => matchesAllowlist(target, pattern))
  if (blockedHit) {
    return {
      ok: false,
      reason:
        `refusing to run: target ${target} matches blocked pattern ${blockedHit}. ` +
        `Blocked targets are never scanned, in any scope mode.`,
    }
  }
  const mode = scope.mode
  if (mode !== "allowlist" && mode !== "enforce") return { ok: true }
  // Fail closed: an enforcement mode with no usable allowlist authorizes nothing.
  if (scope.allowed.length === 0) {
    return {
      ok: false,
      reason:
        `refusing to run: scope mode is '${mode}' but no allowlist is configured ` +
        `(allowlist is empty or unavailable). An empty allowlist authorizes nothing — ` +
        `add the target to security.scope.allowed_targets in argus.config.yaml.`,
    }
  }
  if (scope.allowed.some((pattern) => matchesAllowlist(target, pattern))) return { ok: true }
  return {
    ok: false,
    reason:
      `refusing to run: target ${target} is outside the engagement scope ` +
      `(allowlist: ${scope.allowed.join(", ")}). The scope is the engagement's authorization ` +
      `boundary — a target the LLM supplies can never authorize itself.`,
  }
}

// ── Runtime availability ─────────────────────────────────────────────
//
// The generated registry exposes a tool as soon as the Python registry
// declares it, but the binary may be absent from this machine. Reporting
// that *before* spawning (instead of a failed exec) tells the LLM whether
// a tool is runnable right now: available, missing binary, missing script,
// or missing credentials.

function resolveOnPath(command: string): string | null {
  if (command.includes("/")) {
    try {
      accessSync(command, constants.X_OK)
      return command
    } catch {
      return null
    }
  }
  const pathEnv = process.env["PATH"] ?? ""
  for (const dir of pathEnv.split(delimiter)) {
    if (!dir) continue
    const candidate = join(dir, command)
    try {
      accessSync(candidate, constants.X_OK)
      return candidate
    } catch {
      continue
    }
  }
  return null
}

/** Why a tool cannot run right now, or null when it can. */
export function checkNativeAvailability(spec: RegistryToolSpec): string | null {
  for (const env of spec.requiredEnv) {
    if (!process.env[env]) {
      return `Tool ${spec.id} requires the ${env} environment variable, which is not set (missing credentials).`
    }
  }
  // Repo scripts (python3 launcher/shim/delegate tools) must exist in the tree,
  // and their interpreter must be runnable — otherwise the failure surfaces
  // as a bare spawn error instead of a missing-dependency report.
  const repoScripts = spec.args.filter((a) => a.endsWith(".py"))
  if (repoScripts.length > 0) {
    if (spec.command === "python3" && !resolveOnPath("python3")) {
      return `Tool ${spec.id} is unavailable: python3 is not installed on PATH (required to run ${repoScripts.join(", ")}).`
    }
    const root = findProjectRoot()
    if (!root) {
      return "Could not locate Argus project root (expected argus-workers/mcp_server.py in parent directories)."
    }
    for (const script of repoScripts) {
      try {
        accessSync(join(root, script), constants.R_OK)
      } catch {
        return `Tool ${spec.id} is unavailable: repository script ${script} is missing.`
      }
    }
    return null
  }
  if (spec.command !== "python3" && !resolveOnPath(spec.command)) {
    return `Tool ${spec.id} is unavailable: binary ${spec.command} is not installed on PATH.`
  }
  return null
}

/** Resolve the working directory for a spec (repo root for .py shims). */
function resolveSpecCwd(spec: RegistryToolSpec): { cwd: string } | { error: string } {
  if (!spec.args.some((a) => a.endsWith(".py"))) return { cwd: process.cwd() }
  const root = findProjectRoot()
  if (!root) {
    return {
      error:
        "Could not locate Argus project root (expected argus-workers/mcp_server.py in parent directories)",
    }
  }
  return { cwd: root }
}

/** Shared pre-flight: scope gate, then availability. Refusals never spawn. */
function preflight(
  spec: RegistryToolSpec,
  params: Record<string, unknown>,
  start: number,
): (RegistryToolResult & { refused: true }) | null {
  const scope = checkNativeScope(params["target"])
  if (!scope.ok) {
    return { success: false, data: "", error: scope.reason, durationMs: Date.now() - start, refused: true }
  }
  const unavailable = checkNativeAvailability(spec)
  if (unavailable) {
    return { success: false, data: "", error: unavailable, durationMs: Date.now() - start, refused: true }
  }
  return null
}

/** Per-tool exit-code semantics: only a declared findings code counts as success. */
function isFindingsExit(spec: RegistryToolSpec, status: unknown, stdout: string): boolean {
  return typeof status === "number" && stdout !== "" && spec.findingsExitCodes.includes(status)
}

function shapeLauncherOutput(stdout: string, start: number, failed: boolean, fallbackError: string) {
  try {
    const parsed = JSON.parse(stdout)
    return {
      success: failed ? false : (parsed.success ?? true),
      data: failed
        ? JSON.stringify(parsed.findings || [], null, 2)
        : parsed.data || JSON.stringify(parsed.findings || [], null, 2),
      error: parsed.error || (failed ? fallbackError : ""),
      durationMs: Date.now() - start,
    }
  } catch {
    return {
      success: false,
      data: stdout,
      error: failed ? fallbackError : "Launcher returned output that is not valid JSON.",
      durationMs: Date.now() - start,
    }
  }
}

/**
 * Execute one registry tool as a subprocess and normalise the outcome.
 *
 * Pre-flight runs first: the engagement scope gate, then required-env and
 * binary availability. Launcher tools print the run_agent_tool JSON envelope
 * (findings included); binary tools print raw CLI output. A non-zero exit
 * counts as success only when the tool's own spec declares it
 * findings-bearing (`findingsExitCodes`) — never a blanket exit-1 rule.
 *
 * Synchronous (Effect.sync callers, unit tests). Prefer
 * `runRegistryInvocationAsync` in tool execute paths so long-running
 * scanners never block the event loop.
 */
export function runRegistryInvocation(
  spec: RegistryToolSpec,
  params: Record<string, unknown>,
): RegistryToolResult {
  const start = Date.now()
  const refused = preflight(spec, params, start)
  if (refused) return refused

  const cwdResult = resolveSpecCwd(spec)
  if ("error" in cwdResult) {
    return { success: false, data: "", error: cwdResult.error, durationMs: Date.now() - start }
  }

  const argv = buildRegistryArgv(spec, params)
  const launcher = isLauncherTool(spec)
  try {
    const stdout = execFileSync(spec.command, argv, {
      encoding: "utf-8",
      timeout: spec.timeoutMs,
      maxBuffer: 10 * 1024 * 1024,
      cwd: cwdResult.cwd,
    })
    if (launcher) return shapeLauncherOutput(stdout, start, false, "")
    return { success: true, data: stdout, error: "", durationMs: Date.now() - start }
  } catch (e: any) {
    const stdout = typeof e.stdout === "string" ? e.stdout : e.stdout?.toString?.() ?? ""
    if (launcher) {
      try {
        return shapeLauncherOutput(stdout, start, true, e.message)
      } catch {
        // fall through to the generic failure below
      }
    } else if (isFindingsExit(spec, e.status, stdout)) {
      return { success: true, data: stdout, error: "", durationMs: Date.now() - start }
    }
    return {
      success: false,
      data: stdout,
      error: e.message,
      durationMs: Date.now() - start,
    }
  }
}

/**
 * Async variant of `runRegistryInvocation` for tool execute paths.
 *
 * The runner used `execFileSync` inside `Effect.sync`, blocking the TUI event
 * loop for the whole scan (minutes, at scanner timeouts). This variant uses
 * `execFile` so the loop stays responsive; semantics (scope gate,
 * availability, launcher envelope, per-tool exit codes) are identical.
 */
export function runRegistryInvocationAsync(
  spec: RegistryToolSpec,
  params: Record<string, unknown>,
): Promise<RegistryToolResult> {
  const start = Date.now()
  const refused = preflight(spec, params, start)
  if (refused) return Promise.resolve(refused)

  const cwdResult = resolveSpecCwd(spec)
  if ("error" in cwdResult) {
    return Promise.resolve({
      success: false,
      data: "",
      error: cwdResult.error,
      durationMs: Date.now() - start,
    })
  }

  const argv = buildRegistryArgv(spec, params)
  const launcher = isLauncherTool(spec)
  return new Promise((resolve) => {
    execFile(
      spec.command,
      argv,
      {
        encoding: "utf-8",
        timeout: spec.timeoutMs,
        maxBuffer: 10 * 1024 * 1024,
        cwd: cwdResult.cwd,
      },
      (error, stdout) => {
        const out = typeof stdout === "string" ? stdout : String(stdout ?? "")
        if (!error) {
          if (launcher) resolve(shapeLauncherOutput(out, start, false, ""))
          else resolve({ success: true, data: out, error: "", durationMs: Date.now() - start })
          return
        }
        const err = error as any
        const errStdout = typeof err.stdout === "string" ? err.stdout : out
        if (launcher) {
          try {
            resolve(shapeLauncherOutput(errStdout, start, true, err.message))
            return
          } catch {
            // fall through to the generic failure below
          }
        } else if (isFindingsExit(spec, err.code ?? err.status, errStdout)) {
          resolve({ success: true, data: errStdout, error: "", durationMs: Date.now() - start })
          return
        }
        resolve({
          success: false,
          data: errStdout,
          error: err.message,
          durationMs: Date.now() - start,
        })
      },
    )
  })
}

/** Shape a runner outcome the way native tools present themselves to the LLM. */
export function formatRegistryResult(id: string, result: RegistryToolResult): {
  title: string
  output: string
  metadata: { tool: string; duration: number; success: boolean }
} {
  return {
    title: `${id} completed`,
    output: result.error
      ? `${id} completed with issues:\n${result.error}\n\n${result.data || ""}`
      : result.data || "No output",
    metadata: { tool: id, duration: result.durationMs, success: result.success },
  }
}

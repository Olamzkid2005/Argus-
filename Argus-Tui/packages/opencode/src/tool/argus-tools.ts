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
import { join, dirname } from "path"
import { fileURLToPath } from "url"
import { accessSync, constants } from "fs"
import { execFileSync } from "child_process"

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
  /** Registry risk tier (low, medium, high, critical). */
  readonly risk: string
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

/**
 * Execute one registry tool as a subprocess and normalise the outcome.
 *
 * Launcher tools print the run_agent_tool JSON envelope (findings included);
 * binary tools print raw CLI output. Several scanners exit non-zero when they
 * find something (nuclei, dalfox, semgrep, …) — mirroring the worker's
 * FINDINGS_EXIT_CODES, exit 1 with output on stdout counts as success.
 */
export function runRegistryInvocation(
  spec: RegistryToolSpec,
  params: Record<string, unknown>,
): RegistryToolResult {
  const start = Date.now()
  for (const env of spec.requiredEnv) {
    if (!process.env[env]) {
      return {
        success: false,
        data: "",
        error: `Tool ${spec.id} requires the ${env} environment variable, which is not set.`,
        durationMs: Date.now() - start,
      }
    }
  }

  const usesRepoScripts = spec.args.some((a) => a.endsWith(".py"))
  let cwd = process.cwd()
  if (usesRepoScripts) {
    const root = findProjectRoot()
    if (!root) {
      return {
        success: false,
        data: "",
        error:
          "Could not locate Argus project root (expected argus-workers/mcp_server.py in parent directories)",
        durationMs: Date.now() - start,
      }
    }
    cwd = root
  }

  const argv = buildRegistryArgv(spec, params)
  const launcher = isLauncherTool(spec)
  try {
    const stdout = execFileSync(spec.command, argv, {
      encoding: "utf-8",
      timeout: spec.timeoutMs,
      maxBuffer: 10 * 1024 * 1024,
      cwd,
    })
    if (launcher) {
      try {
        const parsed = JSON.parse(stdout)
        return {
          success: parsed.success ?? true,
          data: parsed.data || JSON.stringify(parsed.findings || [], null, 2),
          error: parsed.error || "",
          durationMs: Date.now() - start,
        }
      } catch {
        return {
          success: false,
          data: stdout,
          error: "Launcher returned output that is not valid JSON.",
          durationMs: Date.now() - start,
        }
      }
    }
    return { success: true, data: stdout, error: "", durationMs: Date.now() - start }
  } catch (e: any) {
    const stdout = typeof e.stdout === "string" ? e.stdout : e.stdout?.toString?.() ?? ""
    if (launcher) {
      // Try to parse partial output on failure
      try {
        const parsed = JSON.parse(stdout)
        return {
          success: false,
          data: JSON.stringify(parsed.findings || [], null, 2),
          error: parsed.error || e.message,
          durationMs: Date.now() - start,
        }
      } catch {
        // fall through to the generic failure below
      }
    } else if (e.status === 1 && stdout) {
      // Findings-bearing exit (nuclei, dalfox, semgrep, gitleaks, trivy, …):
      // the output is the result, not an error.
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

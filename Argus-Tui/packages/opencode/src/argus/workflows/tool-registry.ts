/**
 * TypeScript-side tool registry for the Argus planner.
 *
 * This is INTENTIONALLY SEPARATE from the Python-side TOOLS dict in
 * argus-workers/tool_definitions.py. Different schema, different purpose:
 *   - TS side (this file): planning metadata (capabilities, scoring,
 *     consumes/provides for dependency resolution, auth gating)
 *   - Python side: execution metadata (phases, params, commands, timeouts,
 *     signal quality, risk levels, exploit categories)
 *
 * Python source of truth: argus-workers/tool_definitions.py
 *   - YAML source: argus-workers/tools/definitions/*.yaml
 *   - Inline overrides: tool_definitions.py itself
 *
 * Data is loaded from tool-definitions.yaml (same directory).
 * When adding a tool here, also add its execution metadata to the Python side.
 */

import { readFileSync } from "fs"
import YAML from "yaml"
import { Capability } from "../shared/capabilities"
import type { SignalQuality } from "../bridge/types"
import { ToolConfig } from "../config/tool-config"

export interface RequiresGate {
  /** Tool only runs if the target tech stack contains one of these strings */
  tech_contains?: string[]
  /** Tool only runs if recon has published these signals */
  recon_signals?: string[]
  /** Tool only runs if the target URL scheme matches one of these */
  target_scheme?: string[]
  /** Tool only runs if credentials are configured (requires credential context) */
  credentials?: boolean
}

export interface ToolDef {
  name: string
  label: string
  capabilities: string[]
  requires_auth: boolean
  destructive: boolean
  credential_roles?: string[]
  supports_api: boolean
  supports_web: boolean
  timeout_seconds: number
  scoring?: {
    confidence_score: number
    coverage_score: number
  }
  /** Planner intelligence — these are read from the MCP tool definitions at runtime */
  signal_quality?: SignalQuality
  requires?: RequiresGate
  priority?: number
  cost?: "low" | "medium" | "high"
  /** Minimum required version (semver) */
  min_version?: string
  /** Shell command to get the installed version */
  version_cmd?: string
  /** Regex to extract version from command output */
  version_regex?: string
  /** Data signals this tool consumes (needs from prior tools) */
  consumes?: string[]
  /** Data signals this tool produces (makes available to downstream tools) */
  provides?: string[]
}

interface ToolDefsFile {
  tools: ToolDef[]
}

/** CostFilter — controls which tools are considered based on their cost tier. */
export type CostFilter = "all" | "low_only" | "no_high"

/** Cost ranking for tool selection tiebreaker (lower = cheaper, more preferred). */
const COST_RANK: Record<string, number> = { low: 1, medium: 2, high: 3 }

/** Filter context used by requires gates when selecting tools. */
export interface GateContext {
  /** Tech stack detected from recon findings (e.g. ["python", "react", "graphql"]) */
  techStack?: string[]
  /** Target URL scheme (e.g. "http" or "https") */
  targetScheme?: string
  /** Recon signals published by earlier phases (e.g. "parameterized_forms", "has_api") */
  reconSignals?: string[]
  /** Credential role names available in the credential store (e.g. ["attacker", "victim"]) */
  availableCredentialRoles?: string[]
  /** Whether any credentials at all are configured */
  hasAnyCredentials?: boolean
}

/**
 * Execution state the worker reports for one tool over MCP `list_tools`.
 *
 * Phase selection happens on this side, so the worker's own view of what it
 * can run never reached the planner: `phases=[]` in
 * `argus-workers/tool_definitions.py` had no effect and the run dispatched
 * dnsx/gospider (both deliberately disabled) plus tools whose binary is not
 * installed, collecting usage errors for each. These fields are the channel.
 */
export interface WorkerToolStatus {
  name: string
  /** Worker cannot run this tool at all (no phase, or an in-process step). */
  disabled?: boolean
  /** Why, in the worker's words — surfaced in the skip message. */
  disabled_reason?: string
  /** Entry names an in-process orchestrator step, not a subprocess. */
  pipeline_step?: boolean
  /** Tool binary is present on the worker's execution PATH. */
  available?: boolean
}

export class ToolRegistry {
  private toolsByCapability = new Map<Capability, ToolDef[]>()
  private toolsByName = new Map<string, ToolDef>()
  private toolConfig: ToolConfig = new ToolConfig()
  /** tool name → reason the worker cannot run it. Empty until the MCP
   *  worker has reported its tool list; see setWorkerToolStatus(). */
  private workerBlocked = new Map<string, string>()

  setConfig(tc: ToolConfig): void {
    this.toolConfig = tc
  }

  /**
   * Record the worker's execution state for every tool it advertises.
   *
   * Call once the MCP bridge is connected and before tools are dispatched.
   * Replaces any previous snapshot — the worker is restarted with a new build
   * or a tool is installed mid-session. Tools the worker does not mention at
   * all are left alone (an unreported tool is not evidence of breakage).
   *
   * @returns the tools newly blocked, for logging/audit.
   */
  setWorkerToolStatus(tools: WorkerToolStatus[]): Array<{ name: string; reason: string }> {
    const blocked: Array<{ name: string; reason: string }> = []
    this.workerBlocked.clear()
    for (const tool of tools) {
      if (tool.disabled) {
        this.workerBlocked.set(tool.name, tool.disabled_reason ?? "disabled by the worker")
        blocked.push({ name: tool.name, reason: this.workerBlocked.get(tool.name)! })
      } else if (tool.available === false) {
        const reason = "binary not installed on the worker PATH"
        this.workerBlocked.set(tool.name, reason)
        blocked.push({ name: tool.name, reason })
      }
    }
    return blocked
  }

  /** Why the worker cannot run *toolName*, or undefined if it can. */
  getWorkerBlockReason(toolName: string): string | undefined {
    return this.workerBlocked.get(toolName)
  }

  /** True when the worker is known to be unable to run *toolName*. */
  isWorkerBlocked(toolName: string): boolean {
    return this.workerBlocked.has(toolName)
  }

  /** Every tool the worker has reported as unrunnable, with the reason. */
  listWorkerBlocked(): Array<{ name: string; reason: string }> {
    return Array.from(this.workerBlocked, ([name, reason]) => ({ name, reason }))
  }

  load(definitionsPath: string): void {
    let content: string
    let parsed: ToolDefsFile
    try {
      content = readFileSync(definitionsPath, "utf-8")
      parsed = YAML.parse(content)
    } catch (err) {
      throw new Error(`Failed to read or parse tool definitions file '${definitionsPath}': ${(err as Error).message}`)
    }

    if (!parsed?.tools || !Array.isArray(parsed.tools)) {
      throw new Error(`Tool definitions file ${definitionsPath} is missing the 'tools' key or it is not an array`)
    }

    for (const tool of parsed.tools) {
      this.toolsByName.set(tool.name, tool)

      for (const cap of tool.capabilities) {
        if (!Object.values(Capability).includes(cap as Capability)) {
          throw new Error(`Tool '${tool.name}' declares unknown capability '${cap}'`)
        }
        const c = cap as Capability
        if (!this.toolsByCapability.has(c)) {
          this.toolsByCapability.set(c, [])
        }
        this.toolsByCapability.get(c)!.push(tool)
      }
    }
  }

  getToolsByCapability(cap: Capability): ToolDef[] {
    const all = this.toolsByCapability.get(cap) ?? []
    return all.filter(t => this.toolConfig.isEnabled(t.name) && !this.workerBlocked.has(t.name))
  }

  /**
   * Every tool definition that declares *cap*, usable or not, with the reason
   * it cannot run. Used to explain a capability gap: an operator needs to know
   * which tool would provide the capability, not just that nothing ran.
   */
  listCapabilityProviders(cap: Capability): Array<{ name: string; usable: boolean; reason?: string }> {
    const all = this.toolsByCapability.get(cap) ?? []
    return all.map(t => {
      const reason = this.workerBlocked.get(t.name) ?? (this.toolConfig.isEnabled(t.name) ? undefined : "disabled in tool config")
      return { name: t.name, usable: reason === undefined, reason }
    })
  }

  /**
   * One sentence naming a capability that cannot run and the tools that would
   * provide it. A missing optional tool is a skip with a reason, never a phase
   * failure, so this text is what the operator sees instead of "failed".
   */
  describeCapabilityGap(cap: Capability): string {
    const providers = this.listCapabilityProviders(cap)
    if (providers.length === 0) {
      return `no tool provides capability "${cap}" (no tool definition declares it) — nothing to run, skipped`
    }
    const names = providers.map(p => p.name).join(", ")
    return `capability "${cap}" has no usable tool (providers: ${names}) — skipped`
  }

  /**
   * Human-readable catalogue of the tools eligible for *capabilities* — the
   * context the workflow-planning LLM reasons over instead of bare
   * capability names. Each line names one runnable tool, what it does, and
   * which capabilities it provides, so the model can select specific tools
   * (e.g. the GraphQL scanner when GraphQL is discovered) rather than only
   * suggesting an abstract capability the registry resolves later.
   *
   * Only tools that survive the eligibility filters (enabled, worker-known
   * runnable, target-type and requires gates) are listed: the LLM never sees
   * a tool it cannot actually run.
   */
  describeToolsForCapabilities(capabilities: Capability[], targetType?: string, gateContext?: GateContext): string {
    const tools = this.selectBest(capabilities, targetType, gateContext)
    if (tools.length === 0) return "No eligible tools for the requested capabilities."
    return tools
      .map((t) => {
        const caps = t.capabilities.join(", ")
        const cost = t.cost ? `cost ${t.cost}` : "cost unknown"
        return `- ${t.name}: ${t.label} (provides: ${caps}; ${cost})`
      })
      .join("\n")
  }

  /**
   * Catalogue of every tool eligible to run against this target right now.
   * The replan LLM sees this before suggesting next steps, so its choices
   * are grounded in tools that exist and can run — not capability names it
   * hopes something provides.
   */
  describeAllEligibleTools(targetType?: string, gateContext?: GateContext): string {
    const seen = new Map<string, ToolDef>()
    for (const cap of Object.values(Capability)) {
      for (const tool of this.selectBest([cap], targetType, gateContext)) {
        seen.set(tool.name, tool)
      }
    }
    if (seen.size === 0) return "No eligible tools for this target."
    return Array.from(seen.values())
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((t) => `- ${t.name}: ${t.label} (provides: ${t.capabilities.join(", ")})`)
      .join("\n")
  }

  getCapabilities(toolName: string): string[] {
    return this.toolsByName.get(toolName)?.capabilities ?? []
  }

  getTool(name: string): ToolDef | undefined {
    return this.toolsByName.get(name)
  }

  listTools(): ToolDef[] {
    return Array.from(this.toolsByName.values())
  }

  getToolTimeout(toolName: string): number {
    const custom = this.toolConfig.getTimeout(toolName)
    if (custom !== undefined) return custom
    return this.toolsByName.get(toolName)?.timeout_seconds ?? 120
  }

  /** @deprecated Use selectBest() instead */
  findBestTools(capabilities: Capability[], targetType: string): ToolDef[] {
    return this.selectBest(capabilities, targetType)
  }

  /**
   * Select the best tools for the given capabilities, optionally filtered
   * by requires gates (tech_contains, target_scheme) and cost filter.
   *
   * Tools with unmet requires gates are filtered out. Remaining tools are
   * ranked by scoring (confidence + coverage), then by priority.
   *
   * When a costFilter is active, a safety net ensures capabilities are never
   * left uncovered: if every tool for a given capability would be removed,
   * the unfiltered set is kept for that capability.
   */
  selectBest(capabilities: Capability[], targetType?: string, gateContext?: GateContext, costFilter?: CostFilter): ToolDef[] {
    const candidates = new Map<string, { tool: ToolDef; score: number }>()

    for (const cap of capabilities) {
      const tools = this.getToolsByCapability(cap)
      for (const tool of tools) {
        // The worker's own verdict outranks this static registry: never plan a
        // tool the worker cannot run (disabled, or its binary is absent).
        if (this.workerBlocked.has(tool.name)) continue

        // Filter by target type (web vs api vs non-web)
        // detectTargetType returns "web_app"|"api"|"spa"|"unknown", not "web"
        if ((targetType === "web" || targetType === "web_app" || targetType === "spa") && tool.supports_web === false) {
          continue
        }
        if (targetType === "api" && tool.supports_api === false) {
          continue
        }

        // Apply requires gates if context is available
        if (gateContext && !this.passesGates(tool, gateContext)) {
          continue
        }

        const current = candidates.get(tool.name)
        const score = (tool.scoring?.confidence_score ?? 50) + (tool.scoring?.coverage_score ?? 50)

        if (!current || score > current.score) {
          candidates.set(tool.name, { tool, score })
        }
      }
    }

    // Apply cost filter with safety net: never leave a capability uncovered
    if (costFilter && costFilter !== "all") {
      const survivingCaps = new Set<Capability>()
      for (const { tool } of candidates.values()) {
        if (this._passesCostFilter(tool, costFilter)) {
          for (const cap of tool.capabilities) {
            if (capabilities.includes(cap as Capability)) {
              survivingCaps.add(cap as Capability)
            }
          }
        }
      }

      // Remove tools that fail the cost filter, unless they serve a capability
      // that would be left with zero tools (safety net)
      for (const [name, { tool, score }] of candidates) {
        const passes = this._passesCostFilter(tool, costFilter)
        const servesEmptyCap = tool.capabilities.some((c) =>
          capabilities.includes(c as Capability) && !survivingCaps.has(c as Capability),
        )
        if (!passes && !servesEmptyCap) {
          candidates.delete(name)
        }
      }
    }

    return Array.from(candidates.values())
      .sort((a, b) => {
        // Sort by score desc, then by priority desc, then by cost asc (prefer cheaper)
        if (b.score !== a.score) return b.score - a.score
        if ((b.tool.priority ?? 50) !== (a.tool.priority ?? 50)) return (b.tool.priority ?? 50) - (a.tool.priority ?? 50)
        // Cost tiebreaker: prefer lower cost when scores and priorities are tied
        return (COST_RANK[a.tool.cost ?? "medium"]) - (COST_RANK[b.tool.cost ?? "medium"])
      })
      .map((c) => c.tool)
  }

  /** Check whether a tool passes the given cost filter. Low-cost tools pass all filters. */
  private _passesCostFilter(tool: ToolDef, costFilter: CostFilter): boolean {
    const cost = tool.cost ?? "medium"
    if (costFilter === "low_only") return cost === "low"
    if (costFilter === "no_high") return cost !== "high"
    return true
  }

  /**
   * Check whether a tool passes its requires gates given the current context.
   * All declared gates must pass (AND logic). Undeclared gates are skipped.
   */
  private passesGates(tool: ToolDef, context: GateContext): boolean {
    const requires = tool.requires
    if (!requires) return true

    // tech_contains: tool only runs if target tech stack contains at least one match
    if (requires.tech_contains && requires.tech_contains.length > 0) {
      const stack = context.techStack ?? []
      const hasMatch = requires.tech_contains.some((t) =>
        stack.some((s) => s.toLowerCase().includes(t.toLowerCase())),
      )
      if (!hasMatch) return false
    }

    // target_scheme: tool only runs if target URL scheme matches
    if (requires.target_scheme && requires.target_scheme.length > 0) {
      const scheme = context.targetScheme ?? "https"
      if (!requires.target_scheme.includes(scheme)) return false
    }

    // recon_signals: tool only runs if recon has published matching signals.
    // If no recon_signals context is provided, the gate is skipped (no data yet).
    // If context IS provided (even empty), ALL required signals must be present (AND logic).
    if (requires.recon_signals && requires.recon_signals.length > 0) {
      // No recon data yet — skip gate (don't block tools while recon is pending)
      if (context.reconSignals === undefined) {
        // pass through — planner hasn't populated signals yet
      } else {
        const hasAllSignals = requires.recon_signals.every((s) =>
          (context.reconSignals ?? []).some((sig) =>
            sig.toLowerCase().includes(s.toLowerCase()),
          ),
        )
        if (!hasAllSignals) return false
      }
    }

    // credentials: tool only runs if credentials are configured.
    // When requires.credentials is true, the planner must provide credential context.
    // If no credential context is available, skip the gate (don't block tools during
    // planning when credential info hasn't been gathered yet).
    // But if context explicitly says no credentials, block the tool.
    if (requires.credentials === true) {
      if (context.hasAnyCredentials === false) return false
      // If context.hasAnyCredentials is undefined, we haven't checked yet — pass through
    }

    return true
  }
}

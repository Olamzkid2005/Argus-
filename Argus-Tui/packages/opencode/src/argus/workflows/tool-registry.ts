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

export class ToolRegistry {
  private toolsByCapability = new Map<Capability, ToolDef[]>()
  private toolsByName = new Map<string, ToolDef>()
  private toolConfig: ToolConfig = new ToolConfig()

  setConfig(tc: ToolConfig): void {
    this.toolConfig = tc
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
    return all.filter(t => this.toolConfig.isEnabled(t.name))
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

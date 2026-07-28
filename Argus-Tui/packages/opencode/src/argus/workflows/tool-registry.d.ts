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
import { Capability } from "../shared/capabilities";
import type { SignalQuality } from "../bridge/types";
import { ToolConfig } from "../config/tool-config";
export interface RequiresGate {
    /** Tool only runs if the target tech stack contains one of these strings */
    tech_contains?: string[];
    /** Tool only runs if recon has published these signals */
    recon_signals?: string[];
    /** Tool only runs if the target URL scheme matches one of these */
    target_scheme?: string[];
    /** Tool only runs if credentials are configured (requires credential context) */
    credentials?: boolean;
}
export interface ToolDef {
    name: string;
    label: string;
    capabilities: string[];
    requires_auth: boolean;
    destructive: boolean;
    credential_roles?: string[];
    supports_api: boolean;
    supports_web: boolean;
    timeout_seconds: number;
    scoring?: {
        confidence_score: number;
        coverage_score: number;
    };
    /** Planner intelligence — these are read from the MCP tool definitions at runtime */
    signal_quality?: SignalQuality;
    requires?: RequiresGate;
    priority?: number;
    cost?: "low" | "medium" | "high";
    /** Minimum required version (semver) */
    min_version?: string;
    /** Shell command to get the installed version */
    version_cmd?: string;
    /** Regex to extract version from command output */
    version_regex?: string;
    /** Data signals this tool consumes (needs from prior tools) */
    consumes?: string[];
    /** Data signals this tool produces (makes available to downstream tools) */
    provides?: string[];
}
/** CostFilter — controls which tools are considered based on their cost tier. */
export type CostFilter = "all" | "low_only" | "no_high";
/** Filter context used by requires gates when selecting tools. */
export interface GateContext {
    /** Tech stack detected from recon findings (e.g. ["python", "react", "graphql"]) */
    techStack?: string[];
    /** Target URL scheme (e.g. "http" or "https") */
    targetScheme?: string;
    /** Recon signals published by earlier phases (e.g. "parameterized_forms", "has_api") */
    reconSignals?: string[];
    /** Credential role names available in the credential store (e.g. ["attacker", "victim"]) */
    availableCredentialRoles?: string[];
    /** Whether any credentials at all are configured */
    hasAnyCredentials?: boolean;
}
export declare class ToolRegistry {
    private toolsByCapability;
    private toolsByName;
    private toolConfig;
    setConfig(tc: ToolConfig): void;
    load(definitionsPath: string): void;
    getToolsByCapability(cap: Capability): ToolDef[];
    getCapabilities(toolName: string): string[];
    getTool(name: string): ToolDef | undefined;
    listTools(): ToolDef[];
    getToolTimeout(toolName: string): number;
    /** @deprecated Use selectBest() instead */
    findBestTools(capabilities: Capability[], targetType: string): ToolDef[];
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
    selectBest(capabilities: Capability[], targetType?: string, gateContext?: GateContext, costFilter?: CostFilter): ToolDef[];
    /** Check whether a tool passes the given cost filter. Low-cost tools pass all filters. */
    private _passesCostFilter;
    /**
     * Check whether a tool passes its requires gates given the current context.
     * All declared gates must pass (AND logic). Undeclared gates are skipped.
     */
    private passesGates;
}

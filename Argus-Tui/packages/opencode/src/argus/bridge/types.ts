export interface ToolDefinition {
  name: string
  description: string
  inputSchema: {
    type: string
    properties: Record<string, { type: string; description: string; enum?: string[]; default?: unknown }>
    required: string[]
  }
  /** Capabilities this tool satisfies (e.g. "sqli_detection") */
  capabilities: string[]
  /** Signal quality tier for confidence baseline */
  signal_quality?: "CONFIRMED" | "PROBABLE" | "CANDIDATE"
  /** Gates that must pass before this tool is eligible */
  requires?: {
    tech_contains?: string[]
    recon_signals?: string[]
    target_scheme?: string[]
  }
  /** Ranking priority (0-100, higher = preferred) */
  priority?: number
  /** Execution cost tier */
  cost?: "low" | "medium" | "high"
  /**
   * Worker-reported execution state. The worker publishes these on every
   * `list_tools` entry; older worker builds omit them, which must read as
   * "the worker did not say" rather than "the tool is fine".
   */
  disabled?: boolean
  disabled_reason?: string
  pipeline_step?: boolean
  available?: boolean
}

export type SignalQuality = "CONFIRMED" | "PROBABLE" | "CANDIDATE"

export interface ToolResult {
  success: boolean
  data: unknown
  /**
   * Findings parsed by the worker's parser for this tool (`meta.data.structured`
   * on the MCP response). These — not `data` — are the findings; `data` is the
   * raw tool text, which is frequently just a CLI error.
   */
  structured?: Array<Record<string, unknown>>
  error?: string
  durationMs: number
  /** Signal quality tier from the tool definition, used by ConfidenceEngine as baseline */
  signalQuality?: SignalQuality
}

export interface MCPError {
  code: number
  message: string
  data?: unknown
}

export class LLMUnavailableError extends Error {
  constructor(
    public status: "DEGRADED" | "UNAVAILABLE",
    public retryAfter?: number,
  ) {
    super(`LLM ${status}`)
  }
}

export interface DriftReport {
  missing_from_registry: string[]
  missing_from_mcp: string[]
  capability_gaps: string[]
}

export type LLMStatus = "AVAILABLE" | "DEGRADED" | "UNAVAILABLE"

export type CacheMode = "normal" | "no_cache" | "refresh"

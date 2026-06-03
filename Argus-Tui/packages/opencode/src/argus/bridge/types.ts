export interface ToolDefinition {
  name: string
  label: string
  capabilities: string[]
  requires_auth: boolean
  destructive: boolean
  timeout_seconds: number
}

export interface ToolResult {
  success: boolean
  data: unknown
  error?: string
  durationMs: number
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

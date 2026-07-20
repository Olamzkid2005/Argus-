/**
 * LLM Planner Service — bridges the OpenCode Session LLM into the Argus planner.
 *
 * This service uses the @opencode-ai/llm package (which IS the OpenCode LLM
 * infrastructure) to:
 *   1. Suggest assessment phases/capabilities during initial planning
 *   2. Analyze accumulated findings and suggest next capabilities during replanning
 *
 * Architecture:
 *   LLMPlannerService.lazy() → creates singleton instance
 *     ↓
 *   Uses openai/anthropic providers from @opencode-ai/llm/providers/*
 *     → openai.model("gpt-4o-mini", { apiKey }) returns a Model with route
 *     → Route has protocol (OpenAI Chat), endpoint, auth, transport
 *     ↓
 *   LLM.generateObject() → forces structured output via synthetic tool call
 *     → Returns Effect<GenerateObjectResponse<T>>
 *     → Effect.runPromise wraps it for async/await usage
 *     ↓
 *   Returns structured capability suggestions for the planner
 */

import { Effect, Schema } from "effect"
import { LLM, type ToolSchema } from "@opencode-ai/llm"
import { LLMClient, RequestExecutor } from "@opencode-ai/llm/route"
import { openai } from "@opencode-ai/llm/providers/openai"
import { anthropic } from "@opencode-ai/llm/providers/anthropic"
import type { Model } from "@opencode-ai/llm/schema"

// ── Structured Output Schemas ────────────────────────────────────────
// These Effect Schemas define the shape of data the LLM must return.
// LLM.generateObject forces the LLM to call a synthetic tool that
// produces data matching this schema — no manual parsing needed.

/** Schema for a single LLM-suggested phase/capability. */
const PhaseSuggestionItemSchema = Schema.Struct({
  capabilities: Schema.Array(Schema.String),
  reasoning: Schema.String,
})

/** Wrapper schema for the full phase suggestion response. */
const PhaseSuggestionResponseSchema = Schema.Struct({
  target_analysis: Schema.String,
  suggested_phases: Schema.Array(PhaseSuggestionItemSchema),
})

/** Schema for replan suggestions from the LLM. */
const ReplanSuggestionSchema = Schema.Struct({
  next_capabilities: Schema.Array(Schema.String),
  reasoning: Schema.String,
  stop_assessment: Schema.Boolean,
})

// ── Public Types ─────────────────────────────────────────────────────

export interface LLMPhaseSuggestion {
  /** LLM-suggested capability strings (e.g. "sqli_detection", "xss_detection"). */
  readonly capabilities: string[]
  /** Natural-language reasoning for this suggestion. */
  readonly reasoning: string
}

export interface LLMReplanSuggestion {
  /** Suggested next capability strings. */
  readonly nextCapabilities: string[]
  /** Why the LLM suggests these capabilities. */
  readonly reasoning: string
  /** Whether the assessment should stop (all important findings found). */
  readonly stopAssessment: boolean
}

export interface LLMPhaseSuggestionResult {
  readonly targetAnalysis: string
  readonly suggestedPhases: LLMPhaseSuggestion[]
}

// ── Env Var Keys ─────────────────────────────────────────────────────

const ENV_OPENAI_KEY = "OPENAI_API_KEY"
const ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
const ENV_OPENCODE_KEY = "OPENCODE_API_KEY"
const ENV_PLANNER_MODEL = "ARGUS_PLANNER_MODEL"
const ENV_OPENCODE_MODEL = "OPENCODE_MODEL"

// ── LLM Planner Service ──────────────────────────────────────────────

export class LLMPlannerService {
  private static instance: LLMPlannerService | null = null
  private model: Model | null = null
  private initialized = false
  private initError: string | null = null
  private available = false

  // Private constructor — use LLMPlannerService.lazy()
  private constructor() {}

  /**
   * Get or create the singleton LLMPlannerService instance.
   * Initialization is lazy — the first call to any suggestion method
   * triggers setup. This keeps assessment start fast when LLM isn't needed.
   */
  static lazy(): LLMPlannerService {
    if (!LLMPlannerService.instance) {
      LLMPlannerService.instance = new LLMPlannerService()
    }
    return LLMPlannerService.instance
  }

  // ── Initialization ───────────────────────────────────────────────

  /**
   * Initialize the LLM client. Reads API keys and model config from
   * environment variables — same ones OpenCode uses for its provider
   * configuration (OPENAI_API_KEY, ANTHROPIC_API_KEY).
   *
   * Returns true if the LLM is available and ready.
   */
  private async ensureInitialized(): Promise<boolean> {
    if (this.initialized) return this.available

    try {
      const apiKey = this.resolveApiKey()
      if (!apiKey) {
        this.initError = [
          `No LLM API key found. Set one of:`,
          `  ${ENV_OPENAI_KEY}=sk-...`,
          `  ${ENV_ANTHROPIC_KEY}=sk-ant-...`,
          `  ${ENV_OPENCODE_KEY}=...`,
        ].join("\n")
        this.initialized = true
        this.available = false
        return false
      }

      const configured = this.resolveModel(apiKey)
      if (!configured) {
        this.initError = `Could not create LLM model. Check ARGUS_PLANNER_MODEL env var.`
        this.initialized = true
        this.available = false
        return false
      }

      this.model = configured
      this.initialized = true
      this.available = true
      return true
    } catch (e) {
      this.initError = `LLMPlannerService init failed: ${(e as Error).message}`
      this.initialized = true
      this.available = false
      return false
    }
  }

  /**
   * Check if the LLM service is available for use.
   * Triggers lazy initialization on first call.
   */
  async isAvailable(): Promise<boolean> {
    return this.ensureInitialized()
  }

  /** Get the initialization error message, if any. */
  getInitError(): string | null {
    return this.initError
  }

  // ── Planning Methods ──────────────────────────────────────────────

  /**
   * Use the LLM to suggest assessment phases/capabilities for a target.
   * Returns an empty array if the LLM is unavailable or the call fails.
   *
   * @param target - The target URL or identifier
   * @param targetType - Detected target type (web_app, api, spa, unknown)
   * @param techStack - Optional detected technologies
   * @returns Array of capability suggestions with reasoning
   */
  async suggestPhases(
    target: string,
    targetType: string,
    techStack?: string[],
  ): Promise<LLMPhaseSuggestionResult> {
    if (!(await this.ensureInitialized()) || !this.model) {
      return { targetAnalysis: "", suggestedPhases: [] }
    }

    const techContext = techStack?.length
      ? `\nDetected technologies: ${techStack.join(", ")}`
      : ""

    const systemPrompt = [
      `You are a security assessment planning assistant integrated into Argus, a penetration testing platform.`,
      `Your task is to analyze a target and suggest relevant assessment capabilities.`,
      ``,
      `Available capabilities (use these exact strings):`,
      `- web_recon: Web reconnaissance (whois, DNS, subdomain enumeration)`,
      `- port_scanning: TCP/UDP port scanning`,
      `- technology_detection: Technology stack fingerprinting`,
      `- content_discovery: Directory/file brute-forcing`,
      `- http_probe: HTTP probing and response analysis`,
      `- api_probing: API endpoint discovery and testing`,
      `- auth_detection: Authentication mechanism detection`,
      `- credential_analysis: Credential security analysis`,
      `- vulnerability_scanning: General vulnerability scanning`,
      `- template_scanning: CVE template-based scanning (nuclei)`,
      `- sqli_detection: SQL injection detection`,
      `- xss_detection: Cross-site scripting detection`,
      `- ssrf_check: Server-side request forgery testing`,
      `- command_injection: Command injection testing`,
      `- jwt_analysis: JWT token security analysis`,
      `- graphql_assessment: GraphQL endpoint security testing`,
      `- api_docs_analysis: API documentation analysis (Swagger/OpenAPI)`,
      `- browser_verification: Browser-based exploit verification`,
      `- report_generation: Generate assessment report`,
      ``,
      `Rules:`,
      `1. Always include web_recon and technology_detection for web targets`,
      `2. Include api_probing for API targets`,
      `3. Include port_scanning for network-facing targets`,
      `4. Include vulnerability_scanning and template_scanning for all web targets`,
      `5. Include browser_verification when dynamic testing is needed`,
      `6. Return capabilities in priority/execution order`,
      `7. Only suggest capabilities that are relevant to the target type`,
    ].join("\n")

    const userPrompt = [
      `Plan an assessment for:`,
      `- Target: ${target}`,
      `- Target type: ${targetType}${techContext}`,
      ``,
      `Suggest the most relevant capabilities in priority order.`,
      `Include your analysis of the target and reasoning for each suggestion.`,
    ].join("\n")

    try {
      const result = await Effect.runPromise(
        LLM.generateObject({
          model: this.model,
          system: systemPrompt,
          prompt: userPrompt,
          schema: PhaseSuggestionResponseSchema as ToolSchema<unknown>,
        }).pipe(
          Effect.provide(LLMClient.layer),
          Effect.provide(RequestExecutor.defaultLayer),
        ),
      )

      const data = result.object as {
        target_analysis: string
        suggested_phases: Array<{ capabilities: string[]; reasoning: string }>
      }

      return {
        targetAnalysis: data.target_analysis,
        suggestedPhases: data.suggested_phases.map((p) => ({
          capabilities: p.capabilities,
          reasoning: p.reasoning,
        })),
      }
    } catch (e) {
      console.warn(`[LLMPlanner] Phase suggestion failed: ${(e as Error).message}`)
      return { targetAnalysis: "", suggestedPhases: [] }
    }
  }

  /**
   * Use the LLM to analyze accumulated findings and suggest next capabilities.
   * Returns null if the LLM is unavailable or the call fails.
   *
   * @param target - The target being assessed
   * @param findings - Accumulated findings from completed phases
   * @returns Replan suggestion or null on failure
   */
  async suggestReplan(
    target: string,
    findings: ReadonlyArray<{
      title: string
      severity: number
      subtype?: string
      confidence: number
    }>,
  ): Promise<LLMReplanSuggestion | null> {
    if (!(await this.ensureInitialized()) || !this.model) {
      return null
    }

    if (findings.length === 0) {
      // No findings to analyze — LLM can't provide useful suggestions
      return null
    }

    const findingsSummary = findings
      .map(
        (f) =>
          `- [${f.severity >= 4 ? "CRITICAL" : f.severity >= 3 ? "HIGH" : f.severity >= 2 ? "MEDIUM" : "LOW"}] ${f.title} (${f.subtype ?? "unknown"}, confidence: ${f.confidence}/5)`,
      )
      .join("\n")

    const systemPrompt = [
      `You are a security assessment replanning assistant for the Argus penetration testing platform.`,
      `Given accumulated findings, suggest the next assessment phases.`,
      ``,
      `Available capabilities (use these exact strings):`,
      `- sqli_detection: SQL injection testing`,
      `- xss_detection: Cross-site scripting testing`,
      `- ssrf_check: SSRF testing`,
      `- command_injection: Command injection testing`,
      `- jwt_analysis: JWT security analysis`,
      `- post_exploitation: Post-exploitation actions`,
      `- cloud_metadata_probe: Cloud metadata service probing`,
      `- session_hijack_attempt: Session hijacking tests`,
      `- lateral_movement: Lateral movement`,
      `- phishing_chain: Phishing attack chain testing`,
      `- credential_replay: Credential replay attacks`,
      `- graphql_assessment: GraphQL testing`,
      `- api_docs_analysis: API documentation analysis`,
      `- browser_verification: Browser-based verification`,
      `- vulnerability_scanning: Additional vulnerability scanning`,
      `- template_scanning: CVE template scanning`,
      `- content_discovery: Further content discovery`,
      `- auth_detection: Authentication mechanism testing`,
      ``,
      `Rules:`,
      `1. Analyze the findings and identify attack chains`,
      `2. Suggest capabilities that would exploit or verify the findings`,
      `3. Set stop_assessment=true only if all important findings have been fully exploited`,
      `4. Prioritize capabilities that would have the most security impact`,
      `5. Consider what tools could provide more evidence or exploitation`,
    ].join("\n")

    const userPrompt = [
      `Current findings for ${target}:`,
      findingsSummary,
      ``,
      `Analyze these findings and suggest what capabilities should be run next.`,
      `Consider attack chains, deeper exploitation, and whether the assessment is complete.`,
    ].join("\n")

    try {
      const result = await Effect.runPromise(
        LLM.generateObject({
          model: this.model,
          system: systemPrompt,
          prompt: userPrompt,
          schema: ReplanSuggestionSchema as ToolSchema<unknown>,
        }).pipe(
          Effect.provide(LLMClient.layer),
          Effect.provide(RequestExecutor.defaultLayer),
        ),
      )

      const data = result.object as {
        next_capabilities: string[]
        reasoning: string
        stop_assessment: boolean
      }

      return {
        nextCapabilities: data.next_capabilities,
        reasoning: data.reasoning,
        stopAssessment: data.stop_assessment,
      }
    } catch (e) {
      console.warn(`[LLMPlanner] Replan suggestion failed: ${(e as Error).message}`)
      return null
    }
  }

  /**
   * Get the resolved model identifier string for diagnostic/logging purposes.
   * Returns "unavailable" if not yet initialized.
   */
  getModelId(): string {
    if (!this.model) return "unavailable"
    return `${this.model.provider}/${this.model.id}`
  }

  /**
   * Switch the planner model at runtime.
   *
   * Resets the initialized state and forces reinitialization with the
   * new model ID on the next LLM call. Also updates the environment
   * variable so subsequent env-var-based resolution uses the new value.
   *
   * @param modelId - The new model identifier (e.g. "gpt-4o", "claude-sonnet-4-20250514")
   */
  static switchModel(modelId: string): void {
    process.env[ENV_PLANNER_MODEL] = modelId
    const inst = LLMPlannerService.instance
    if (inst) {
      inst.model = null
      inst.initialized = false
      inst.available = false
      inst.initError = null
    }
  }

  /**
   * Get the current model ID from the env var, if one is set.
   * Returns the raw value or undefined.
   */
  static getCurrentModelId(): string | undefined {
    return process.env[ENV_PLANNER_MODEL]?.trim() || process.env[ENV_OPENCODE_MODEL]?.trim() || undefined
  }

  /**
   * Get available model options based on configured API keys.
   * Returns a sorted list of model ID strings the user can switch to.
   * Always includes the currently active model (if any).
   */
  static getAvailableModels(): string[] {
    const hasOpenAI = !!(process.env[ENV_OPENAI_KEY]?.trim())
    const hasAnthropic = !!(process.env[ENV_ANTHROPIC_KEY]?.trim())

    const models: string[] = []
    if (hasOpenAI) {
      models.push("gpt-4o-mini", "gpt-4o", "gpt-4.1")
    }
    if (hasAnthropic) {
      models.push("claude-sonnet-4-20250514", "claude-haiku-3-5-20241022")
    }

    // Always include the currently active model so there's an in-list option
    const current = LLMPlannerService.getCurrentModelId()
    if (current && !models.includes(current)) {
      models.push(current)
    }

    return models
  }

  /**
   * Get which env var controls the planner model (for help/doctor displays).
   */
  static getModelEnvVarDescription(): string {
    const current = process.env[ENV_PLANNER_MODEL]?.trim() || process.env[ENV_OPENCODE_MODEL]?.trim() || "not set"
    return `ARGUS_PLANNER_MODEL=${current} (default: gpt-4o-mini, supports OpenAI-compatible and Anthropic models)`
  }

  // ── Private Helpers ───────────────────────────────────────────────

  /**
   * Resolve an API key from environment variables.
   * Tries, in order: OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENCODE_API_KEY.
   */
  private resolveApiKey(): string | undefined {
    const openaiKey = process.env[ENV_OPENAI_KEY]?.trim()
    if (openaiKey) return openaiKey

    const anthropicKey = process.env[ENV_ANTHROPIC_KEY]?.trim()
    if (anthropicKey) return anthropicKey

    const opencodeKey = process.env[ENV_OPENCODE_KEY]?.trim()
    if (opencodeKey) return opencodeKey

    return undefined
  }

  /**
   * Create an LLM Model from the configured model string and API key.
   * Uses the model specified in ARGUS_PLANNER_MODEL (or OPENCODE_MODEL),
   * otherwise defaults to gpt-4o-mini.
   *
   * Detects Anthropic models vs OpenAI-compatible models by the model name.
   *
   * Configure via env var:
   *   ARGUS_PLANNER_MODEL=claude-sonnet-4-20250514   → Anthropic
   *   ARGUS_PLANNER_MODEL=gpt-4o-mini                 → OpenAI (default)
   *   ARGUS_PLANNER_MODEL=accounts/fireworks/models/... → OpenAI-compatible
   */
  private resolveModel(apiKey: string): Model | undefined {
    const modelStr =
      process.env[ENV_PLANNER_MODEL]?.trim() ??
      process.env[ENV_OPENCODE_MODEL]?.trim() ??
      ""

    // Anthropic models
    if (
      modelStr.toLowerCase().includes("claude") ||
      modelStr.toLowerCase().includes("anthropic")
    ) {
      const modelId = modelStr || "claude-sonnet-4-20250514"
      console.warn(`[LLMPlanner] Using Anthropic model: ${modelId}`)
      return anthropic.model(modelId) as unknown as Model
    }

    // Default: OpenAI-compatible (OpenAI, Azure, Fireworks, etc.)
    const modelId = modelStr || "gpt-4o-mini"
    console.warn(`[LLMPlanner] Using OpenAI-compatible model: ${modelId}`)
    return openai.model(modelId) as unknown as Model
  }
}

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
 *   resolvePlannerModel() (./model-registry) → reads OpenCode's provider
 *     registry (auth.json + models.dev) and lowers the selected model into an
 *     @opencode-ai/llm route via LLMNative.model()
 *     → Route has protocol, endpoint, auth, transport
 *     ↓
 *   LLM.generateObject() → forces structured output via synthetic tool call
 *     → Returns Effect<GenerateObjectResponse<T>>
 *     → Effect.runPromise wraps it for async/await usage
 *     ↓
 *   Returns structured capability suggestions for the planner
 *
 * Credentials and provider selection come from OpenCode's own configuration.
 * Ambient provider env vars (OPENAI_API_KEY, OPENAI_BASE_URL, ...) are NOT
 * used — see ./model-registry for why and how to opt back in.
 */

import { Effect, Schema } from "effect"
import { LLM, type Model, type ToolSchema } from "@opencode-ai/llm"
import { LLMClient, RequestExecutor } from "@opencode-ai/llm/route"
import {
  PLANNER_MODEL_ENV_VAR,
  invalidatePlannerModelCache,
  listPlannerModels,
  resolvePlannerModel,
} from "./model-registry"
import {
  acquireServer,
  prompt as serverPrompt,
  parseJsonObject,
  OpencodeServerError,
  LLM_TRANSPORT_ENV_VAR,
  selectPlannerTransport,
  type OpencodeServerHandle,
  type PlannerTransport,
  type ServerModelRef,
} from "./opencode-server"

// The transport policy lives with the transport (opencode-server.ts) because
// the worker handoff must make the same decision; re-exported here so the
// planner keeps one entry point for it.
export { LLM_TRANSPORT_ENV_VAR, selectPlannerTransport, type PlannerTransport }

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

// ── Model selection env keys ─────────────────────────────────────────
// Only model *selection* is env-driven; provider credentials always come
// from OpenCode's provider registry.

const ENV_PLANNER_MODEL = PLANNER_MODEL_ENV_VAR
const ENV_OPENCODE_MODEL = "OPENCODE_MODEL"

/**
 * JSON Schema for the phase-suggestion response — the wire form of
 * `PhaseSuggestionResponseSchema` below, which cannot be sent to a provider as
 * an Effect Schema. Keep the two in step.
 */
const PHASE_SUGGESTION_JSON_SCHEMA = {
  type: "object",
  properties: {
    target_analysis: { type: "string" },
    suggested_phases: {
      type: "array",
      items: {
        type: "object",
        properties: {
          capabilities: { type: "array", items: { type: "string" } },
          reasoning: { type: "string" },
        },
        required: ["capabilities", "reasoning"],
      },
    },
  },
  required: ["target_analysis", "suggested_phases"],
} as const

/** JSON Schema for `ReplanSuggestionSchema`. Keep in step with it. */
const REPLAN_JSON_SCHEMA = {
  type: "object",
  properties: {
    next_capabilities: { type: "array", items: { type: "string" } },
    reasoning: { type: "string" },
    stop_assessment: { type: "boolean" },
  },
  required: ["next_capabilities", "reasoning", "stop_assessment"],
} as const

// Re-exported so callers have one import site for planner helpers; the
// implementation lives with the transport that receives the text.
export { parseJsonObject } from "./opencode-server"

// ── LLM Planner Service ──────────────────────────────────────────────

export class LLMPlannerService {
  private static instance: LLMPlannerService | null = null
  private model: Model | null = null
  private modelRef: { providerID: string; modelID: string } | null = null
  private resolutionSource: string | null = null
  private ignoredAmbientEnv: string[] = []
  private initialized = false
  private initError: string | null = null
  private available = false

  /** How this planner reaches the model: a local OpenCode server, or direct. */
  private transport: PlannerTransport = "direct"
  /** The local OpenCode server, when the transport needs one. */
  private server: OpencodeServerHandle | null = null
  /** Why the server transport was unavailable, when it was wanted. */
  private transportError: string | null = null

  /** Directory the OpenCode server is asked to work in. */
  private readonly directory: string = process.cwd()

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
   * Initialize the LLM client from OpenCode's provider registry.
   *
   * Returns true if the LLM is available and ready. Ambient provider env vars
   * are deliberately ignored (see ./model-registry).
   */
  private async ensureInitialized(): Promise<boolean> {
    if (this.initialized) return this.available

    try {
      const resolution = await resolvePlannerModel()
      this.ignoredAmbientEnv = resolution.ignoredAmbientEnv
      if (!resolution.ok) {
        this.initError = resolution.reason
        this.initialized = true
        this.available = false
        return false
      }

      this.model = resolution.model
      this.modelRef = { providerID: resolution.providerID, modelID: resolution.modelID }
      this.resolutionSource = resolution.source

      const wanted = selectPlannerTransport(resolution.providerID)
      const explicit = process.env[LLM_TRANSPORT_ENV_VAR]?.trim().toLowerCase() === "server"
      if (wanted === "server") {
        try {
          this.server = await acquireServer({ directory: this.directory })
          this.transport = "server"
        } catch (e) {
          // An explicit request for the server transport cannot be silently
          // downgraded: OpenCode's gateways reject direct calls from this build
          // (blocker B9), so "direct" here would fail later and less clearly.
          this.transportError = e instanceof OpencodeServerError ? e.message : String(e)
          if (explicit) {
            this.initError = `Planner LLM transport 'server' was requested but no OpenCode server is available: ${this.transportError}`
            this.initialized = true
            this.available = false
            return false
          }
          console.warn(`[LLMPlanner] Falling back to a direct call: ${this.transportError}`)
          this.transport = "direct"
        }
      }

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

  /**
   * Diagnostics: which registry entry the planner resolved to, and which
   * ambient provider env vars were ignored while doing so.
   */
  getResolutionInfo(): {
    source: string | null
    ignoredAmbientEnv: string[]
    transport: PlannerTransport
    serverOrigin: string | null
    transportError: string | null
  } {
    return {
      source: this.resolutionSource,
      ignoredAmbientEnv: [...this.ignoredAmbientEnv],
      transport: this.transport,
      serverOrigin: this.server?.origin ?? null,
      transportError: this.transportError,
    }
  }

  /**
   * One planner call through the local OpenCode server.
   *
   * The model call is made by OpenCode itself, which is the only way its own
   * gateways will serve it from this build (blocker B9).
   */
  private async callThroughServer(
    systemPrompt: string,
    userPrompt: string,
    schema: Record<string, unknown>,
  ): Promise<unknown> {
    const server = this.server
    const ref = this.modelRef
    if (!server || !ref) throw new Error("OpenCode server transport is not initialized")

    const result = await serverPrompt({
      server,
      directory: this.directory,
      model: ref as ServerModelRef,
      system: systemPrompt,
      prompt: userPrompt,
      schema,
    })
    if (process.env.ARGUS_DEBUG_PLANNER) {
      console.log(
        `[LLMPlanner] raw reply from ${result.providerID}/${result.modelID}: ` +
          `structured=${result.structured === undefined ? "none" : JSON.stringify(result.structured).slice(0, 600)} ` +
          `text=${JSON.stringify(result.text.slice(0, 600))} ` +
          `tokens=${JSON.stringify(result.tokens)}`,
      )
    }

    // Structured output when the model produced one; otherwise parse its text,
    // so a smaller model that ignored the schema can still be understood.
    if (result.structured !== undefined) return result.structured
    const parsed = parseJsonObject(result.text)
    if (parsed === undefined) {
      // Say so loudly: a silently empty plan is indistinguishable from a planner
      // that never ran, which is exactly the confusion this transport removes.
      console.warn(
        `[LLMPlanner] ${result.providerID}/${result.modelID} answered without usable JSON ` +
          `(${result.text.length} chars): ${result.text.slice(0, 300)}`,
      )
    }
    return parsed
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
      const raw = this.server
        ? await this.callThroughServer(systemPrompt, userPrompt, PHASE_SUGGESTION_JSON_SCHEMA)
        : (
            await Effect.runPromise(
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
          ).object

      const data = raw as {
        target_analysis?: string
        suggested_phases?: Array<{ capabilities?: string[]; reasoning?: string }>
      }
      if (!data || typeof data !== "object") return { targetAnalysis: "", suggestedPhases: [] }

      return {
        targetAnalysis: data.target_analysis ?? "",
        suggestedPhases: (data.suggested_phases ?? [])
          .filter((p) => p && typeof p === "object")
          .map((p) => ({
            capabilities: p.capabilities ?? [],
            reasoning: p.reasoning ?? "",
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
      const raw = this.server
        ? await this.callThroughServer(systemPrompt, userPrompt, REPLAN_JSON_SCHEMA)
        : (
            await Effect.runPromise(
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
          ).object

      const data = raw as {
        next_capabilities?: string[]
        reasoning?: string
        stop_assessment?: boolean
      }
      if (!data || typeof data !== "object") return null

      return {
        nextCapabilities: data.next_capabilities ?? [],
        reasoning: data.reasoning ?? "",
        stopAssessment: data.stop_assessment ?? false,
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
    if (this.modelRef) return `${this.modelRef.providerID}/${this.modelRef.modelID}`
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
    // The resolution (and therefore the worker handoff) is cached per model.
    invalidatePlannerModelCache()
    const inst = LLMPlannerService.instance
    if (inst) {
      inst.model = null
      inst.modelRef = null
      inst.resolutionSource = null
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
   * Get available model options from OpenCode's provider registry.
   * Returns `provider/model` strings the user can switch to.
   * Always includes the currently active model (if any).
   */
  static async getAvailableModels(): Promise<string[]> {
    const models = await listPlannerModels()

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
    const current = LLMPlannerService.getCurrentModelId() ?? "not set"
    return `ARGUS_PLANNER_MODEL=${current} (default: OpenCode's configured default model)`
  }
}

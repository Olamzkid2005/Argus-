/**
 * LLMPlannerService unit tests.
 *
 * Tests the LLM planner service in isolation by mocking @opencode-ai/llm
 * calls at the module level. This avoids needing real API keys or network
 * access while still exercising the full LLMPlannerService code path.
 *
 * Mock strategy:
 *   - Module-level flags (shouldLLMThrow, currentMockResponse) control
 *     the mocked LLM.generateObject() behavior per-test without needing
 *     to re-mock the module, avoiding mock leakage across tests.
 *   - Provider modules are stubbed to return minimal model objects.
 *   - Effect.pipe() and Effect.provide() work naturally on the real
 *     Effect.succeed() value, so no special handling is needed.
 *   - Environment variables control the availability check path.
 */

import { describe, expect, test, mock, beforeEach, afterEach } from "bun:test"
import { Effect, Layer } from "effect"

// These tests drive the service against a mocked `@opencode-ai/llm`, so they must
// stay on the direct transport. The default for an `opencode*` provider is the
// server transport (see selectPlannerTransport), which spawns a real
// `opencode serve` — a real server is not available in a unit test, and the
// transport itself is covered by opencode-server.test.ts.
process.env.ARGUS_LLM_TRANSPORT = "direct"

// ── Mock Control Flags ───────────────────────────────────────────────
// These module-level flags control the mocked generateObject behavior
// from individual tests WITHOUT calling mock.module() again (which is
// process-global and would leak). Flags are reset in beforeEach/afterEach.

/** When true, generateObject returns a failed Effect. */
let shouldLLMThrow = false

/** The canned response object the mock returns. */
let currentMockResponse: object = {}

/** Default phase suggestion response — set in beforeEach. */
let defaultPhaseResponse: object = {}

/** Default replan suggestion response — set in beforeEach. */
let defaultReplanResponse: object = {}

// ── Mock Layers for Effect.provide ───────────────────────────────────
// These are valid (empty) Layers that Effect.provide accepts without error.
// The mocked LLM.generateObject returns Effect.succeed() which requires
// no services, so the provided layers are silently ignored.
//
// Note: GenericTag API differs between effect versions (Context.GenericTag
// in some vs. direct GenericTag in others). We use a plain tag object to
// avoid the mismatch — the mock layers are never actually invoked since
// the mocked LLM.generateObject returns Effect.succeed() directly.
const noopClientLayer = Layer.succeed(
  "@opencode/LLMClient" as any,
  {} as any,
)

const noopExecutorLayer = Layer.succeed(
  "@opencode/RequestExecutor" as any,
  {} as any,
)// ── Module Mocks (set up once, controlled via flags) ─────────────────
// These must be created BEFORE the service is imported.

mock.module("@opencode-ai/llm", () => ({
  LLM: {
    generateObject: () => {
      if (shouldLLMThrow) {
        return Effect.fail(new Error("LLM temporarily unavailable"))
      }
      return Effect.succeed({ object: currentMockResponse })
    },
  },
  ToolFailure: class extends Error {},
  tool: () => ({}),
  Tool: class {},
  toDefinitions: () => [],
  Provider: {
    make: (def: any) => def,
  },
}))

mock.module("@opencode-ai/llm/providers/openai", () => ({
  openai: {
    model: (id: string, _options: any) => ({
      id,
      provider: "openai",
      route: { id: "openai-chat", provider: "openai" },
      name: id,
    }),
  },
}))

mock.module("@opencode-ai/llm/providers/anthropic", () => ({
  anthropic: {
    model: (id: string, _options: any) => ({
      id,
      provider: "anthropic",
      route: { id: "anthropic-messages", provider: "anthropic" },
      name: id,
    }),
  },
}))

mock.module("@opencode-ai/llm/route", () => ({
  LLMClient: {
    layer: noopClientLayer,
    Service: class {},
  },
  RequestExecutor: {
    defaultLayer: noopExecutorLayer,
    Service: class {},
    default: {},
  },
}))

mock.module("@opencode-ai/llm/schema", () => ({
  Model: class {},
  ModelID: { make: (id: string) => id },
  ProviderID: { make: (id: string) => id },
}))

// ── Registry mock ────────────────────────────────────────────────────
// The planner resolves provider/model/credentials from OpenCode's provider
// registry (argus/planner/model-registry). Mocking it here keeps these tests
// offline while still exercising availability, caching and error paths.

let registryAvailable = true
let registrySource: "explicit" | "default" | "first-configured" = "default"
let resolvedProviderID = "opencode"
let resolvedModelID = "mimo-v2.5-free"
let registryReason =
  "No providers are configured in OpenCode. Run `opencode auth login` (or configure a provider " +
  "in the OpenCode TUI) to make a model available to Argus."
let ignoredAmbientEnv: string[] = []

mock.module("../../../../src/argus/planner/model-registry", () => ({
  PLANNER_MODEL_ENV_VAR: "ARGUS_PLANNER_MODEL",
  ALLOW_AMBIENT_ENV_VAR: "ARGUS_ALLOW_AMBIENT_LLM_ENV",
  AMBIENT_LLM_ENV_VARS: [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENCODE_API_KEY",
  ],
  resolvePlannerModel: async () =>
    registryAvailable
      ? {
          ok: true,
          providerID: resolvedProviderID,
          modelID: resolvedModelID,
          model: { id: resolvedModelID, provider: resolvedProviderID },
          source: registrySource,
          ignoredAmbientEnv,
        }
      : { ok: false, reason: registryReason, ignoredAmbientEnv },
  listPlannerModels: async () => [`${resolvedProviderID}/${resolvedModelID}`],
  ignoredAmbientLlmEnvVars: () => ignoredAmbientEnv,
  ambientEnvAllowed: () => false,
}))

// ── Import the service AFTER mocks are set up ─────────────────────────
import { LLMPlannerService } from "../../../../src/argus/planner/llm-service"

// ── Tests ─────────────────────────────────────────────────────────────

describe("LLMPlannerService", () => {
  beforeEach(() => {
    // Reset the private singleton for clean test isolation
    ;(LLMPlannerService as any).instance = null

    // Registry resolves a model by default
    registryAvailable = true
    registrySource = "default"
    resolvedProviderID = "opencode"
    resolvedModelID = "mimo-v2.5-free"
    ignoredAmbientEnv = []

    // Reset mock control flags
    shouldLLMThrow = false

    // Set default phase response
    defaultPhaseResponse = {
      target_analysis:
        "Web application with login form, API endpoints, and JavaScript-heavy frontend. Standard web assessment phases recommended.",
      suggested_phases: [
        {
          capabilities: ["web_recon", "technology_detection"],
          reasoning:
            "Identify tech stack, subdomains, and attack surface.",
        },
        {
          capabilities: ["vulnerability_scanning", "template_scanning"],
          reasoning:
            "Automated vulnerability detection using scanners and CVE templates.",
        },
        {
          capabilities: ["browser_verification"],
          reasoning:
            "Browser-based verification for UX-borne vulnerabilities.",
        },
        {
          capabilities: ["report_generation"],
          reasoning: "Generate comprehensive assessment report.",
        },
      ],
    }

    // Set default replan response
    defaultReplanResponse = {
      next_capabilities: ["post_exploitation", "sqli_detection"],
      reasoning:
        "SQL injection confirmed in login form. Proceed with post-exploitation to extract data. Additional SQLi testing recommended for deeper coverage.",
      stop_assessment: false,
    }

    // Default the mock response to phase suggestions
    currentMockResponse = defaultPhaseResponse
  })

  afterEach(() => {
    // Clean up env vars to avoid cross-test pollution
    delete process.env.OPENAI_API_KEY
    delete process.env.ANTHROPIC_API_KEY
    delete process.env.OPENCODE_API_KEY
    delete process.env.ARGUS_PLANNER_MODEL
    delete process.env.OPENCODE_MODEL
  })

  // ── lazy singleton ───────────────────────────────────────────────

  describe("lazy singleton", () => {
    test("returns the same instance on multiple calls", () => {
      const svc1 = LLMPlannerService.lazy()
      const svc2 = LLMPlannerService.lazy()
      expect(svc1).toBe(svc2)
    })

    test("creates a new instance after reset", () => {
      const svc1 = LLMPlannerService.lazy()
      ;(LLMPlannerService as any).instance = null
      const svc2 = LLMPlannerService.lazy()
      expect(svc1).not.toBe(svc2)
    })
  })

  // ── isAvailable ──────────────────────────────────────────────────

  describe("isAvailable()", () => {
    test("returns true when the OpenCode provider registry resolves a model", async () => {
      const svc = LLMPlannerService.lazy()
      const available = await svc.isAvailable()
      expect(available).toBe(true)
    })

    // ── Regression: the ambient-credential leak ──────────────────────
    // Argus used to pick its provider from whatever OPENAI_API_KEY /
    // ANTHROPIC_API_KEY / OPENCODE_API_KEY the surrounding shell exported.
    test("ignores ambient OPENAI_API_KEY", async () => {
      process.env.OPENAI_API_KEY = "sk-harness-key"
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      expect(await svc.isAvailable()).toBe(false)
      expect(svc.getInitError()).toContain("opencode auth login")
    })

    test("ignores ambient ANTHROPIC_API_KEY", async () => {
      process.env.ANTHROPIC_API_KEY = "sk-ant-harness-key"
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      expect(await svc.isAvailable()).toBe(false)
    })

    test("ignores ambient OPENCODE_API_KEY", async () => {
      process.env.OPENCODE_API_KEY = "oc-harness-key"
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      expect(await svc.isAvailable()).toBe(false)
    })

    test("reports which ambient env vars were ignored", async () => {
      process.env.OPENAI_API_KEY = "sk-harness-key"
      ignoredAmbientEnv = ["OPENAI_API_KEY", "OPENAI_BASE_URL"]
      const svc = LLMPlannerService.lazy()
      await svc.isAvailable()
      expect(svc.getResolutionInfo().ignoredAmbientEnv).toEqual(["OPENAI_API_KEY", "OPENAI_BASE_URL"])
    })

    test("reports the resolution source", async () => {
      registrySource = "explicit"
      const svc = LLMPlannerService.lazy()
      await svc.isAvailable()
      expect(svc.getResolutionInfo().source).toBe("explicit")
      expect(svc.getModelId()).toBe("opencode/mimo-v2.5-free")
    })

    test("returns false when no provider is configured in OpenCode", async () => {
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      expect(await svc.isAvailable()).toBe(false)
    })

    test("returns cached result on second call", async () => {
      const svc = LLMPlannerService.lazy()
      const first = await svc.isAvailable()
      expect(first).toBe(true)

      // Registry becomes unavailable — the cached result should still be true
      registryAvailable = false
      const second = await svc.isAvailable()
      expect(second).toBe(true) // cached
    })
  })

  // ── getModelId ──────────────────────────────────────────────────

  describe("getModelId()", () => {
    test("returns provider/model string after initialization", async () => {
      const svc = LLMPlannerService.lazy()
      await svc.isAvailable()
      const modelId = svc.getModelId()
      expect(modelId).not.toBe("unavailable")
      expect(modelId).toContain("/")
    })

    test("returns 'unavailable' before initialization", () => {
      const svc = LLMPlannerService.lazy()
      expect(svc.getModelId()).toBe("unavailable")
    })
  })

  // ── getModelEnvVarDescription ────────────────────────────────────

  describe("getModelEnvVarDescription()", () => {
    test("returns description with default when ARGUS_PLANNER_MODEL is not set", () => {
      delete process.env.ARGUS_PLANNER_MODEL
      const desc = LLMPlannerService.getModelEnvVarDescription()
      expect(desc).toContain("ARGUS_PLANNER_MODEL")
      expect(desc).toContain("not set")
      expect(desc).toContain("OpenCode's configured default model")
    })

    test("returns description with configured model when set", () => {
      process.env.ARGUS_PLANNER_MODEL = "deepseek/deepseek-chat"
      const desc = LLMPlannerService.getModelEnvVarDescription()
      expect(desc).toContain("deepseek/deepseek-chat")
    })

    test("falls back to OPENCODE_MODEL when ARGUS_PLANNER_MODEL is not set", () => {
      delete process.env.ARGUS_PLANNER_MODEL
      process.env.OPENCODE_MODEL = "gpt-5"
      const desc = LLMPlannerService.getModelEnvVarDescription()
      expect(desc).toContain("gpt-5")
    })

    test("ARGUS_PLANNER_MODEL takes precedence over OPENCODE_MODEL", () => {
      process.env.ARGUS_PLANNER_MODEL = "claude-opus-4-20250514"
      process.env.OPENCODE_MODEL = "gpt-5"
      const desc = LLMPlannerService.getModelEnvVarDescription()
      expect(desc).toContain("claude-opus-4-20250514")
      expect(desc).not.toContain("gpt-5")
    })
  })

  // ── getInitError ─────────────────────────────────────────────────

  describe("getInitError()", () => {
    test("returns null when initialization succeeded", async () => {
      const svc = LLMPlannerService.lazy()
      await svc.isAvailable()
      expect(svc.getInitError()).toBeNull()
    })

    test("explains the provider registry when no provider is configured", async () => {
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      await svc.isAvailable()
      const error = svc.getInitError()
      expect(error).not.toBeNull()
      expect(error).toContain("No providers are configured in OpenCode")
      expect(error).toContain("opencode auth login")
    })
  })

  // ── suggestPhases ────────────────────────────────────────────────

  describe("suggestPhases()", () => {
    test("returns phase suggestions for a web target with tech stack", async () => {
      currentMockResponse = defaultPhaseResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases(
        "https://example.com",
        "web_app",
        ["react", "node"],
      )

      expect(result.targetAnalysis).toBeTruthy()
      expect(result.targetAnalysis.length).toBeGreaterThan(10)
      expect(result.suggestedPhases.length).toBeGreaterThan(0)

      // Each suggestion should have capabilities and reasoning
      for (const phase of result.suggestedPhases) {
        expect(phase.capabilities).toBeDefined()
        expect(phase.capabilities.length).toBeGreaterThan(0)
        expect(phase.reasoning).toBeTruthy()
      }
    })

    test("suggested phases include valid capability strings", async () => {
      currentMockResponse = defaultPhaseResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases("https://example.com", "web_app")

      const allCaps = result.suggestedPhases.flatMap((p) => p.capabilities)
      expect(allCaps.length).toBeGreaterThan(0)

      // All capabilities should be non-empty strings
      for (const cap of allCaps) {
        expect(typeof cap).toBe("string")
        expect(cap.length).toBeGreaterThan(0)
      }
    })

    test("returns empty result when LLM is unavailable (no configured provider)", async () => {
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases("https://example.com", "web_app")

      expect(result.targetAnalysis).toBe("")
      expect(result.suggestedPhases).toHaveLength(0)
    })

    test("handles undefined techStack gracefully", async () => {
      currentMockResponse = defaultPhaseResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases(
        "https://example.com",
        "web_app",
        undefined,
      )

      expect(result.targetAnalysis).toBeTruthy()
      expect(result.suggestedPhases.length).toBeGreaterThan(0)
    })

    test("works for API target type", async () => {
      currentMockResponse = defaultPhaseResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases(
        "https://api.example.com/v1",
        "api",
      )

      expect(result.suggestedPhases.length).toBeGreaterThan(0)
    })

    test("handles LLM failure gracefully (non-blocking)", async () => {
      shouldLLMThrow = true
      currentMockResponse = defaultPhaseResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases("https://example.com", "web_app")

      // Should return empty result without throwing
      expect(result.targetAnalysis).toBe("")
      expect(result.suggestedPhases).toHaveLength(0)
    })
  })

  // ── suggestReplan ────────────────────────────────────────────────

  describe("suggestReplan()", () => {
    test("returns replan suggestions with findings", async () => {
      currentMockResponse = defaultReplanResponse
      const svc = LLMPlannerService.lazy()
      const findings = [
        {
          title: "SQL Injection in login form",
          severity: 4,
          subtype: "sqli",
          confidence: 3,
        },
      ]

      const result = await svc.suggestReplan("https://example.com", findings)

      expect(result).not.toBeNull()
      expect(result!.nextCapabilities).toBeDefined()
      expect(result!.nextCapabilities.length).toBeGreaterThan(0)
      expect(result!.reasoning).toBeTruthy()
      expect(typeof result!.stopAssessment).toBe("boolean")
    })

    test("stopAssessment is a boolean in the response", async () => {
      currentMockResponse = defaultReplanResponse
      const svc = LLMPlannerService.lazy()
      const findings = [
        {
          title: "XSS vulnerability",
          severity: 3,
          subtype: "xss",
          confidence: 2,
        },
      ]

      const result = await svc.suggestReplan("https://example.com", findings)

      expect(result).not.toBeNull()
      expect(typeof result!.stopAssessment).toBe("boolean")
    })

    test("returns null for empty findings", async () => {
      currentMockResponse = defaultReplanResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestReplan("https://example.com", [])

      expect(result).toBeNull()
    })

    test("returns null when LLM is unavailable", async () => {
      registryAvailable = false
      const svc = LLMPlannerService.lazy()
      const findings = [
        {
          title: "XSS vulnerability",
          severity: 3,
          subtype: "xss",
          confidence: 3,
        },
      ]

      const result = await svc.suggestReplan("https://example.com", findings)
      expect(result).toBeNull()
    })

    test("handles findings with mixed severity levels", async () => {
      currentMockResponse = defaultReplanResponse
      const svc = LLMPlannerService.lazy()
      const findings = [
        {
          title: "Critical SQL Injection",
          severity: 4,
          subtype: "sqli",
          confidence: 4,
        },
        {
          title: "Medium XSS in search",
          severity: 2,
          subtype: "xss",
          confidence: 2,
        },
        {
          title: "Open port 443",
          severity: 0,
          subtype: "port_scanning",
          confidence: 3,
        },
      ]

      const result = await svc.suggestReplan("https://example.com", findings)
      expect(result).not.toBeNull()
      expect(result!.nextCapabilities.length).toBeGreaterThan(0)
    })

    test("handles LLM failure gracefully (non-blocking)", async () => {
      shouldLLMThrow = true
      currentMockResponse = defaultReplanResponse
      const svc = LLMPlannerService.lazy()
      const findings = [
        {
          title: "SQL Injection found",
          severity: 4,
          subtype: "sqli",
          confidence: 3,
        },
      ]

      const result = await svc.suggestReplan("https://example.com", findings)
      expect(result).toBeNull()
    })
  })

  // ── Integration context shapes ───────────────────────────────────

  describe("planner integration shapes", () => {
    test("replan with critical findings returns capabilities", async () => {
      currentMockResponse = defaultReplanResponse
      const svc = LLMPlannerService.lazy()
      const findings = [
        {
          title: "RCE in file upload",
          severity: 4,
          subtype: "command_injection",
          confidence: 4,
        },
        {
          title: "SSRF in proxy endpoint",
          severity: 3,
          subtype: "ssrf",
          confidence: 3,
        },
      ]

      const result = await svc.suggestReplan("https://example.com", findings)
      expect(result).not.toBeNull()
      expect(result!.nextCapabilities.length).toBeGreaterThan(0)
    })

    test("phase suggestions with empty techStack array", async () => {
      currentMockResponse = defaultPhaseResponse
      const svc = LLMPlannerService.lazy()
      const result = await svc.suggestPhases(
        "https://example.com",
        "web_app",
        [],
      )
      expect(result.suggestedPhases.length).toBeGreaterThan(0)
    })
  })
})

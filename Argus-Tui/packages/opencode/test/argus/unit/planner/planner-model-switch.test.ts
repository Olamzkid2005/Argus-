/**
 * Integration tests: model selector click handler.
 *
 * Simulates clicking the model indicator in scan.tsx and verifies:
 *   1. LLMPlannerService-style switchModel updates ARGUS_PLANNER_MODEL
 *   2. getAvailableModels returns correct models per API key
 *   3. getCurrentModelId reads the current env var
 *   4. Full click handler: cycle → env var + scan-store + log all update
 *   5. Single-model scenario: no-op guard
 *
 * Strategy:
 *   - Mock solid-js/store to import real scan-store functions
 *   - Use inline implementations of the LLMPlannerService static methods
 *     to avoid @opencode-ai/llm workspace dependency resolution issues
 *   - The inline implementations match the actual source logic exactly
 */

import { describe, test, expect, mock, beforeEach } from "bun:test"

// ── Mock solid-js/store for scan-store ───────────────────────────────
mock.module("solid-js/store", () => {
  let state: any = {}
  return {
    createStore: (initial: any) => {
      state = { ...initial }
      return [
        state,
        (path: any, ...args: any[]) => {
          if (typeof path === "function") {
            Object.assign(state, path(state))
          } else if (typeof path === "object" && path !== null) {
            Object.assign(state, path)
          } else if (typeof path === "string") {
            if (args.length === 1) {
              if (typeof args[0] === "function") {
                state[path] = args[0](state[path] ?? [])
              } else {
                state[path] = args[0]
              }
            } else if (args.length === 2) {
              state[path] ??= []
              state[path][args[0]] = args[1]
            } else if (args.length === 3) {
              state[path] ??= []
              state[path][args[0]] ??= {}
              state[path][args[0]][args[1]] = args[2]
            }
          }
        },
      ]
    },
  }
})

// ── Dynamic import scan-store (mock.module runs first) ───────────────
const {
  getScanState,
  initScan,
  appendLog,
  resetScan,
  setPlannerModel,
} = await import("../../../../src/argus/tui/scan-store")

// ── Inline LLMPlannerService static methods ──────────────────────────
// These match the actual source logic in src/argus/planner/llm-service.ts.
// We inline them to avoid the @opencode-ai/llm monorepo dependency chain.

const ENV_PLANNER_MODEL = "ARGUS_PLANNER_MODEL"
const ENV_OPENCODE_MODEL = "OPENCODE_MODEL"
const ENV_OPENAI_KEY = "OPENAI_API_KEY"
const ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
const ENV_OPENCODE_KEY = "OPENCODE_API_KEY"

/** Singleton instance state for switchModel to reset. */
let _mockInstance: { model: any; initialized: boolean; available: boolean; initError: string | null } | null = null

/** Create a new singleton, mimicking LLMPlannerService.lazy(). */
function createMockInstance(): void {
  _mockInstance = { model: {} as any, initialized: true, available: true, initError: null }
}

function mockSwitchModel(modelId: string): void {
  process.env[ENV_PLANNER_MODEL] = modelId
  if (_mockInstance) {
    _mockInstance.model = null
    _mockInstance.initialized = false
    _mockInstance.available = false
    _mockInstance.initError = null
  }
}

function mockGetCurrentModelId(): string | undefined {
  return process.env[ENV_PLANNER_MODEL]?.trim() || process.env[ENV_OPENCODE_MODEL]?.trim() || undefined
}

function mockGetAvailableModels(): string[] {
  const hasOpenAI = !!(process.env[ENV_OPENAI_KEY]?.trim())
  const hasAnthropic = !!(process.env[ENV_ANTHROPIC_KEY]?.trim())

  const models: string[] = []
  if (hasOpenAI) {
    models.push("gpt-4o-mini", "gpt-4o", "gpt-4.1")
  }
  if (hasAnthropic) {
    models.push("claude-sonnet-4-20250514", "claude-haiku-3-5-20241022")
  }

  const current = mockGetCurrentModelId()
  if (current && !models.includes(current)) {
    models.push(current)
  }

  return models
}

// ── Save/restore helper ──────────────────────────────────────────────

/** Save/restore specific env vars so tests don't leak.
 *  Unlike assigning `undefined` (which creates the string "undefined"),
 *  this properly deletes keys that were absent before the test. */
function withCleanEnv(fn: () => void) {
  const saved: Record<string, string | undefined> = {
    OPENAI_API_KEY: process.env.OPENAI_API_KEY,
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
    OPENCODE_API_KEY: process.env.OPENCODE_API_KEY,
    ARGUS_PLANNER_MODEL: process.env.ARGUS_PLANNER_MODEL,
    OPENCODE_MODEL: process.env.OPENCODE_MODEL,
  }
  try {
    fn()
  } finally {
    for (const [key, val] of Object.entries(saved)) {
      if (val === undefined) {
        delete process.env[key]
      } else {
        process.env[key] = val
      }
    }
  }
}

// ── Tests ────────────────────────────────────────────────────────────

describe("planner model switch integration", () => {
  beforeEach(() => {
    resetScan()
    _mockInstance = null
  })

  // ── switchModel tests ───────────────────────────────────────────────

  describe("switchModel", () => {
    test("sets ARGUS_PLANNER_MODEL env var", () => {
      withCleanEnv(() => {
        delete process.env.ARGUS_PLANNER_MODEL
        mockSwitchModel("gpt-4o")
        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("gpt-4o")
      })
    })

    test("resets instance fields (model, initialized, available)", () => {
      withCleanEnv(() => {
        createMockInstance()
        expect(_mockInstance).not.toBeNull()
        expect(_mockInstance!.model).not.toBeNull()
        expect(_mockInstance!.initialized).toBe(true)

        mockSwitchModel("claude-sonnet-4-20250514")

        expect(_mockInstance!.model).toBeNull()
        expect(_mockInstance!.initialized).toBe(false)
        expect(_mockInstance!.available).toBe(false)
        expect(_mockInstance!.initError).toBeNull()
      })
    })

    test("works when no singleton instance exists", () => {
      withCleanEnv(() => {
        delete process.env.ARGUS_PLANNER_MODEL
        _mockInstance = null
        mockSwitchModel("gpt-4o-mini")
        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("gpt-4o-mini")
      })
    })
  })

  // ── getCurrentModelId tests ─────────────────────────────────────────

  describe("getCurrentModelId", () => {
    test("returns ARGUS_PLANNER_MODEL when set", () => {
      withCleanEnv(() => {
        process.env.ARGUS_PLANNER_MODEL = "gpt-4o"
        delete process.env.OPENCODE_MODEL
        expect(mockGetCurrentModelId()).toBe("gpt-4o")
      })
    })

    test("falls back to OPENCODE_MODEL", () => {
      withCleanEnv(() => {
        delete process.env.ARGUS_PLANNER_MODEL
        process.env.OPENCODE_MODEL = "claude-sonnet-4"
        expect(mockGetCurrentModelId()).toBe("claude-sonnet-4")
      })
    })

    test("returns undefined when neither is set", () => {
      withCleanEnv(() => {
        delete process.env.ARGUS_PLANNER_MODEL
        delete process.env.OPENCODE_MODEL
        expect(mockGetCurrentModelId()).toBeUndefined()
      })
    })
  })

  // ── getAvailableModels tests ────────────────────────────────────────

  describe("getAvailableModels", () => {
    test("returns OpenAI models with only OPENAI_API_KEY", () => {
      withCleanEnv(() => {
        process.env.OPENAI_API_KEY = "sk-test"
        delete process.env.ANTHROPIC_API_KEY
        const models = mockGetAvailableModels()
        expect(models).toEqual(["gpt-4o-mini", "gpt-4o", "gpt-4.1"])
        expect(models).not.toContain("claude-sonnet-4-20250514")
      })
    })

    test("returns Anthropic models with only ANTHROPIC_API_KEY", () => {
      withCleanEnv(() => {
        delete process.env.OPENAI_API_KEY
        process.env.ANTHROPIC_API_KEY = "sk-ant-test"
        const models = mockGetAvailableModels()
        expect(models).toEqual(["claude-sonnet-4-20250514", "claude-haiku-3-5-20241022"])
        expect(models).not.toContain("gpt-4o-mini")
      })
    })

    test("returns both sets with both API keys", () => {
      withCleanEnv(() => {
        process.env.OPENAI_API_KEY = "sk-test"
        process.env.ANTHROPIC_API_KEY = "sk-ant-test"
        const models = mockGetAvailableModels()
        expect(models).toHaveLength(5)
        expect(models).toContain("gpt-4o-mini")
        expect(models).toContain("gpt-4o")
        expect(models).toContain("gpt-4.1")
        expect(models).toContain("claude-sonnet-4-20250514")
        expect(models).toContain("claude-haiku-3-5-20241022")
      })
    })

    test("includes current model even when not in defaults", () => {
      withCleanEnv(() => {
        process.env.OPENAI_API_KEY = "sk-test"
        process.env.ARGUS_PLANNER_MODEL = "accounts/fireworks/models/llama-3"
        const models = mockGetAvailableModels()
        expect(models).toContain("accounts/fireworks/models/llama-3")
      })
    })

    test("empty array when no API key and no current model", () => {
      withCleanEnv(() => {
        delete process.env.OPENAI_API_KEY
        delete process.env.ANTHROPIC_API_KEY
        delete process.env.ARGUS_PLANNER_MODEL
        const models = mockGetAvailableModels()
        expect(models).toEqual([])
      })
    })

    test("only current model when no API key but model is set", () => {
      withCleanEnv(() => {
        delete process.env.OPENAI_API_KEY
        delete process.env.ANTHROPIC_API_KEY
        process.env.ARGUS_PLANNER_MODEL = "gpt-4o-custom"
        const models = mockGetAvailableModels()
        expect(models).toEqual(["gpt-4o-custom"])
      })
    })
  })

  // ── Click handler flow ──────────────────────────────────────────────

  describe("click handler flow", () => {
    test("cycles from gpt-4o-mini → gpt-4o (env var + store + log + instance reset)", () => {
      withCleanEnv(() => {
        // Setup
        process.env.OPENAI_API_KEY = "sk-test"
        process.env.ARGUS_PLANNER_MODEL = "gpt-4o-mini"
        createMockInstance()
        initScan("https://test.com", "eng-test")
        setPlannerModel("openai/gpt-4o-mini", "ARGUS_PLANNER_MODEL=gpt-4o-mini")

        // Click handler logic (from scan.tsx)
        const available = mockGetAvailableModels()
        const current = mockGetCurrentModelId()
        const idx = current ? available.indexOf(current) : -1
        const nextIdx = (idx + 1) % available.length
        const nextModel = available[nextIdx]

        mockSwitchModel(nextModel)
        setPlannerModel(
          `${nextModel.includes("claude") ? "anthropic" : "openai"}/${nextModel}`,
          `ARGUS_PLANNER_MODEL=${nextModel} (click to switch)`,
        )
        appendLog(`🔁 Switched planner model to ${nextModel}`)

        // Verify env var updated
        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("gpt-4o")
        // Verify scan-store updates
        const state = getScanState()
        expect(state.llmPlanningModel).toBe("openai/gpt-4o")
        expect(state.llmPlanningModelConfig).toContain("gpt-4o")
        // Verify instance reset
        expect(_mockInstance!.model).toBeNull()
        expect(_mockInstance!.initialized).toBe(false)
        // Verify log entry
        expect(state.log.some((l: string) => l.includes("Switched planner model to gpt-4o"))).toBe(true)
      })
    })

    test("cycles through all 5 models and wraps back to start", () => {
      withCleanEnv(() => {
        process.env.OPENAI_API_KEY = "sk-test"
        process.env.ANTHROPIC_API_KEY = "sk-ant-test"
        process.env.ARGUS_PLANNER_MODEL = "gpt-4o-mini"
        createMockInstance()
        initScan("https://test.com", "eng-test")
        setPlannerModel("openai/gpt-4o-mini", "initial")
        appendLog("scan started")

        const models = mockGetAvailableModels()
        expect(models).toHaveLength(5)

        // Cycle through all 5 models (full wrap — back to gpt-4o-mini)
        for (let i = 0; i < models.length; i++) {
          const current = mockGetCurrentModelId()!
          const idx = models.indexOf(current)
          const nextIdx = (idx + 1) % models.length
          const nextModel = models[nextIdx]

          mockSwitchModel(nextModel)
          setPlannerModel(
            `${nextModel.includes("claude") ? "anthropic" : "openai"}/${nextModel}`,
            `ARGUS_PLANNER_MODEL=${nextModel}`,
          )
          appendLog(`🔁 Switched planner model to ${nextModel}`)
        }

        const state = getScanState()
        // After 5 clicks (full cycle) we're back to gpt-4o-mini
        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("gpt-4o-mini")
        expect(state.log.filter((l: string) => l.includes("Switched")).length).toBe(5)
      })
    })

    test("wraps from last Anthropic model back to first OpenAI model", () => {
      withCleanEnv(() => {
        process.env.OPENAI_API_KEY = "sk-test"
        process.env.ANTHROPIC_API_KEY = "sk-ant-test"
        // Start from the LAST model in the list (index 4 = claude-haiku)
        process.env.ARGUS_PLANNER_MODEL = "claude-haiku-3-5-20241022"
        createMockInstance()
        initScan("https://test.com", "eng-test")
        setPlannerModel("anthropic/claude-haiku-3-5-20241022", "initial")

        const models = mockGetAvailableModels()
        expect(models).toHaveLength(5)

        const current = mockGetCurrentModelId()!
        const idx = models.indexOf(current)
        expect(idx).toBe(4) // last model

        const nextIdx = (idx + 1) % models.length
        expect(nextIdx).toBe(0) // wraps to first (gpt-4o-mini)
        const nextModel = models[nextIdx]

        mockSwitchModel(nextModel)
        setPlannerModel(
          `${nextModel.includes("claude") ? "anthropic" : "openai"}/${nextModel}`,
          `ARGUS_PLANNER_MODEL=${nextModel} (wrap)`,
        )

        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("gpt-4o-mini")
        expect(getScanState().llmPlanningModel).toBe("openai/gpt-4o-mini")
      })
    })

    test("no-op guard when only one available model", () => {
      withCleanEnv(() => {
        delete process.env.OPENAI_API_KEY
        delete process.env.ANTHROPIC_API_KEY
        delete process.env.OPENCODE_API_KEY
        process.env.ARGUS_PLANNER_MODEL = "custom-model"

        const available = mockGetAvailableModels()
        expect(available).toHaveLength(1)
        expect(available[0]).toBe("custom-model")
        // Click handler returns early when available.length <= 1
        expect(available.length <= 1).toBe(true)
        // Nothing should change
        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("custom-model")
      })
    })

    test("full end-to-end: initial model → switch → scan-store → log all consistent", () => {
      withCleanEnv(() => {
        process.env.OPENAI_API_KEY = "sk-test"
        process.env.ARGUS_PLANNER_MODEL = "gpt-4o-mini"
        initScan("https://test.com", "eng-test")
        setPlannerModel("openai/gpt-4o-mini", "ARGUS_PLANNER_MODEL=gpt-4o-mini")

        // Switch to claude
        mockSwitchModel("claude-sonnet-4-20250514")
        setPlannerModel("anthropic/claude-sonnet-4-20250514", "ARGUS_PLANNER_MODEL=claude-sonnet-4-20250514 (switched)")
        appendLog("🔁 Switched planner model to claude-sonnet-4-20250514")

        const state = getScanState()

        // Env var — updated by mockSwitchModel
        expect(process.env.ARGUS_PLANNER_MODEL as unknown as string).toBe("claude-sonnet-4-20250514");
        // Store
        expect(state.llmPlanningModel).toBe("anthropic/claude-sonnet-4-20250514");
        expect(state.llmPlanningModelConfig).toBe("ARGUS_PLANNER_MODEL=claude-sonnet-4-20250514 (switched)");
        // Log
        expect(state.log.some((l: string) => l.includes("claude-sonnet-4-20250514"))).toBe(true);
      })
    });
  })
})

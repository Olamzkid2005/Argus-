/**
 * Planner model selection policy tests.
 *
 * These are the regression tests for the provider-credential leak: Argus used
 * to build its planner route from ambient OPENAI_API_KEY / ANTHROPIC_API_KEY /
 * OPENCODE_API_KEY, so any tool that exported those into the shell could
 * silently become the model Argus ran — and billed. The policy must only ever
 * select providers configured in OpenCode (auth.json) or OpenCode's own
 * gateway.
 */

import { describe, expect, test } from "bun:test"
import {
  ALLOW_AMBIENT_ENV_VAR,
  AMBIENT_LLM_ENV_VARS,
  ambientEnvAllowed,
  ignoredAmbientLlmEnvVars,
  isSelectableProviderID,
  selectPlannerModelRef,
} from "../../../../src/argus/planner/model-selection"

const provider = (models: string[]) => ({ models: Object.fromEntries(models.map((m) => [m, {}])) })

describe("ambient env policy", () => {
  test("every ambient provider var is listed", () => {
    expect([...AMBIENT_LLM_ENV_VARS]).toContain("OPENAI_API_KEY")
    expect([...AMBIENT_LLM_ENV_VARS]).toContain("OPENAI_BASE_URL")
    expect([...AMBIENT_LLM_ENV_VARS]).toContain("ANTHROPIC_API_KEY")
  })

  test("ambient vars are ignored by default", () => {
    expect(ambientEnvAllowed({ OPENAI_API_KEY: "sk-x" } as NodeJS.ProcessEnv)).toBe(false)

    const ignored = ignoredAmbientLlmEnvVars({
      OPENAI_API_KEY: "sk-x",
      OPENAI_BASE_URL: "https://openrouter.ai/api/v1",
    } as NodeJS.ProcessEnv)
    expect(ignored).toEqual(["OPENAI_API_KEY", "OPENAI_BASE_URL"])
  })

  test("blank values do not count as configured", () => {
    expect(ignoredAmbientLlmEnvVars({ OPENAI_API_KEY: "   " } as NodeJS.ProcessEnv)).toEqual([])
  })

  test("explicit opt-in re-enables ambient vars", () => {
    const env = { [ALLOW_AMBIENT_ENV_VAR]: "1", OPENAI_API_KEY: "sk-x" } as NodeJS.ProcessEnv
    expect(ambientEnvAllowed(env)).toBe(true)
    expect(ignoredAmbientLlmEnvVars(env)).toEqual([])
  })
})

describe("isSelectableProviderID", () => {
  const configured = new Set(["opencode-go", "deepseek"])

  test("allows providers configured in OpenCode", () => {
    expect(isSelectableProviderID("opencode-go", configured, false)).toBe(true)
    expect(isSelectableProviderID("deepseek", configured, false)).toBe(true)
  })

  test("allows OpenCode's own gateway", () => {
    expect(isSelectableProviderID("opencode", configured, false)).toBe(true)
    expect(isSelectableProviderID("opencode-zen", configured, false)).toBe(true)
  })

  test("rejects ambient-only providers", () => {
    // `openai` shows up in the registry purely because OPENAI_API_KEY is set.
    expect(isSelectableProviderID("openai", configured, false)).toBe(false)
    expect(isSelectableProviderID("anthropic", configured, false)).toBe(false)
  })

  test("opt-in allows everything", () => {
    expect(isSelectableProviderID("openai", configured, true)).toBe(true)
  })
})

describe("selectPlannerModelRef", () => {
  test("never selects an ambient-only provider when a configured one exists", () => {
    const result = selectPlannerModelRef({
      configured: ["opencode-go"],
      available: {
        openai: provider(["gpt-4o-mini"]),
        "opencode-go": provider(["mimo-v2.5-free"]),
      },
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.ref.providerID).toBe("opencode-go")
  })

  test("ignores OpenCode's default model when it points at an ambient-only provider", () => {
    // Reproduces the observed machine state: provider.list() contains `openai`
    // (from the ambient key) and defaultModel() could point at it.
    const result = selectPlannerModelRef({
      configured: ["deepseek"],
      available: {
        openai: provider(["gpt-4o-mini"]),
        deepseek: provider(["deepseek-chat"]),
      },
      defaultModel: { providerID: "openai", modelID: "gpt-4o-mini" },
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.ref.providerID).toBe("deepseek")
    expect(result.source).toBe("first-configured")
  })

  test("uses OpenCode's default model when its provider is selectable", () => {
    const result = selectPlannerModelRef({
      configured: ["opencode-go"],
      available: { "opencode-go": provider(["mimo-v2.5-free", "other"]) },
      defaultModel: { providerID: "opencode-go", modelID: "mimo-v2.5-free" },
    })
    expect(result).toEqual({
      ok: true,
      ref: { providerID: "opencode-go", modelID: "mimo-v2.5-free" },
      source: "default",
    })
  })

  test("prefers OpenCode's own gateway over third-party providers", () => {
    const result = selectPlannerModelRef({
      configured: ["deepseek", "xiaomi"],
      available: {
        deepseek: provider(["deepseek-chat"]),
        xiaomi: provider(["mimo"]),
        opencode: provider(["mimo-v2.5-free"]),
      },
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.ref.providerID).toBe("opencode")
  })

  test("honours an explicit provider/model selection", () => {
    const result = selectPlannerModelRef({
      preferred: "deepseek/deepseek-chat",
      configured: ["deepseek"],
      available: { deepseek: provider(["deepseek-chat"]) },
    })
    expect(result).toEqual({
      ok: true,
      ref: { providerID: "deepseek", modelID: "deepseek-chat" },
      source: "explicit",
    })
  })

  test("resolves a bare model id on a configured provider", () => {
    const result = selectPlannerModelRef({
      preferred: "deepseek-chat",
      configured: ["deepseek"],
      available: { deepseek: provider(["deepseek-chat"]) },
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.ref).toEqual({ providerID: "deepseek", modelID: "deepseek-chat" })
  })

  test("an explicit selection naming an unconfigured provider is an error, not a fallback", () => {
    const result = selectPlannerModelRef({
      preferred: "openai/gpt-4o-mini",
      configured: ["deepseek"],
      available: {
        openai: provider(["gpt-4o-mini"]),
        deepseek: provider(["deepseek-chat"]),
      },
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.reason).toContain("openai")
    expect(result.reason).toContain("not configured")
  })

  test("an unknown model on a configured provider is an error", () => {
    const result = selectPlannerModelRef({
      preferred: "deepseek/does-not-exist",
      configured: ["deepseek"],
      available: { deepseek: provider(["deepseek-chat"]) },
    })
    expect(result.ok).toBe(false)
  })

  test("empty registry explains how to configure a provider", () => {
    const result = selectPlannerModelRef({ configured: [], available: {} })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.reason).toContain("opencode auth login")
  })

  test("ambient-only registry is empty for Argus", () => {
    const result = selectPlannerModelRef({
      configured: [],
      available: { openai: provider(["gpt-4o-mini"]) },
    })
    expect(result.ok).toBe(false)
  })

  test("opt-in makes ambient-only providers selectable", () => {
    const result = selectPlannerModelRef({
      configured: [],
      available: { openai: provider(["gpt-4o-mini"]) },
      allowAmbient: true,
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.ref).toEqual({ providerID: "openai", modelID: "gpt-4o-mini" })
  })

  test("provider that advertises no models is reported", () => {
    const result = selectPlannerModelRef({
      configured: ["opencode-go"],
      available: { "opencode-go": provider([]) },
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.reason).toContain("no models")
  })
})

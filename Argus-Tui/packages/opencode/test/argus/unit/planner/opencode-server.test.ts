/**
 * Pure parts of the OpenCode-server transport.
 *
 * The transport exists because OpenCode's own gateways refuse direct calls from
 * this source tree (see docs/DEMO-READINESS-PLAN.md, blocker B9), so planner and
 * worker calls are made by a local OpenCode server instead. Talking to a real
 * server needs an installed `opencode` plus network, so it is covered by
 * mcp-style integration checks; what is pinned here is the part that decides
 * *how* to talk, and the parsing that real free-tier replies made necessary.
 */

import { describe, expect, test } from "bun:test"
import { parseJsonObject, unwrapToolCall } from "@/argus/planner/opencode-server"
import { LLM_TRANSPORT_ENV_VAR, selectPlannerTransport } from "@/argus/planner/llm-service"

describe("parseJsonObject", () => {
  test("plain object", () => {
    expect(parseJsonObject('{"a":1}')).toEqual({ a: 1 })
  })

  test("fenced json", () => {
    expect(parseJsonObject('```json\n{"a":1}\n```')).toEqual({ a: 1 })
  })

  test("object embedded in prose", () => {
    expect(parseJsonObject('Sure! Here is the plan: {"a":1} — hope that helps.')).toEqual({ a: 1 })
  })

  test("arrays are objects too", () => {
    expect(parseJsonObject("[[1,2]]")).toEqual([[1, 2]])
  })

  test("no JSON at all", () => {
    expect(parseJsonObject("I could not answer that.")).toBeUndefined()
  })

  test("empty text", () => {
    expect(parseJsonObject("   ")).toBeUndefined()
  })
})

describe("unwrapToolCall", () => {
  test("unwraps a tool call a model wrote instead of making it", () => {
    // Observed verbatim from a free-tier model asked for structured output.
    const written = { name: "StructuredOutput", parameters: { target_analysis: "x", phases: [] } }
    expect(unwrapToolCall(written)).toEqual({ target_analysis: "x", phases: [] })
  })

  test("unwraps through nested arrays", () => {
    const written = [[{ name: "StructuredOutput", parameters: { ok: true } }]]
    expect(unwrapToolCall(written)).toEqual({ ok: true })
  })

  test("leaves a normal answer alone", () => {
    expect(unwrapToolCall({ target_analysis: "x", suggested_phases: [] })).toEqual({
      target_analysis: "x",
      suggested_phases: [],
    })
  })

  test("does not unwrap on a name alone", () => {
    // A legitimate answer may carry a `name`; only an envelope has parameters.
    expect(unwrapToolCall({ name: "something", value: 1 })).toEqual({
      name: "something",
      value: 1,
    })
  })

  test("scalars and null are not objects", () => {
    expect(unwrapToolCall("text")).toBeUndefined()
    expect(unwrapToolCall(42)).toBeUndefined()
    expect(unwrapToolCall(null)).toBeUndefined()
  })
})

describe("selectPlannerTransport", () => {
  /**
   * Read the default rule from a known state.
   *
   * Suites that must not spawn a real `opencode serve` pin
   * `ARGUS_LLM_TRANSPORT=direct` at module scope, and Bun runs the test files in
   * one process, so the variable may hold another file's value here.
   */
  function withNoPreference<T>(fn: () => T): T {
    const previous = process.env[LLM_TRANSPORT_ENV_VAR]
    delete process.env[LLM_TRANSPORT_ENV_VAR]
    try {
      return fn()
    } finally {
      if (previous !== undefined) process.env[LLM_TRANSPORT_ENV_VAR] = previous
    }
  }

  test("OpenCode's own gateways go through the local server", () => {
    // A direct call from this build is refused by those gateways, so the server
    // is not a preference here — it is the only transport that can work.
    withNoPreference(() => {
      expect(selectPlannerTransport("opencode")).toBe("server")
      expect(selectPlannerTransport("opencode-go")).toBe("server")
    })
  })

  test("other providers are called directly", () => {
    withNoPreference(() => {
      expect(selectPlannerTransport("deepseek")).toBe("direct")
      expect(selectPlannerTransport("anthropic")).toBe("direct")
    })
  })

  test("the environment can force either transport", () => {
    expect(selectPlannerTransport("deepseek", "server")).toBe("server")
    expect(selectPlannerTransport("opencode", "direct")).toBe("direct")
  })

  test("an unknown preference falls back to the default rule", () => {
    expect(selectPlannerTransport("opencode", "nonsense")).toBe("server")
    expect(selectPlannerTransport("deepseek", "nonsense")).toBe("direct")
  })
})

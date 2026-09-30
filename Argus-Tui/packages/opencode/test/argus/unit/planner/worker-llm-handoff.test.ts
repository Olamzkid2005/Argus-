/**
 * The planner→worker LLM handoff is a wire contract with Python.
 *
 * The planner resolves the model (it owns OpenCode's provider registry) and
 * passes the result to the Python worker at `agent_init`, where
 * `argus-workers/config/llm_env.py::build_worker_llm_config` validates it. The
 * two sides are written in different languages and cannot check each other at
 * compile time, so a renamed key here would silently downgrade every worker run
 * to deterministic mode — these tests pin the keys, and the transport rules
 * that decide which of the two forms is sent.
 */

import { describe, expect, test } from "bun:test"
import { buildServerWorkerLlmConfig } from "../../../../src/argus/planner/model-registry"
import {
  LLM_TRANSPORT_ENV_VAR,
  selectPlannerTransport,
} from "../../../../src/argus/planner/opencode-server"

describe("buildServerWorkerLlmConfig", () => {
  test("emits exactly the keys the Python worker requires", () => {
    const config = buildServerWorkerLlmConfig({
      providerID: "opencode",
      modelID: "nemotron-3-ultra-free",
      baseUrl: "http://127.0.0.1:41234",
      directory: "/Users/mac/Documents/Argus-",
    })

    // `provider` and `baseUrl` are required by llm_env.py; `providerID` and
    // `modelID` name the model to prompt with; `directory` scopes the server.
    expect(Object.keys(config).sort()).toEqual([
      "baseUrl",
      "directory",
      "modelID",
      "provider",
      "providerID",
    ])
    expect(config.provider).toBe("opencode-server")
    expect(config.modelID).toBe("nemotron-3-ultra-free")
  })
})

describe("selectPlannerTransport governs the worker handoff too", () => {
  /** Read the default rule from a known state; see opencode-server.test.ts. */
  function withNoPreference<T>(fn: () => T): T {
    const previous = process.env[LLM_TRANSPORT_ENV_VAR]
    delete process.env[LLM_TRANSPORT_ENV_VAR]
    try {
      return fn()
    } finally {
      if (previous !== undefined) process.env[LLM_TRANSPORT_ENV_VAR] = previous
    }
  }

  test("opencode providers borrow the server by default", () => {
    // Direct calls from this source tree are refused with
    // `FreeTierError: OpenCode's free tier can only be used from within
    // OpenCode`, so the planner and the worker must both go through a server.
    withNoPreference(() => {
      expect(selectPlannerTransport("opencode")).toBe("server")
      expect(selectPlannerTransport("opencode-go")).toBe("server")
    })
  })

  test("other providers are called directly", () => {
    withNoPreference(() => {
      expect(selectPlannerTransport("anthropic")).toBe("direct")
      expect(selectPlannerTransport("openrouter")).toBe("direct")
    })
  })

  test("an explicit transport preference wins for both runtimes", () => {
    expect(selectPlannerTransport("opencode", "direct")).toBe("direct")
    expect(selectPlannerTransport("anthropic", "server")).toBe("server")
  })

  test("the preference is read from ARGUS_LLM_TRANSPORT", () => {
    // The worker handoff calls this without an argument, so the env var is the
    // one knob that keeps the two runtimes on the same transport.
    expect(LLM_TRANSPORT_ENV_VAR).toBe("ARGUS_LLM_TRANSPORT")
  })
})

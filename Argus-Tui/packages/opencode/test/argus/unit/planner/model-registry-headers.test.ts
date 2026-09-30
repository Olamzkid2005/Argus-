/**
 * How the planner identifies itself on the wire.
 *
 * Regression test for a real, measured failure: the planner built its route
 * without the headers OpenCode's own session layer sends, so every call to an
 * `opencode*` gateway was rejected before the model was ever reached —
 *
 *   HTTP 400 {"type":"MissingSessionID",
 *             "message":"Request is missing x-opencode-session ..."}
 *
 * `session/llm/request.ts` is the only place that knows how OpenCode identifies
 * itself to its own gateways. The planner talks to the same gateways with the
 * same credentials, so it must send the same headers.
 */

import { describe, expect, test } from "bun:test"
import { buildRouteHeaders } from "@/argus/planner/model-registry"

const input = {
  projectID: "proj_abc123",
  sessionID: "ses_argus-test",
  userAgent: "opencode/latest/1.0.0/cli",
}

describe("planner route headers", () => {
  test("opencode gateways get the full OpenCode identification block", () => {
    const headers = buildRouteHeaders({ ...input, providerID: "opencode" })

    expect(headers).toEqual({
      "x-opencode-project": "proj_abc123",
      "x-opencode-session": "ses_argus-test",
      "x-opencode-client": "cli",
      "User-Agent": "opencode/latest/1.0.0/cli",
    })
  })

  test("opencode-go (paid) is treated as an opencode gateway too", () => {
    const headers = buildRouteHeaders({ ...input, providerID: "opencode-go" })

    expect(headers?.["x-opencode-session"]).toBe("ses_argus-test")
    expect(headers?.["x-opencode-client"]).toBe("cli")
  })

  test("the session id is sent even before a project is known", () => {
    // A missing session id is the exact field the gateway rejected; it must not
    // be collateral damage from an unresolvable project id.
    const headers = buildRouteHeaders({ ...input, projectID: undefined, providerID: "opencode" })

    expect(headers?.["x-opencode-session"]).toBe("ses_argus-test")
    expect(headers).not.toHaveProperty("x-opencode-project")
  })

  test("third-party providers get session affinity, not OpenCode headers", () => {
    const headers = buildRouteHeaders({ ...input, providerID: "deepseek" })

    expect(headers).toEqual({
      "x-session-affinity": "ses_argus-test",
      "User-Agent": "opencode/latest/1.0.0/cli",
    })
    expect(headers).not.toHaveProperty("x-opencode-session")
  })

  test("every provider is identified with a real user agent", () => {
    for (const providerID of ["opencode", "opencode-go", "deepseek", "xiaomi"]) {
      const headers = buildRouteHeaders({ ...input, providerID })
      expect(headers?.["User-Agent"]).toBe("opencode/latest/1.0.0/cli")
    }
  })

  test("github-copilot gets no injected headers", () => {
    expect(buildRouteHeaders({ ...input, providerID: "github-copilot" })).toBeUndefined()
  })
})

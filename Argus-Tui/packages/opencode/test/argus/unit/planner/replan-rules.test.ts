import { describe, expect, test } from "bun:test"
import { determineNewCapabilities } from "@argus/planner/replan-rules"
import { Capability } from "@argus/planner/capabilities"
import type { PlannerContext, NormalizedFinding } from "@argus/planner/types"

function makeContext(overrides?: Partial<PlannerContext>): PlannerContext {
  return {
    target: "https://example.com",
    targetType: "web_app",
    authState: "none",
    findings: [],
    executedCapabilities: new Set<Capability>(),
    insertedPhases: new Set<string>(),
    replanCount: 0,
    ...overrides,
  }
}

function makeFinding(subtype?: string): NormalizedFinding {
  return {
    id: "f-1",
    title: "Test Finding",
    severity: 2 as any,
    confidence: 1 as any,
    status: "PENDING",
    description: "a finding",
    tool: "scanner",
    phase: "recon",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    subtype,
  }
}

describe("determineNewCapabilities", () => {
  test("returns empty set when no findings have subtypes", () => {
    const ctx = makeContext({ findings: [makeFinding(undefined), makeFinding(undefined)] })
    const result = determineNewCapabilities(ctx)
    expect(result.size).toBe(0)
  })

  test("returns empty set when all detected subtypes are already in executedCapabilities", () => {
    const ctx = makeContext({
      findings: [makeFinding("graphql")],
      executedCapabilities: new Set([Capability.GRAPHQL_ASSESSMENT]),
    })
    const result = determineNewCapabilities(ctx)
    expect(result.size).toBe(0)
  })

  test("adds GRAPHQL_ASSESSMENT for graphql subtype", () => {
    const ctx = makeContext({ findings: [makeFinding("graphql")] })
    const result = determineNewCapabilities(ctx)
    expect(result.has(Capability.GRAPHQL_ASSESSMENT)).toBe(true)
    expect(result.size).toBe(1)
  })

  test("adds EXPRESS_CVE_SCAN for expressjs subtype", () => {
    const ctx = makeContext({ findings: [makeFinding("expressjs")] })
    const result = determineNewCapabilities(ctx)
    expect(result.has(Capability.EXPRESS_CVE_SCAN)).toBe(true)
    expect(result.size).toBe(1)
  })

  test("adds API_DOCS_ANALYSIS for swagger and openapi subtypes", () => {
    const ctx = makeContext({ findings: [makeFinding("swagger"), makeFinding("openapi")] })
    const result = determineNewCapabilities(ctx)

    expect(result.has(Capability.API_DOCS_ANALYSIS)).toBe(true)
  })

  test("adds JWT_ANALYSIS for jwt subtype", () => {
    const ctx = makeContext({ findings: [makeFinding("jwt")] })
    const result = determineNewCapabilities(ctx)
    expect(result.has(Capability.JWT_ANALYSIS)).toBe(true)
    expect(result.size).toBe(1)
  })

  test("adds SSRF_CHECK for ssrf_parameters subtype", () => {
    const ctx = makeContext({ findings: [makeFinding("ssrf_parameters")] })
    const result = determineNewCapabilities(ctx)
    expect(result.has(Capability.SSRF_CHECK)).toBe(true)
    expect(result.size).toBe(1)
  })

  test("adds SQLI_DETECTION for sqli_reflective and sqli_blind subtypes", () => {
    const ctx = makeContext({
      findings: [makeFinding("sqli_reflective"), makeFinding("sqli_blind")],
    })
    const result = determineNewCapabilities(ctx)
    expect(result.has(Capability.SQLI_DETECTION)).toBe(true)
  })

  test("deduplicates when multiple findings map to same capability", () => {
    const ctx = makeContext({
      findings: [makeFinding("sqli_reflective"), makeFinding("sqli_blind")],
    })
    const result = determineNewCapabilities(ctx)
    expect(result.size).toBe(1)
  })

  test("handles empty findings array", () => {
    const ctx = makeContext({ findings: [] })
    const result = determineNewCapabilities(ctx)
    expect(result.size).toBe(0)
  })

  test("handles null/undefined subtype", () => {
    const ctx = makeContext({
      findings: [makeFinding(undefined), makeFinding(null as any)],
    })
    const result = determineNewCapabilities(ctx)
    expect(result.size).toBe(0)
  })
})

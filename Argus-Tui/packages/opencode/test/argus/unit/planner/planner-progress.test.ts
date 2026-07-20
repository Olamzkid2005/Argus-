/**
 * Integration tests: WorkflowPlanner → ProgressEvent emissions.
 *
 * Verifies that planner.plan() and planner.replan() emit the correct
 * ProgressEvent types in the right order when `onProgress` is provided.
 *
 * Strategy: Use mock.module() to replace the entire llm-service module
 * that the planner imports. This means the planner gets our controlled
 * mock without ever loading the real LLMPlannerService (and its
 * @opencode-ai/llm dependency chain).
 */

import { describe, expect, test, mock, beforeEach } from "bun:test"
import type { ProgressEvent } from "../../../../src/argus/shared/progress"
import type { PlannerContext } from "../../../../src/argus/planner/types"
import type { WorkflowDefinition } from "../../../../src/argus/workflows/types"

// ── Mock LLMPlannerService module ────────────────────────────────────
// This must be done BEFORE importing the planner (via dynamic import)
// because static imports are hoisted and execute before module-scope code.
// By using dynamic import(), mock.module() runs first, then the planner
// resolves ./llm-service to our mocked version.

const mockSuggestPhases = mock<(...args: any[]) => any>()
const mockSuggestReplan = mock<(...args: any[]) => any>()
const mockGetModelId = mock(() => "openai/gpt-4o-mock")

const mockLlmSvc = {
  suggestPhases: mockSuggestPhases,
  suggestReplan: mockSuggestReplan,
  getModelId: mockGetModelId,
  isAvailable: mock(async () => true) as any,
  getInitError: () => null,
}

mock.module("../../../../src/argus/planner/llm-service.ts", () => ({
  LLMPlannerService: {
    lazy: () => mockLlmSvc as any,
    getModelEnvVarDescription: () => "ARGUS_PLANNER_MODEL=test-model (mock)",
  },
}))

// Dynamic import so mock.module() is set up BEFORE the planner module resolves
const { WorkflowPlanner } = await import("../../../../src/argus/planner/planner")
const { Capability } = await import("../../../../src/argus/planner/capabilities")

// ── Mock workflow/tool registries ─────────────────────────────────────

function mockWorkflow(overrides?: Partial<WorkflowDefinition>): WorkflowDefinition {
  return {
    name: "test-workflow",
    label: "Test Workflow",
    version: 1,
    phases: [
      { name: "recon", required_capabilities: [Capability.WEB_RECON], execution: "parallel", error_recovery: "retry_once_then_skip" },
      { name: "reporting", required_capabilities: [Capability.REPORT_GENERATION], execution: "sequential", error_recovery: "fail_fast" },
    ],
    ...overrides,
  }
}

const singleTool = { name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 }

function makeRegistry() {
  const workflow = mockWorkflow()
  return {
    findByCapabilities: () => workflow,
    loadAll: () => [],
    listWorkflows: () => [workflow],
    getWorkflow: () => workflow,
  }
}

function makeToolRegistry() {
  return {
    selectBest: () => [singleTool],
    findBestTools: () => [singleTool],
    getToolsByCapability: () => [],
    getTool: () => singleTool,
    listTools: () => [],
    load: () => {},
    getCapabilities: () => ["web_recon"],
    setConfig: () => {},
  }
}

function makeContext(overrides?: Partial<PlannerContext>): PlannerContext {
  return {
    target: "https://example.com",
    targetType: "web_app",
    authState: "none",
    findings: [],
    executedCapabilities: new Set<Capability>() as any,
    insertedPhases: new Set<string>(),
    replanCount: 0,
    ...overrides,
  }
}

const sampleFinding = {
  id: "f-1",
  title: "SQL Injection",
  severity: 4 as any,
  confidence: 3 as any,
  status: "PENDING" as const,
  description: "sqli in login",
  subtype: "sqli_reflective",
  tool: "scanner",
  phase: "recon",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

// ── Tests ─────────────────────────────────────────────────────────────

describe("WorkflowPlanner progress events", () => {
  beforeEach(() => {
    mockSuggestPhases.mockReset()
    mockSuggestReplan.mockReset()
    mockGetModelId.mockReset()
    mockGetModelId.mockImplementation(() => "openai/gpt-4o-mock")
  })

  // ── plan() progress events ─────────────────────────────────────────

  describe("plan()", () => {
    test("emits llm_planning_start then llm_planning_complete with suggestions", async () => {
      mockSuggestPhases.mockImplementation(async () => ({
        targetAnalysis: "Web application with React frontend. Standard assessment phases recommended.",
        suggestedPhases: [
          { capabilities: ["web_recon", "technology_detection"], reasoning: "Identify tech stack and attack surface." },
          { capabilities: ["vulnerability_scanning", "template_scanning"], reasoning: "Automated vulnerability detection." },
        ],
      }))

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      await planner.plan("https://example.com", undefined, {
        onProgress: (e) => events.push(e),
      })

      expect(events.length).toBe(2)
      expect(events[0].type).toBe("llm_planning_start")
      expect((events[0] as any).phase).toBe("initial")
      expect(events[1].type).toBe("llm_planning_complete")

      const complete = events[1] as Extract<ProgressEvent, { type: "llm_planning_complete" }>
      expect(complete.targetAnalysis).toBe("Web application with React frontend. Standard assessment phases recommended.")
      expect(complete.suggestions).toHaveLength(2)
      expect(complete.suggestions[0].capabilities).toContain("web_recon")
      expect(complete.suggestions[1].reasoning).toContain("vulnerability")
      // Verify model fields are emitted in the event
      expect(complete.llmModel).toBe("openai/gpt-4o-mock")
      expect(complete.modelEnvDescription).toBe("ARGUS_PLANNER_MODEL=test-model (mock)")
    })

    test("emits llm_planning_complete with empty suggestions when LLM returns nothing", async () => {
      mockSuggestPhases.mockImplementation(async () => ({
        targetAnalysis: "",
        suggestedPhases: [],
      }))

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      await planner.plan("https://example.com", undefined, {
        onProgress: (e) => events.push(e),
      })

      expect(events.length).toBe(2)
      const complete = events[1] as Extract<ProgressEvent, { type: "llm_planning_complete" }>
      expect(complete.suggestions).toHaveLength(0)
      expect(complete.targetAnalysis).toBe("")
    })

    test("emits llm_planning_start then llm_planning_error when LLM throws", async () => {
      mockSuggestPhases.mockImplementation(async () => {
        throw new Error("API rate limit exceeded")
      })

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      await planner.plan("https://example.com", undefined, {
        onProgress: (e) => events.push(e),
      })

      expect(events.length).toBe(2)
      expect(events[0].type).toBe("llm_planning_start")
      expect(events[1].type).toBe("llm_planning_error")
      const err = events[1] as Extract<ProgressEvent, { type: "llm_planning_error" }>
      expect(err.phase).toBe("initial")
      expect(err.error).toContain("API rate limit exceeded")
    })

    test("does not emit LLM events when useLLM is false", async () => {
      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      await planner.plan("https://example.com", undefined, {
        useLLM: false,
        onProgress: (e) => events.push(e),
      })

      expect(events.every((e) => !e.type.startsWith("llm_planning"))).toBe(true)
    })

    test("does not throw when onProgress is not provided (optional callback)", async () => {
      mockSuggestPhases.mockImplementation(async () => ({
        targetAnalysis: "Test",
        suggestedPhases: [{ capabilities: ["web_recon"], reasoning: "Test" }],
      }))

      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      await expect(planner.plan("https://example.com")).resolves.toBeDefined()
    })

    test("preserves suggestion shape with multiple capabilities per phase", async () => {
      mockSuggestPhases.mockImplementation(async () => ({
        targetAnalysis: "API target. Focus on endpoint security.",
        suggestedPhases: [
          { capabilities: ["api_probing", "auth_detection"], reasoning: "Discover API endpoints and auth mechanisms." },
          { capabilities: ["sqli_detection", "xss_detection", "command_injection"], reasoning: "Injector vulnerability testing." },
          { capabilities: ["graphql_assessment"], reasoning: "GraphQL introspection and query depth testing." },
        ],
      }))

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      await planner.plan("https://api.example.com/graphql", undefined, {
        onProgress: (e) => events.push(e),
      })

      expect(events.length).toBe(2)
      const complete = events[1] as Extract<ProgressEvent, { type: "llm_planning_complete" }>
      expect(complete.suggestions).toHaveLength(3)
      expect(complete.suggestions[0].capabilities).toEqual(["api_probing", "auth_detection"])
      expect(complete.suggestions[1].capabilities).toEqual(["sqli_detection", "xss_detection", "command_injection"])
      expect(complete.suggestions[2].capabilities).toEqual(["graphql_assessment"])
    })
  })

  // ── replan() progress events ───────────────────────────────────────

  describe("replan()", () => {
    test("emits llm_replan_analysis when Local LLM produces suggestions", async () => {
      mockSuggestReplan.mockImplementation(async () => ({
        nextCapabilities: ["sqli_detection", "post_exploitation"],
        reasoning: "SQL injection confirmed. Proceed with exploitation.",
        stopAssessment: false,
      }))

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      const ctx = makeContext({
        findings: [sampleFinding],
        onProgress: (e) => events.push(e),
      })

      const replanResult = await planner.replan(ctx)

      expect(replanResult).not.toBeNull()
      expect(events.length).toBe(1)
      expect(events[0].type).toBe("llm_replan_analysis")
      const analysis = events[0] as Extract<ProgressEvent, { type: "llm_replan_analysis" }>
      expect(analysis.label).toBe("https://example.com")
      expect(analysis.reasoning).toContain("SQL injection confirmed")
      expect(analysis.suggestedCapabilities).toEqual(["sqli_detection", "post_exploitation"])
      expect(analysis.stopAssessment).toBe(false)
      expect(analysis.llmModel).toBe("openai/gpt-4o-mock")
    })

    test("emits llm_replan_analysis with stopAssessment=true, LLM phases skipped but rule phases still produced", async () => {
      mockSuggestReplan.mockImplementation(async () => ({
        nextCapabilities: [],
        reasoning: "All critical findings have been identified and verified. Assessment is complete.",
        stopAssessment: true,
      }))

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      const ctx = makeContext({
        findings: [{ ...sampleFinding, confidence: 5 as any }],
        onProgress: (e) => events.push(e),
      })

      const replanResult = await planner.replan(ctx)

      expect(events.length).toBe(1)
      const analysis = events[0] as Extract<ProgressEvent, { type: "llm_replan_analysis" }>
      expect(analysis.stopAssessment).toBe(true)
      expect(analysis.suggestedCapabilities).toEqual([])
      // stopAssessment=true means LLM suggestions are NOT added to phases,
      // but rule-based replanning (from REPLAN_INSERTABLE subtypes) still
      // produces phases independently.
      expect(replanResult).not.toBeNull()
    })

    test("emits llm_planning_error when Local LLM throws during replan", async () => {
      mockSuggestReplan.mockImplementation(async () => {
        throw new Error("Model temporarily overloaded")
      })

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      const ctx = makeContext({
        findings: [sampleFinding],
        onProgress: (e) => events.push(e),
      })

      const replanResult = await planner.replan(ctx)

      expect(events.length).toBe(1)
      expect(events[0].type).toBe("llm_planning_error")
      const err = events[0] as Extract<ProgressEvent, { type: "llm_planning_error" }>
      expect(err.phase).toBe("replan")
      expect(err.error).toContain("Model temporarily overloaded")
      expect(replanResult).not.toBeNull()
    })

    test("does not emit LLM events when findings is empty", async () => {
      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      const ctx = makeContext({
        findings: [],
        onProgress: (e) => events.push(e),
      })

      const replanResult = await planner.replan(ctx)

      expect(events.length).toBe(0)
      expect(replanResult).toBeNull()
    })

    test("does not emit LLM events when LLM budget is exhausted", async () => {
      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      const ctx = makeContext({
        llmReplanCount: 10,
        llmMaxReplans: 10,
        findings: [sampleFinding],
        onProgress: (e) => events.push(e),
      })

      const replanResult = await planner.replan(ctx)

      expect(events.length).toBe(0)
      expect(replanResult).not.toBeNull()
    })

    test("llm_replan_analysis includes custom llmModel from getModelId()", async () => {
      mockGetModelId.mockImplementation(() => "anthropic/claude-sonnet-4-custom")
      mockSuggestReplan.mockImplementation(async () => ({
        nextCapabilities: ["jwt_analysis"],
        reasoning: "JWT found in auth headers.",
        stopAssessment: false,
      }))

      const events: ProgressEvent[] = []
      const planner = new WorkflowPlanner(makeRegistry() as any, makeToolRegistry() as any)
      const ctx = makeContext({
        findings: [{
          ...sampleFinding,
          title: "JWT Token", subtype: "jwt", description: "jwt in headers",
        }],
        onProgress: (e) => events.push(e),
      })

      const replanResult = await planner.replan(ctx)

      expect(events.length).toBe(1)
      const analysis = events[0] as Extract<ProgressEvent, { type: "llm_replan_analysis" }>
      expect(analysis.llmModel).toBe("anthropic/claude-sonnet-4-custom")
      expect(replanResult).not.toBeNull()
    })
  })
})

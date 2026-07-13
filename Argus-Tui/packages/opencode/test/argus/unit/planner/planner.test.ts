import { describe, expect, test } from "bun:test"
import { WorkflowPlanner, MAX_REPLANS } from "../../../../src/argus/planner/planner"
import { Capability } from "../../../../src/argus/planner/capabilities"
import type { PlannerContext } from "../../../../src/argus/planner/types"
import type { WorkflowDefinition } from "../../../../src/argus/workflows/types"

function mockWorkflow(overrides?: Partial<WorkflowDefinition>): WorkflowDefinition {
  return {
    name: "test-workflow",
    label: "Test Workflow",
    version: 1,
    phases: [
      {
        name: "recon",
        required_capabilities: [Capability.WEB_RECON],
        execution: "parallel",
        error_recovery: "retry_once_then_skip",
      },
      {
        name: "reporting",
        required_capabilities: [Capability.REPORT_GENERATION],
        execution: "sequential",
        error_recovery: "fail_fast",
      },
    ],
    ...overrides,
  }
}

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

describe("WorkflowPlanner", () => {
  describe("plan()", () => {
    test("returns an AssessmentPlan with detected target type", async () => {
      const workflow = mockWorkflow()
      const registry = {
        findByCapabilities: () => workflow,
      }
      const toolRegistry = {
        findBestTools: () => [{ name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 }],
        selectBest: () => [{ name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 }],
      }
      const planner = new WorkflowPlanner(registry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com/api/v1")

      expect(plan).toHaveProperty("phases")
      expect(plan).toHaveProperty("workflow")
      expect(plan).toHaveProperty("errorRecovery")
      expect(plan).toHaveProperty("planCreatedAt")
    })

    test("plan() returns phase objects with correct shape", async () => {
      const workflow = mockWorkflow()
      const registry = { findByCapabilities: () => workflow }
      const toolRegistry = {
        findBestTools: () => [{ name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 }],
        selectBest: () => [{ name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 }],
      }
      const planner = new WorkflowPlanner(registry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com")

      expect(plan.phases.length).toBeGreaterThan(0)
      for (const phase of plan.phases) {
        expect(phase).toHaveProperty("phaseId")
        expect(phase).toHaveProperty("workflowName")
        expect(phase).toHaveProperty("target")
        expect(phase).toHaveProperty("requiredCapabilities")
      }
    })

    test("plan() uses deterministic fallback when useLLM is false", async () => {
      const registry = { findByCapabilities: () => null }
      const toolRegistry = { findBestTools: () => [], selectBest: () => [] }
      const planner = new WorkflowPlanner(registry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com", {}, { useLLM: false })

      expect(plan.workflow).toBe("deterministic")
    })

    test("plan() falls back to deterministic when no workflow matches", async () => {
      const registry = { findByCapabilities: () => null }
      const toolRegistry = { findBestTools: () => [], selectBest: () => [] }
      const planner = new WorkflowPlanner(registry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com")

      expect(plan.workflow).toBe("deterministic")
    })
  })

  describe("replan()", () => {
    test("returns null when replanCount equals MAX_REPLANS", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        replanCount: MAX_REPLANS,
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      })
      const result = planner.replan(ctx)

      expect(result).toBeNull()
    })

    test("returns null when replanCount exceeds MAX_REPLANS", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        replanCount: MAX_REPLANS + 1,
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      })
      const result = planner.replan(ctx)

      expect(result).toBeNull()
    })

    test("returns null when no new capabilities found", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({ findings: [] })
      const result = planner.replan(ctx)

      expect(result).toBeNull()
    })

    test("returns new phases for unhandled capabilities", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        executedCapabilities: new Set([Capability.WEB_RECON]),
      })
      const result = planner.replan(ctx)

      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
      expect(result![0].requiredCapabilities).toContain(Capability.GRAPHQL_ASSESSMENT)
      expect(result![0].replanCycle).toBe(true)
      expect(result![0].toolExecution).toBe("sequential")
      expect(result![0].workflowName).toBe("replan")
      expect(result![0].phaseId).toMatch(/^replan-\d+-/)
    })

    test("writes back incremented replanCount to context", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        findings: [
          {
            id: "f-1",
            title: "Express App",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "express app detected",
            subtype: "expressjs",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        executedCapabilities: new Set([Capability.WEB_RECON]),
      })
      const result = planner.replan(ctx)

      expect(result).not.toBeNull()
      expect(result![0].replanCycle).toBe(true)
    })

    test("uses maxReplans from context when provided", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        replanCount: 1,
        maxReplans: 1,
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        executedCapabilities: new Set([Capability.WEB_RECON]),
      })
      expect(planner.replan(ctx)).toBeNull()

      const ctx2 = makeContext({
        replanCount: 0,
        maxReplans: 1,
        findings: [
          {
            id: "f-2",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        executedCapabilities: new Set([Capability.WEB_RECON]),
      })
      const result = planner.replan(ctx2)
      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
    })

    test("returns null when all new capabilities are already executed", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        findings: [
          {
            id: "f-1",
            title: "JWT Found",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "jwt token found",
            subtype: "jwt",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        executedCapabilities: new Set([Capability.JWT_ANALYSIS]),
      })
      const result = planner.replan(ctx)

      expect(result).toBeNull()
    })

    // ── Independent budget logic ──
    test("returns null when both rule and LLM budgets are exhausted", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        replanCount: MAX_REPLANS,
        llmReplanCount: MAX_REPLANS,
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
      })
      const result = planner.replan(ctx)

      expect(result).toBeNull()
    })

    test("LLM suggestions produce phases when rule budget exhausted", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        replanCount: MAX_REPLANS,  // rule budget exhausted
        llmReplanCount: 0,          // LLM budget still available
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
      })
      const result = planner.replan(ctx)

      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
      expect(result![0].requiredCapabilities).toContain(Capability.POST_EXPLOITATION)
      expect(result![0].workflowName).toBe("replan")
    })

    test("rule-based findings produce phases when LLM budget exhausted", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        llmReplanCount: MAX_REPLANS,  // LLM budget exhausted
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        executedCapabilities: new Set([Capability.WEB_RECON]),
      })
      const result = planner.replan(ctx)

      // LLM suggestions are skipped (budget exhausted), but rule-based finding still produces a phase
      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
      expect(result![0].requiredCapabilities).toContain(Capability.GRAPHQL_ASSESSMENT)
    })

    test("LLM-only suggestions produce phases without rule findings", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
        llmReplanCount: 0,
        // No findings — purely LLM-driven
      })
      const result = planner.replan(ctx)

      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
      expect(result![0].requiredCapabilities).toContain(Capability.POST_EXPLOITATION)
    })

    test("both LLM and rule-based suggestions combine when both budgets available", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
        executedCapabilities: new Set([Capability.WEB_RECON]),
      })
      const result = planner.replan(ctx)

      expect(result).not.toBeNull()
      // Should include BOTH the LLM-suggested POST_EXPLOITATION and rule-based GRAPHQL_ASSESSMENT
      const caps = result!.map(p => p.requiredCapabilities).flat()
      expect(caps).toContain(Capability.POST_EXPLOITATION)
      expect(caps).toContain(Capability.GRAPHQL_ASSESSMENT)
    })

    test("llmReplanCount increments when LLM produces phases", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        llmReplanCount: 0,
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
      })
      const result = planner.replan(ctx)

      expect(result).not.toBeNull()
      expect(ctx.llmReplanCount).toBe(1)
      expect(ctx.replanCount).toBe(1)  // also incremented (LLM caps became regularPhases)
    })

    test("llmReplanCount does not increment when all LLM suggestions already executed", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        llmReplanCount: 0,
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
        executedCapabilities: new Set([Capability.POST_EXPLOITATION]),
      })
      const result = planner.replan(ctx)

      expect(result).toBeNull()
      expect(ctx.llmReplanCount).toBe(0)
    })

    test("llmMaxReplans from context caps LLM-driven replanning", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        llmReplanCount: 2,
        llmMaxReplans: 2,
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
      })
      // LLM budget exhausted (2 >= 2), even though rule budget is available
      expect(planner.replan(ctx)).toBeNull()

      const ctx2 = makeContext({
        llmReplanCount: 1,
        llmMaxReplans: 2,
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
      })
      const result = planner.replan(ctx2)
      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
      expect(result![0].requiredCapabilities).toContain(Capability.POST_EXPLOITATION)
    })

    test("LLM suggestions with unknown capabilities are silently skipped", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        llmSuggestedCapabilities: ["UNKNOWN_CAP_X99"],
      })
      const result = planner.replan(ctx)

      // Unknown capability maps to undefined — no phases produced
      expect(result).toBeNull()
    })

    test("rule budget exhausted but LLM suggestions still produce phases — verifies replanCount not incremented for rule", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({
        replanCount: MAX_REPLANS,
        llmReplanCount: 0,
        llmSuggestedCapabilities: ["POST_EXPLOIT"],
        findings: [
          {
            id: "f-1",
            title: "GraphQL Endpoint",
            severity: 2 as any,
            confidence: 1 as any,
            status: "PENDING",
            description: "graphql endpoint found",
            subtype: "graphql",
            tool: "scanner",
            phase: "recon",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      })
      const result = planner.replan(ctx)

      // Only LLM phases produced (rule budget exhausted)
      expect(result).not.toBeNull()
      expect(result).toHaveLength(1)
      expect(result![0].requiredCapabilities).toContain(Capability.POST_EXPLOITATION)

      // replanCount stays exhausted (not incremented since no rule/chain phases)
      expect(ctx.replanCount).toBe(MAX_REPLANS)
      // llmReplanCount incremented
      expect(ctx.llmReplanCount).toBe(1)
    })
  })

  describe("plan — pipeline integration", () => {
    test("phases include pipelineSteps in config when pipeline resolves", async () => {
      const toolRegistry = {
        selectBest: () => [{ name: "subfinder", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }],
        getToolsByCapability: () => [],
        getTool: () => ({ name: "subfinder", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }),
        listTools: () => [],
        load: () => {},
        getCapabilities: () => ["web_recon"],
        findBestTools: () => [],
        setConfig: () => {},
      }
      const workflowRegistry = {
        getWorkflow: (name: string) => name === "test-workflow" ? mockWorkflow() : null,
        loadAll: () => [],
        listWorkflows: () => [mockWorkflow()],
      }
      const planner = new WorkflowPlanner(workflowRegistry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com", undefined, { useLLM: false })
      expect(plan.phases.length).toBeGreaterThanOrEqual(1)
      expect(plan.phases[0].phaseId).toMatch(/^phase-/)
    })

    test("deterministic fallback with useLLM=false produces valid plan", async () => {
      const toolRegistry = {
        selectBest: () => [{ name: "nuclei", capabilities: ["vulnerability_scanning"], requires_auth: false, destructive: false, timeout_seconds: 30 }],
        getToolsByCapability: () => [],
        getTool: () => ({ name: "nuclei", capabilities: ["vulnerability_scanning"], requires_auth: false, destructive: false, timeout_seconds: 30 }),
        listTools: () => [],
        load: () => {},
        getCapabilities: () => ["vulnerability_scanning"],
        findBestTools: () => [],
        setConfig: () => {},
      }
      const workflowRegistry = {
        getWorkflow: () => null,
        loadAll: () => [],
        listWorkflows: () => [],
      }
      const planner = new WorkflowPlanner(workflowRegistry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com", undefined, { useLLM: false })
      expect(plan).toBeDefined()
      expect(plan.workflow).toBe("deterministic")
      expect(plan.phases.length).toBeGreaterThanOrEqual(1)
    })

    test("plan filters out phases with zero available tools", async () => {
      const toolRegistry = {
        selectBest: () => [],
        getToolsByCapability: () => [],
        getTool: () => undefined,
        listTools: () => [],
        load: () => {},
        getCapabilities: () => [],
        findBestTools: () => [],
        setConfig: () => {},
      }
      const workflowRegistry = {
        getWorkflow: (name: string) => name === "test-workflow" ? mockWorkflow() : null,
        loadAll: () => [],
        listWorkflows: () => [mockWorkflow()],
      }
      const planner = new WorkflowPlanner(workflowRegistry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com", undefined, { useLLM: false })
      expect(plan.phases).toHaveLength(0)
    })

    test("deterministic plan has valid errorRecovery map", async () => {
      const toolRegistry = {
        selectBest: () => [],
        getToolsByCapability: () => [],
        getTool: () => undefined,
        listTools: () => [],
        load: () => {},
        getCapabilities: () => [],
        findBestTools: () => [],
        setConfig: () => {},
      }
      const workflowRegistry = {
        getWorkflow: () => null,
        loadAll: () => [],
        listWorkflows: () => [],
      }
      const planner = new WorkflowPlanner(workflowRegistry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com", undefined, { useLLM: false })
      expect(plan).toBeDefined()
      expect(typeof plan.errorRecovery).toBe("object")
    })

    test("plan with LLM mode finds workflow and builds phases", async () => {
      const toolRegistry = {
        selectBest: () => [{ name: "subfinder", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }],
        getToolsByCapability: () => [],
        getTool: () => ({ name: "subfinder", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }),
        listTools: () => [],
        load: () => {},
        getCapabilities: () => ["web_recon"],
        findBestTools: () => [],
        setConfig: () => {},
      }
      const workflowRegistry = {
        getWorkflow: () => null,
        findByCapabilities: () => null,
        loadAll: () => [],
        listWorkflows: () => [],
      }
      const planner = new WorkflowPlanner(workflowRegistry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com")
      expect(plan).toBeDefined()
      expect(plan.workflow).toBe("deterministic")
    })
  })
})

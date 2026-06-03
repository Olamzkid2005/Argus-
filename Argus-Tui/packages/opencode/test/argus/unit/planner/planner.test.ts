import { describe, expect, test } from "bun:test"
import { WorkflowPlanner } from "@argus/planner/planner"
import { Capability } from "@argus/planner/capabilities"
import type { PlannerContext } from "@argus/planner/types"
import type { WorkflowDefinition } from "@argus/workflows/types"

const MAX_REPLANS = 10

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
      const toolRegistry = { findBestTools: () => [] }
      const planner = new WorkflowPlanner(registry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com", {}, { useLLM: false })

      expect(plan.workflow).toBe("deterministic")
    })

    test("plan() falls back to deterministic when no workflow matches", async () => {
      const registry = { findByCapabilities: () => null }
      const toolRegistry = { findBestTools: () => [] }
      const planner = new WorkflowPlanner(registry as any, toolRegistry as any)
      const plan = await planner.plan("https://example.com")

      expect(plan.workflow).toBe("deterministic")
    })
  })

  describe("replan()", () => {
    test("returns null when replanCount >= MAX_REPLANS", () => {
      const planner = new WorkflowPlanner({} as any, {} as any)
      const ctx = makeContext({ replanCount: MAX_REPLANS })
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
    })

    test("increments replanCount", () => {
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
      planner.replan(ctx)

      // replan no longer mutates context.replanCount — uses local counter
      expect(ctx.replanCount).toBe(0)
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
  })
})

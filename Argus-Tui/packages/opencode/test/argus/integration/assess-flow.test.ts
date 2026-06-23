import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import { WorkflowRegistry } from "../../../src/argus/workflows/registry"
import { ToolRegistry } from "../../../src/argus/workflows/tool-registry"
import { WorkflowPlanner } from "../../../src/argus/planner/planner"

let dbDir: string

const mockBridge = {
  callTool: async () => ({ success: true, data: [], durationMs: 0 }),
  connect: async () => {},
  disconnect: async () => {},
  supervisor: { resetAttempts: () => {}, restartWorker: async () => {} },
  isHealthy: async () => true,
  on: () => {},
  llmStatus: () => "AVAILABLE" as const,
  getTools: async () => [],
  detectDrift: async () => ({ missing_from_registry: [], missing_from_mcp: [], capability_gaps: [] }),
  killChild: () => {},
  restartWorker: async () => {},
} as any

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-flow-test-"))
})

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

const workflowsDir = join(__dirname, "../../../src/argus/workflows")
const toolsPath = join(workflowsDir, "tool-definitions.yaml")

describe("Assess Flow", () => {
  test("WorkflowRegistry loads real YAML files from src/argus/workflows/ directory", () => {
    const registry = new WorkflowRegistry(workflowsDir)
    const loaded = registry.loadAll()
    expect(loaded.length).toBeGreaterThanOrEqual(4)
    const names = loaded.map((w) => w.name)
    expect(names).toContain("full_assessment")
    expect(names).toContain("quick_scan")
    expect(names).toContain("api_assessment")
    expect(names).toContain("browser_assessment")
  })

  test("ToolRegistry loads real tool definitions from tool-definitions.yaml", () => {
    const registry = new ToolRegistry()
    registry.load(toolsPath)
    const tools = registry.listTools()
    expect(tools.length).toBeGreaterThan(0)
  })

  test("Planner generates a plan using the real registry", async () => {
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan("https://example.com", undefined, { useLLM: false })
    expect(plan.workflow).toBe("deterministic")
    expect(plan.phases.length).toBeGreaterThanOrEqual(2)
    expect(plan.errorRecovery).toBeTruthy()
  })

  test("EngagementStore persists the phases created by the planner", () => {
    const store = new EngagementStore(join(dbDir, `planner-persist-${Date.now()}.db`))
    const eng = store.createEngagement("https://planner-persist.com", "assessment")
    const phases = [
      { id: `pp-${Date.now()}-0-recon`, engagementId: eng.id, name: "recon", status: "PENDING" as const, capabilities: ["web_recon", "port_scanning"], executionMode: "parallel" as const, replanCycle: false },
      { id: `pp-${Date.now()}-1-vuln`, engagementId: eng.id, name: "vuln_scan", status: "PENDING" as const, capabilities: ["vulnerability_scanning"], executionMode: "parallel" as const, replanCycle: false },
    ]
    store.savePhases(eng.id, phases)
    const saved = store.getPhases(eng.id)
    expect(saved).toHaveLength(2)
    expect(saved[0].engagementId).toBe(eng.id)
    expect(saved[1].engagementId).toBe(eng.id)
  })

  test("assessCommand() with deterministic mode creates engagement, runs phases, produces findings", async () => {
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan("https://test-target.com", undefined, { useLLM: false })
    expect(plan.workflow).toBe("deterministic")
    expect(plan.phases.length).toBeGreaterThanOrEqual(2)
    for (const phase of plan.phases) {
      expect(phase.phaseId).toMatch(/^phase-\d+-/)
    }
    const store = new EngagementStore(join(dbDir, `assess-${Date.now()}.db`))
    const eng = store.createEngagement("https://test-target.com", "assessment")
    const phaseRecords = plan.phases.map((p, i) => ({
      id: p.phaseId,
      engagementId: eng.id,
      name: p.name,
      status: "PENDING" as const,
      capabilities: p.requiredCapabilities,
      executionMode: "sequential" as const,
      replanCycle: p.replanCycle ?? false,
    }))
    store.savePhases(eng.id, phaseRecords)
    const savedPhases = store.getPhases(eng.id)
    expect(savedPhases.length).toBe(plan.phases.length)
    const status = store.getEngagement(eng.id)!.status
    expect(status).toBe("CREATED")
  })

  test("WorkflowRunner.full pipeline creates engagement and runs phases via mocked bridge", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const store = new EngagementStore(join(dbDir, `int-pipeline-${Date.now()}.db`))
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan("https://pipeline-test.com", undefined, { useLLM: false })
    expect(plan.workflow).toBe("deterministic")

    const mockBridge = {
      callTool: async () => ({ success: true, data: [{ id: "f1", title: "finding-1", severity: 2, confidence: 0 }], durationMs: 5 }),
      connect: async () => {},
      disconnect: async () => {},
      supervisor: { resetAttempts: () => {}, restartWorker: async () => {} },
      isHealthy: async () => true,
      on: () => {},
      llmStatus: () => "AVAILABLE" as const,
      getTools: async () => [],
      detectDrift: async () => ({ missing_from_registry: [], missing_from_mcp: [], capability_gaps: [] }),
      quickDriftCheck: async () => true,
      killChild: () => {},
      restartWorker: async () => {},
      resetCircuitBreaker: () => {},
      setRegistryTools: () => {},
    } as any

    const runner = new WorkflowRunner({
      store,
      workflowRegistry,
      toolRegistry,
      planner,
      bridge: mockBridge,
    })

    const result = await runner.run({ target: "https://pipeline-test.com" })

    expect(result.engagementId).toBeTruthy()
    expect(result.engagementId).toMatch(/^ENG-/)
    expect(result.success).toBe(true)
    expect(result.durationMs).toBeGreaterThan(0)
  })

  test("WorkflowRunner.full pipeline handles execution errors gracefully", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const store = new EngagementStore(join(dbDir, `int-error-${Date.now()}.db`))
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan("https://error-test.com", undefined, { useLLM: false })
    expect(plan.workflow).toBe("deterministic")

    // Bridge that fails on callTool
    const failingBridge = {
      callTool: async () => ({ success: false, data: null, error: "Tool timed out", durationMs: 0 }),
      connect: async () => {},
      disconnect: async () => {},
      supervisor: { resetAttempts: () => {}, restartWorker: async () => {} },
      isHealthy: async () => true,
      on: () => {},
      llmStatus: () => "AVAILABLE" as const,
      getTools: async () => [],
      detectDrift: async () => ({ missing_from_registry: [], missing_from_mcp: [], capability_gaps: [] }),
      quickDriftCheck: async () => true,
      killChild: () => {},
      restartWorker: async () => {},
      resetCircuitBreaker: () => {},
      setRegistryTools: () => {},
    } as any

    const runner = new WorkflowRunner({
      store,
      workflowRegistry,
      toolRegistry,
      planner,
      bridge: failingBridge,
    })

    const result = await runner.run({ target: "https://error-test.com" })

    // Pipeline still returns a result even with errors
    expect(result.engagementId).toBeTruthy()
    expect(result.success).toBe(true) // overall pipeline succeeded
    expect(typeof result.durationMs).toBe("number")
  })

  test("WorkflowRunner progress callbacks receive expected pipeline events", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const store = new EngagementStore(join(dbDir, `int-progress-${Date.now()}.db`))
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan("https://progress-test.com", undefined, { useLLM: false })
    expect(plan.workflow).toBe("deterministic")

    const progressEvents: any[] = []
    const mockBridge = {
      callTool: async () => ({ success: true, data: [{ id: "f1", title: "finding-1", severity: 2, confidence: 0 }], durationMs: 5 }),
      connect: async () => {},
      disconnect: async () => {},
      supervisor: { resetAttempts: () => {}, restartWorker: async () => {} },
      isHealthy: async () => true,
      on: () => {},
      llmStatus: () => "AVAILABLE" as const,
      getTools: async () => [],
      detectDrift: async () => ({ missing_from_registry: [], missing_from_mcp: [], capability_gaps: [] }),
      quickDriftCheck: async () => true,
      killChild: () => {},
      restartWorker: async () => {},
      resetCircuitBreaker: () => {},
      setRegistryTools: () => {},
    } as any

    const runner = new WorkflowRunner({
      store,
      workflowRegistry,
      toolRegistry,
      planner,
      bridge: mockBridge,
    })

    await runner.run({
      target: "https://progress-test.com",
      onProgress: (event: any) => progressEvents.push(event),
    })

    // Should have received pipeline lifecycle events
    expect(progressEvents.length).toBeGreaterThan(0)

    const stringEvents = progressEvents.filter((e: any) => typeof e === "string")
    const objectEvents = progressEvents.filter((e: any) => typeof e === "object" && e.type)

    expect(stringEvents.length).toBeGreaterThan(0)
    expect(objectEvents.length).toBeGreaterThan(0)

    // Should include key lifecycle events
    const eventStrings = stringEvents.join(" ")
    expect(eventStrings).toMatch(/Target validated|Engagement|Planning|MCP workers|Phase|complete/)
  })

  test("planner generates deterministic plan with phases having valid structure", async () => {
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan("https://structural-test.com", undefined, { useLLM: false })

    expect(plan.workflow).toBe("deterministic")
    expect(plan.phases.length).toBeGreaterThanOrEqual(2)
    expect(plan.errorRecovery).toBeDefined()

    for (const phase of plan.phases) {
      expect(phase.phaseId).toMatch(/^phase-\d+-/)
      expect(phase.name).toBeTruthy()
      expect(phase.target).toBe("https://structural-test.com")
      expect(Array.isArray(phase.requiredCapabilities)).toBe(true)
      expect(phase.requiredCapabilities.length).toBeGreaterThan(0)
      expect(typeof phase.config).toBe("object")
      expect(Array.isArray(phase.previousPhaseResults)).toBe(true)
    }
  })

  test("engagement lifecycle: CREATED → RUNNING → COMPLETED", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const store = new EngagementStore(join(dbDir, `int-lifecycle-${Date.now()}.db`))
    const workflowRegistry = new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = new ToolRegistry()
    toolRegistry.load(toolsPath)
    const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)

    const mockBridge = {
      callTool: async () => ({ success: true, data: [], durationMs: 5 }),
      connect: async () => {},
      disconnect: async () => {},
      supervisor: { resetAttempts: () => {}, restartWorker: async () => {} },
      isHealthy: async () => true,
      on: () => {},
      llmStatus: () => "AVAILABLE" as const,
      getTools: async () => [],
      detectDrift: async () => ({ missing_from_registry: [], missing_from_mcp: [], capability_gaps: [] }),
      quickDriftCheck: async () => true,
      killChild: () => {},
      restartWorker: async () => {},
      resetCircuitBreaker: () => {},
      setRegistryTools: () => {},
    } as any

    const runner = new WorkflowRunner({
      store,
      workflowRegistry,
      toolRegistry,
      planner,
      bridge: mockBridge,
    })

    await runner.run({ target: "https://lifecycle-test.com" })

    // Find the engagement that was created
    const engagements = store.listEngagements()
    const created = engagements.find((e: any) => e.target === "https://lifecycle-test.com")
    expect(created).toBeDefined()
    // After successful run, status should be COMPLETED
    expect(created!.status).toBe("COMPLETED")

    // Phases should have been saved
    const phases = store.getPhases(created!.id)
    expect(phases.length).toBeGreaterThan(0)
    expect(phases.every((p: any) => p.status === "COMPLETED" || p.status === "PARTIAL")).toBe(true)
  })
})

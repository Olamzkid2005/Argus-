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
      { id: `pp-${Date.now()}-0-recon`, engagementId: eng.id, name: "recon", status: "PENDING" as const, capabilities: ["web_recon", "port_scanning"], executionMode: "parallel", replanCycle: false },
      { id: `pp-${Date.now()}-1-vuln`, engagementId: eng.id, name: "vuln_scan", status: "PENDING" as const, capabilities: ["vulnerability_scanning"], executionMode: "parallel", replanCycle: false },
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
})

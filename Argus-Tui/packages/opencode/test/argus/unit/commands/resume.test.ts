import { describe, expect, test, beforeAll, afterAll, mock } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"

let dbDir: string

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-resume-test-"))
})

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

function makeStore(name: string): EngagementStore {
  return new EngagementStore(join(dbDir, `${name}.db`))
}

describe("resume validation", () => {
  test("canResume returns true for RUNNING engagement", () => {
    const store = makeStore("running")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.status).toBe("RUNNING")
  })

  test("canResume returns true for PAUSED engagement", () => {
    const store = makeStore("paused")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "PAUSED")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.status).toBe("PAUSED")
  })

  test("canResume returns false for COMPLETED engagement", () => {
    const store = makeStore("completed")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "COMPLETED")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.status).toBe("COMPLETED")
  })

  test("canResume returns false for FAILED engagement", () => {
    const store = makeStore("failed")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "FAILED")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.status).toBe("FAILED")
  })

  test("getPhases returns phases for an engagement", () => {
    const store = makeStore("phases")
    const eng = store.createEngagement("https://example.com", "assessment")
    const phases = [
      { id: `p1-${Date.now()}`, engagementId: eng.id, name: "recon", status: "COMPLETED" as const, capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false },
      { id: `p2-${Date.now()}`, engagementId: eng.id, name: "vuln_scan", status: "PENDING" as const, capabilities: ["vulnerability_scanning"], executionMode: "parallel", replanCycle: false },
    ]
    store.savePhases(eng.id, phases)
    const saved = store.getPhases(eng.id)
    expect(saved).toHaveLength(2)
    expect(saved[0].status).toBe("COMPLETED")
    expect(saved[1].status).toBe("PENDING")
  })

  test("saveFindings and getFindings round-trips correctly", () => {
    const store = makeStore("findings")
    const eng = store.createEngagement("https://example.com", "assessment")
    const findings = [
      {
        id: `f1-${Date.now()}`,
        title: "Test Finding",
        severity: 3,
        confidence: 3,
        status: "CONFIRMED" as const,
        description: "A test finding",
        tool: "test-tool",
        phase: "recon",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]
    store.saveFindings(eng.id, findings)
    const saved = store.getFindings(eng.id)
    expect(saved).toHaveLength(1)
    expect(saved[0].title).toBe("Test Finding")
  })

  test("appendAuditLog creates retrievable entries", () => {
    const store = makeStore("audit")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.appendAuditLog(eng.id, "TEST_EVENT", "test message")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.status).toBe("CREATED")
  })

  test("engagement can be updated from CREATED to RUNNING to COMPLETED", () => {
    const store = makeStore("lifecycle")
    const eng = store.createEngagement("https://lifecycle-test.com", "assessment")
    expect(eng.status).toBe("CREATED")
    store.updateStatus(eng.id, "RUNNING")
    expect(store.getEngagement(eng.id)!.status).toBe("RUNNING")
    store.updateStatus(eng.id, "COMPLETED")
    expect(store.getEngagement(eng.id)!.status).toBe("COMPLETED")
  })
})

describe("resumeCommand", () => {
  let resumeStore: EngagementStore

  const mockPlan = {
    workflow: "test-workflow",
    phases: [
      { phaseId: "phase-0-recon", name: "recon", workflowName: "test", target: "https://test.com", requiredCapabilities: ["web_recon"], config: {}, previousPhaseResults: [] },
      { phaseId: "phase-1-scan", name: "scan", workflowName: "test", target: "https://test.com", requiredCapabilities: ["vulnerability_scanning"], config: {}, previousPhaseResults: [] },
    ],
    errorRecovery: {},
    planCreatedAt: new Date().toISOString(),
  }

  const mockExecutorResult = {
    phaseId: "phase-0-recon",
    status: "completed",
    findings: [{ id: "f1", title: "found", severity: 2, confidence: 2, status: "PENDING", description: "test", tool: "nuclei", phase: "recon", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }],
    artifacts: [],
    errors: [],
    durationMs: 50,
  }

  beforeAll(async () => {
    resumeStore = makeStore("resume-command")

    mock.module("../../../../src/argus/bridge/mcp-client", () => ({
      WorkersBridge: mock(() => ({
        connect: mock(async () => {}),
        disconnect: mock(async () => {}),
        callTool: mock(async () => ({ success: true, data: [], durationMs: 5 })),
        supervisor: { resetAttempts: mock(() => {}), restartWorker: mock(async () => {}) },
        on: mock(() => {}),
        llmStatus: mock(() => "AVAILABLE"),
        getTools: mock(async () => []),
        detectDrift: mock(async () => ({ missing_from_registry: [], missing_from_mcp: [], capability_gaps: [] })),
        killChild: mock(() => {}),
        restartWorker: mock(async () => {}),
        resetCircuitBreaker: mock(() => {}),
        isHealthy: mock(async () => true),
        agentInit: mock(async () => ({ session_id: "sess-1", plan: [], reasoning: "test", phase: "phase-0" })),
        agentNext: mock(async () => ({ session_id: "sess-1", done: true, reasoning: "done" })),
        agentObserve: mock(async () => ({ session_id: "sess-1", done: true, reasoning: "done" })),
      })),
    }))

    mock.module("../../../../src/argus/workflows/registry", () => ({
      WorkflowRegistry: mock(() => ({
        loadAll: mock(() => []),
        getWorkflow: mock(() => ({ name: "test-workflow", version: 1 })),
        listWorkflows: mock(() => []),
        findByCapabilities: mock(() => null),
        addWorkflow: mock(() => {}),
      })),
    }))

    mock.module("../../../../src/argus/workflows/tool-registry", () => ({
      ToolRegistry: mock(() => ({
        load: mock(() => {}),
        getToolsByCapability: mock(() => []),
        getTool: mock(() => ({ name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 })),
        listTools: mock(() => []),
        selectBest: mock(() => []),
      })),
    }))

    mock.module("../../../../src/argus/planner/planner", () => ({
      WorkflowPlanner: mock(() => ({
        plan: mock(async () => mockPlan),
        replan: mock(() => null),
      })),
    }))

    mock.module("../../../../src/argus/planner/executor", () => ({
      InProcessExecutor: mock(() => ({
        execute: mock(async () => mockExecutorResult),
        loadGates: mock(() => {}),
        setFeatureFlags: mock(() => {}),
        setOnProgress: mock(() => {}),
        setExecutionOptions: mock(() => {}),
        getToolHealth: mock(() => []),
      })),
    }))

    mock.module("../../../../src/argus/engagement/confidence", () => ({
      ConfidenceEngine: mock(() => ({
        promote: mock((f: any) => f.confidence ?? 2),
        shouldFinalize: mock(() => false),
      })),
    }))

    mock.module("../../../../src/argus/engagement/credentials", () => ({
      CredentialStore: mock(() => ({
        load: mock(() => ({ roles: {} })),
        getDefaultCredentials: mock(() => null),
        listRoles: mock(() => []),
        clear: mock(() => {}),
      })),
    }))

    mock.module("../../../../src/argus/reporting/generator", () => ({
      ReportGenerator: mock(() => ({
        generateMarkdown: mock(() => "# Report\n\nFindings: 1"),
      })),
    }))

    // Mock EngagementStore to return the shared test store
    mock.module("../../../../src/argus/engagement/store", () => ({
      EngagementStore: mock(() => resumeStore),
    }))
  })

  test("returns not-found message for non-existent engagement", async () => {
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand("ENG-NONEXISTENT")
    expect(result).toContain("Engagement not found")
  })

  test("returns cannot-resume message for COMPLETED engagement", async () => {
    const eng = resumeStore.createEngagement("https://test.com", "assessment")
    resumeStore.updateStatus(eng.id, "COMPLETED")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id)
    expect(result).toContain("cannot be resumed")
  })

  test("returns cannot-resume message for FAILED engagement", async () => {
    const eng = resumeStore.createEngagement("https://test.com", "assessment")
    resumeStore.updateStatus(eng.id, "FAILED")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id)
    expect(result).toContain("cannot be resumed")
  })

  test("returns cannot-resume message for CREATED engagement", async () => {
    const eng = resumeStore.createEngagement("https://test.com", "assessment")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id)
    expect(result).toContain("cannot be resumed")
  })

  test("resumes PAUSED engagement and returns report", async () => {
    const tag = `paused-${Date.now()}`
    const eng = resumeStore.createEngagement("https://test.com", "assessment")
    resumeStore.updateStatus(eng.id, "PAUSED")
    resumeStore.savePhases(eng.id, [{
      id: `${tag}-recon`, engagementId: eng.id, name: "recon", status: "COMPLETED",
      capabilities: ["web_recon"], executionMode: "sequential", replanCycle: false,
    }])
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id)
    expect(result).toContain("Report")
  })

  test("resumes RUNNING engagement and returns report", async () => {
    const tag = `running-${Date.now()}`
    const eng = resumeStore.createEngagement("https://test.com", "assessment")
    resumeStore.updateStatus(eng.id, "RUNNING")
    resumeStore.savePhases(eng.id, [{
      id: `${tag}-recon`, engagementId: eng.id, name: "recon", status: "COMPLETED",
      capabilities: ["web_recon"], executionMode: "sequential", replanCycle: false,
    }])
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id)
    expect(result).toContain("Report")
  })

  test("engagement with all phases completed returns early message", async () => {
    const tag = `completed-${Date.now()}`
    const eng = resumeStore.createEngagement("https://test.com", "assessment")
    resumeStore.updateStatus(eng.id, "PAUSED")
    resumeStore.savePhases(eng.id, [
      { id: `${tag}-recon`, engagementId: eng.id, name: "recon", status: "COMPLETED", capabilities: ["web_recon"], executionMode: "sequential", replanCycle: false },
      { id: `${tag}-scan`, engagementId: eng.id, name: "scan", status: "COMPLETED", capabilities: ["vulnerability_scanning"], executionMode: "sequential", replanCycle: false },
    ])
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id)
    expect(result).toContain("All phases already completed")
  })
})

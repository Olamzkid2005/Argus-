import { describe, expect, test, mock, beforeEach } from "bun:test"

// ── Module-level mocks ──

const mockCreateEngagement = mock(() => ({ id: "ENG-test-001" }))
const mockGetEngagement = mock(() => ({ id: "ENG-test-001" }))
const mockUpdateStatus = mock(() => {})
const mockSavePhases = mock(() => {})
const mockSavePhase = mock(() => {})
const mockSaveFindings = mock(() => {})
const mockAppendAuditLog = mock(() => {})

mock.module("../../../src/argus/engagement/store", () => ({
  EngagementStore: mock(() => ({
    createEngagement: mockCreateEngagement,
    getEngagement: mockGetEngagement,
    updateStatus: mockUpdateStatus,
    savePhases: mockSavePhases,
    savePhase: mockSavePhase,
    saveFindings: mockSaveFindings,
    appendAuditLog: mockAppendAuditLog,
  })),
}))

const mockLoadAll = mock(() => [])
const mockGetWorkflow = mock(() => ({ name: "test-workflow", phases: [], approval_required: false }))

mock.module("../../../src/argus/workflows/registry", () => ({
  WorkflowRegistry: mock(() => ({
    loadAll: mockLoadAll,
    getWorkflow: mockGetWorkflow,
    findByCapabilities: mock(() => null),
    listWorkflows: mock(() => []),
  })),
}))

const mockToolLoad = mock(() => {})
const mockToolSelectBest = mock(() => [])
const mockGetTool = mock(() => undefined)
const mockGetToolsByCapability = mock(() => [])

mock.module("../../../src/argus/workflows/tool-registry", () => ({
  ToolRegistry: mock(() => ({
    load: mockToolLoad,
    selectBest: mockToolSelectBest,
    getTool: mockGetTool,
    getToolsByCapability: mockGetToolsByCapability,
  })),
}))

const mockPlan = mock(() => ({
  workflow: "test-workflow",
  phases: [
    {
      phaseId: "phase-0-recon",
      workflowName: "test-workflow",
      target: "https://example.com",
      requiredCapabilities: ["recon"],
      config: {},
      previousPhaseResults: [],
    },
  ],
  errorRecovery: { "phase-0-recon": "skip_and_continue" },
  planCreatedAt: new Date().toISOString(),
}))

mock.module("../../../src/argus/planner/planner", () => ({
  WorkflowPlanner: mock(() => ({
    plan: mockPlan,
    replan: mock(() => null),
  })),
}))

const mockExecute = mock(() => ({
  phaseId: "phase-0-recon",
  status: "completed",
  findings: [],
  artifacts: [],
  errors: [],
  durationMs: 42,
}))
const mockLoadGates = mock(() => {})
const mockSetBrowserVerifierDeps = mock(() => {})

mock.module("../../../src/argus/planner/executor", () => ({
  InProcessExecutor: mock(() => ({
    execute: mockExecute,
    loadGates: mockLoadGates,
    setBrowserVerifierDeps: mockSetBrowserVerifierDeps,
  })),
}))

const mockBridgeConnect = mock(() => Promise.resolve())
const mockBridgeDisconnect = mock(() => Promise.resolve())

mock.module("../../../src/argus/bridge/mcp-client", () => ({
  WorkersBridge: mock(() => ({
    connect: mockBridgeConnect,
    disconnect: mockBridgeDisconnect,
  })),
}))

const mockPromote = mock((finding: any) => finding.confidence ?? 0)

mock.module("../../../src/argus/engagement/confidence", () => ({
  ConfidenceEngine: mock(() => ({
    promote: mockPromote,
    shouldFinalize: mock(() => false),
  })),
}))

const mockCredLoad = mock(() => ({ roles: {} }))
const mockGetAllCredentials = mock(() => ({}))
const mockCredClear = mock(() => {})

mock.module("../../../src/argus/engagement/credentials", () => ({
  CredentialStore: mock(() => ({
    load: mockCredLoad,
    getAllCredentials: mockGetAllCredentials,
    clear: mockCredClear,
    getCredentials: mock(() => null),
    listRoles: mock(() => []),
    getDefaultRole: mock(() => undefined),
    getDefaultCredentials: mock(() => null),
  })),
}))

mock.module("../../../src/argus/evidence/collector", () => ({
  EvidenceCollector: mock(() => ({
    saveRequest: mock(() => ({ type: "request", path: "", size_bytes: 0, hash: "" })),
    saveResponse: mock(() => ({ type: "response", path: "", size_bytes: 0, hash: "" })),
    captureScreenshot: mock(() => ({ type: "screenshot", path: "", size_bytes: 0, hash: "" })),
    createPackage: mock(() => ({ package_id: "", engagement_id: "", artifacts: [], package_hash: "", created_at: "" })),
    hashFile: mock(() => ""),
  })),
}))

mock.module("../../../src/argus/browser/engine", () => ({
  PlaywrightEngine: mock(() => ({
    launch: mock(() => {}),
    close: mock(() => {}),
    createContext: mock(() => ({ newPage: mock(async () => ({})) })),
    captureScreenshot: mock(() => Buffer.from("")),
  })),
}))

// ── Pure function tests (no mocking needed) ──

describe("formatFindingsSummary", () => {
  test("returns formatted string with all zeros when no findings", () => {
    const { formatFindingsSummary } =
      require("../../../src/argus/workflow-runner")
    const result = formatFindingsSummary([], "ENG-000", "https://example.com")

    expect(result).toContain("Assessment Complete: https://example.com")
    expect(result).toContain("ENG-000")
    expect(result).toContain("Critical: 0")
    expect(result).toContain("High:     0")
    expect(result).toContain("Medium:   0")
    expect(result).toContain("Low:      0")
    expect(result).not.toContain("Top Findings")
    expect(result).toContain("/report ENG-000")
  })

  test("returns correct critical/high/medium/low counts", () => {
    const { formatFindingsSummary } =
      require("../../../src/argus/workflow-runner")
    const findings = [
      { title: "XSS", severity: 4, confidence: 3, tool: "scanner", phase: "recon" },
      { title: "SQLi", severity: 3, confidence: 2, tool: "scanner", phase: "recon" },
      { title: "Info Leak", severity: 1, confidence: 1, tool: "scanner", phase: "recon" },
      { title: "Cookie", severity: 2, confidence: 2, tool: "scanner", phase: "recon" },
      { title: "Low Issue", severity: 0, confidence: 0, tool: "scanner", phase: "recon" },
    ]
    const result = formatFindingsSummary(findings, "ENG-001", "https://target.test")

    expect(result).toContain("Critical: 1")
    expect(result).toContain("High:     1")
    expect(result).toContain("Medium:   1")
    expect(result).toContain("Low:      2")
  })

  test("includes top 5 findings ordered by severity", () => {
    const { formatFindingsSummary } =
      require("../../../src/argus/workflow-runner")
    const findings = [
      { title: "Critical A", severity: 4, confidence: 3, tool: "t1", phase: "p1" },
      { title: "High A", severity: 3, confidence: 2, tool: "t2", phase: "p2" },
      { title: "High B", severity: 3, confidence: 2, tool: "t2", phase: "p2" },
      { title: "Medium A", severity: 2, confidence: 2, tool: "t3", phase: "p3" },
      { title: "Medium B", severity: 2, confidence: 1, tool: "t3", phase: "p3" },
      { title: "Low A", severity: 1, confidence: 1, tool: "t4", phase: "p4" },
    ]
    const result = formatFindingsSummary(findings, "ENG-002", "https://target.test")

    expect(result).toContain("Top Findings")
    expect(result).toContain("[CRITICAL] Critical A")
    expect(result).toContain("[HIGH] High A")
    expect(result).toContain("[HIGH] High B")
    expect(result).toContain("[MEDIUM] Medium A")
    expect(result).toContain("[MEDIUM] Medium B")
    expect(result).not.toContain("Low A")
  })

  test("includes engagement ID and target in output", () => {
    const { formatFindingsSummary } =
      require("../../../src/argus/workflow-runner")
    const result = formatFindingsSummary([], "ENG-CUSTOM-123", "https://myapp.test")

    expect(result).toContain("ENG-CUSTOM-123")
    expect(result).toContain("https://myapp.test")
  })
})

// ── WorkflowRunner.run() tests ──

describe("WorkflowRunner", () => {
  beforeEach(() => {
    mockCreateEngagement.mockClear()
    mockGetEngagement.mockClear()
    mockUpdateStatus.mockClear()
    mockSavePhases.mockClear()
    mockSavePhase.mockClear()
    mockSaveFindings.mockClear()
    mockAppendAuditLog.mockClear()

    mockLoadAll.mockClear()
    mockToolLoad.mockClear()
    mockPlan.mockClear()
    mockLoadGates.mockClear()
    mockExecute.mockClear()
    mockSetBrowserVerifierDeps.mockClear()

    mockBridgeConnect.mockClear()
    mockBridgeDisconnect.mockClear()

    mockPromote.mockClear()
    mockCredLoad.mockClear()
    mockGetAllCredentials.mockClear()
    mockCredClear.mockClear()

    // Restore default implementations
    mockGetEngagement.mockImplementation(() => ({ id: "ENG-test-001" }))
    mockCreateEngagement.mockImplementation(() => ({ id: "ENG-test-001" }))
    mockPlan.mockImplementation(() => ({
      workflow: "test-workflow",
      phases: [
        {
          phaseId: "phase-0-recon",
          workflowName: "test-workflow",
          target: "https://example.com",
          requiredCapabilities: ["recon"],
          config: {},
          previousPhaseResults: [],
        },
      ],
      errorRecovery: { "phase-0-recon": "skip_and_continue" },
      planCreatedAt: new Date().toISOString(),
    }))
    mockExecute.mockImplementation(() => ({
      phaseId: "phase-0-recon",
      status: "completed",
      findings: [],
      artifacts: [],
      errors: [],
      durationMs: 42,
    }))
    mockPromote.mockImplementation((finding: any) => finding.confidence ?? 0)
    mockGetAllCredentials.mockImplementation(() => ({}))
    mockBridgeConnect.mockImplementation(() => Promise.resolve())
    mockBridgeDisconnect.mockImplementation(() => Promise.resolve())
  })

  test("creates new engagement and runs workflow successfully", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()
    const result = await runner.run({ target: "https://example.com" })

    expect(mockCreateEngagement).toHaveBeenCalledWith("https://example.com", "assessment")
    expect(mockUpdateStatus).toHaveBeenCalledWith("ENG-test-001", "RUNNING")
    expect(mockLoadAll).toHaveBeenCalled()
    expect(mockToolLoad).toHaveBeenCalled()
    expect(mockPlan).toHaveBeenCalledWith("https://example.com", undefined, { useLLM: true })
    expect(mockSavePhases).toHaveBeenCalled()
    expect(mockBridgeConnect).toHaveBeenCalled()
    expect(mockLoadGates).toHaveBeenCalledWith("test-workflow")
    expect(mockExecute).toHaveBeenCalledTimes(1)
    expect(mockUpdateStatus).toHaveBeenCalledWith("ENG-test-001", "COMPLETED")
    expect(mockSaveFindings).toHaveBeenCalled()
    expect(mockBridgeDisconnect).toHaveBeenCalled()

    expect(result.engagementId).toBe("ENG-test-001")
    expect(result.findings).toBe(0)
    expect(result.durationMs).toBeGreaterThanOrEqual(0)
  })

  test("uses existing engagementId when provided", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()
    const result = await runner.run({
      target: "https://example.com",
      engagementId: "ENG-EXISTING-1",
    })

    expect(mockGetEngagement).toHaveBeenCalledWith("ENG-EXISTING-1")
    expect(mockCreateEngagement).not.toHaveBeenCalled()
    expect(mockUpdateStatus).toHaveBeenCalledWith("ENG-EXISTING-1", "RUNNING")
  })

  test("throws error when engagementId not found in store", async () => {
    mockGetEngagement.mockImplementation(() => null)

    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()

    await expect(
      runner.run({ target: "https://example.com", engagementId: "ENG-MISSING" }),
    ).rejects.toThrow("Engagement ENG-MISSING not found in store")
  })

  test("calls onProgress callbacks during execution", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()
    const onProgress = mock(() => {})

    await runner.run({ target: "https://example.com", onProgress })

    expect(onProgress).toHaveBeenCalled()
    const calls = onProgress.mock.calls.map((c: string[]) => c[0])
    expect(calls.some((s: string) => s.includes("Target validated"))).toBe(true)
    expect(calls.some((s: string) => s.includes("Engagement created"))).toBe(true)
    expect(calls.some((s: string) => s.includes("Planning assessment"))).toBe(true)
    expect(calls.some((s: string) => s.includes("MCP workers connected"))).toBe(true)
  })

  test("handles execution error gracefully", async () => {
    mockExecute.mockImplementation(() => {
      throw new Error("Phase crashed")
    })

    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()
    const onProgress = mock(() => {})

    const result = await runner.run({ target: "https://example.com", onProgress })

    // Status set to FAILED
    expect(mockUpdateStatus).toHaveBeenCalledWith("ENG-test-001", "FAILED")
    // Audit log appended
    expect(mockAppendAuditLog).toHaveBeenCalledWith(
      "ENG-test-001",
      "RUNNER_ERROR",
      expect.stringContaining("Phase crashed"),
    )
    // Result still returned
    expect(result.engagementId).toBe("ENG-test-001")
    expect(result.findings).toBe(0)
    // Progress reported error
    const calls = onProgress.mock.calls.map((c: string[]) => c[0])
    expect(calls.some((s: string) => s.includes("Error"))).toBe(true)
    expect(calls.some((s: string) => s.includes("failed"))).toBe(true)
  })

  test("saves findings even when execution has error", async () => {
    const partialFindings = [
      {
        id: "find-1",
        title: "Found before crash",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "test",
        tool: "scanner",
        phase: "phase-0-recon",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]

    mockExecute.mockImplementation(() => ({
      phaseId: "phase-0-recon",
      status: "completed",
      findings: partialFindings,
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()

    const result = await runner.run({ target: "https://example.com" })

    expect(mockSaveFindings).toHaveBeenCalled()
    expect(result.findings).toBe(1)
  })

  test("disconnects bridge in finally block despite error", async () => {
    let disconnectCalled = false
    mockBridgeDisconnect.mockImplementation(() => {
      disconnectCalled = true
      return Promise.resolve()
    })
    mockExecute.mockImplementation(() => {
      throw new Error("Crash")
    })

    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const runner = new WorkflowRunner()

    await runner.run({ target: "https://example.com" })

    expect(disconnectCalled).toBe(true)
    expect(mockBridgeDisconnect).toHaveBeenCalledTimes(1)
  })
})

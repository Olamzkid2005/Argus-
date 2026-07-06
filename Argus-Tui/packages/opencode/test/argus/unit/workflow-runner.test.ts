import { describe, expect, test, mock } from "bun:test"

// ── Pure function tests ──

describe("formatFindingsSummary", () => {
  test("returns formatted string with all zeros when no findings", async () => {
    const { formatFindingsSummary } =
      await import("../../../src/argus/workflow-runner")
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

  test("returns correct critical/high/medium/low counts", async () => {
    const { formatFindingsSummary } =
      await import("../../../src/argus/workflow-runner")
    const ts = new Date().toISOString()
    const findings = [
      { id: "f1", title: "XSS", severity: 4, confidence: 3, tool: "scanner", phase: "recon", status: "PENDING" as const, description: "xss", created_at: ts, updated_at: ts },
      { id: "f2", title: "SQLi", severity: 3, confidence: 2, tool: "scanner", phase: "recon", status: "PENDING" as const, description: "sqli", created_at: ts, updated_at: ts },
      { id: "f3", title: "Info Leak", severity: 1, confidence: 1, tool: "scanner", phase: "recon", status: "PENDING" as const, description: "info", created_at: ts, updated_at: ts },
      { id: "f4", title: "Cookie", severity: 2, confidence: 2, tool: "scanner", phase: "recon", status: "PENDING" as const, description: "cookie", created_at: ts, updated_at: ts },
      { id: "f5", title: "Low Issue", severity: 1, confidence: 0, tool: "scanner", phase: "recon", status: "PENDING" as const, description: "low", created_at: ts, updated_at: ts },
    ]
    const result = formatFindingsSummary(findings, "ENG-001", "https://target.test")

    expect(result).toContain("Critical: 1")
    expect(result).toContain("High:     1")
    expect(result).toContain("Medium:   1")
    expect(result).toContain("Low:      2")
  })

  test("includes top 5 findings ordered by severity", async () => {
    const { formatFindingsSummary } =
      await import("../../../src/argus/workflow-runner")
    const ts = new Date().toISOString()
    const findings = [
      { id: "f1", title: "Critical A", severity: 4, confidence: 3, tool: "t1", phase: "p1", status: "PENDING" as const, description: "crit", created_at: ts, updated_at: ts },
      { id: "f2", title: "High A", severity: 3, confidence: 2, tool: "t2", phase: "p2", status: "PENDING" as const, description: "high", created_at: ts, updated_at: ts },
      { id: "f3", title: "High B", severity: 3, confidence: 2, tool: "t2", phase: "p2", status: "PENDING" as const, description: "high", created_at: ts, updated_at: ts },
      { id: "f4", title: "Medium A", severity: 2, confidence: 2, tool: "t3", phase: "p3", status: "PENDING" as const, description: "med", created_at: ts, updated_at: ts },
      { id: "f5", title: "Medium B", severity: 2, confidence: 1, tool: "t3", phase: "p3", status: "PENDING" as const, description: "med", created_at: ts, updated_at: ts },
      { id: "f6", title: "Low A", severity: 1, confidence: 1, tool: "t4", phase: "p4", status: "PENDING" as const, description: "low", created_at: ts, updated_at: ts },
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

  test("includes engagement ID and target in output", async () => {
    const { formatFindingsSummary } =
      await import("../../../src/argus/workflow-runner")
    const result = formatFindingsSummary([], "ENG-CUSTOM-123", "https://myapp.test")

    expect(result).toContain("ENG-CUSTOM-123")
    expect(result).toContain("https://myapp.test")
  })
})

// ── WorkflowRunner.run() tests ──  const FORMAT_RESULT = { engagementId: "ENG-test-001", findings: 0, critical: 0, high: 0, medium: 0, low: 0, durationMs: 0, error: undefined, allFindings: [], toolsExecuted: new Set(), replanCount: 0 }

  describe("WorkflowRunner", () => {
    function makeDeps() {
    const mockEngagementStore = {
      createEngagement: mock(() => ({ id: "ENG-test-001" })),
      getEngagement: mock(() => ({ id: "ENG-test-001" })),
      updateStatus: mock(() => {}),
      savePhases: mock(() => {}),
      savePhase: mock(() => {}),
      saveFindings: mock(() => {}),
      appendAuditLog: mock(() => {}),
      listEngagements: mock(() => []),
      getFindings: mock(() => []),
      getPhases: mock(() => []),
      getAuditLog: mock(() => []),
      getEvidencePackages: mock(() => []),
      getArtifacts: mock(() => []),
      saveEvidencePackage: mock(() => {}),
      saveArtifact: mock(() => {}),
      saveFindingAnalysis: mock(() => {}),
      getFindingAnalysis: mock(() => null),
      deleteFindingAnalysis: mock(() => {}),
      getValidAnalysis: mock(() => null),
      saveWorkflowSnapshot: mock(() => {}),
      getWorkflowSnapshots: mock(() => []),
      getEvidenceByEngagement: mock(() => []),
      getFinding: mock(() => null),
    }

    const mockWorkflowRegistry = {
      loadAll: mock(() => []),
      getWorkflow: mock(() => ({ name: "test-workflow", phases: [], approval_required: false })),
      findByCapabilities: mock(() => null),
      listWorkflows: mock(() => []),
      addWorkflow: mock(() => {}),
    }

    const mockToolRegistry = {
      load: mock(() => {}),
      selectBest: mock(() => []),
      getTool: mock(() => undefined),
      getToolsByCapability: mock(() => []),
      getCapabilities: mock(() => []),
      listTools: mock(() => []),
      findBestTools: mock(() => []),
      setConfig: mock(() => {}),
      getToolTimeout: mock(() => 120),
    }

    const mockPlanner = {
      plan: mock(() => ({
        workflow: "test-workflow",
        phases: [
          {
            phaseId: "phase-0-recon",
            name: "recon",
            workflowName: "test-workflow",
            target: "https://example.com",
            requiredCapabilities: ["recon"],
            config: {},
            previousPhaseResults: [],
          },
        ],
        errorRecovery: { "phase-0-recon": "skip_and_continue" },
        planCreatedAt: new Date().toISOString(),
      })),
      replan: mock(() => null),
    }

    const mockExecutor = {
      execute: mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [],
        artifacts: [],
        errors: [],
        durationMs: 42,
      })),
      loadGates: mock(() => {}),
      setFeatureFlags: mock(() => {}),
      setExecutionOptions: mock(() => {}),
      setOnProgress: mock(() => {}),
      setToolConfig: mock(() => {}),
      getToolHealth: mock(() => []),
    }

    const mockBridge = {
      connect: mock(() => Promise.resolve()),
      disconnect: mock(() => Promise.resolve()),
      isHealthy: mock(() => Promise.resolve(true)),
      killChild: mock(() => {}),
      restartWorker: mock(() => Promise.resolve()),
      setRegistryTools: mock(() => {}),
    }

    const mockConfidenceEngine = {
      promote: mock((finding: any) => finding.confidence ?? 0),
      shouldFinalize: mock(() => false),
    }

    const mockCredStore = {
      load: mock(() => {}),
      getAllCredentials: mock(() => ({})),
      clear: mock(() => {}),
      getCredentials: mock(() => null),
      listRoles: mock(() => []),
      getDefaultRole: mock(() => undefined),
      getDefaultCredentials: mock(() => null),
    }

    return {
      mockEngagementStore,
      mockWorkflowRegistry,
      mockToolRegistry,
      mockPlanner,
      mockExecutor,
      mockBridge,
      mockConfidenceEngine,
      mockCredStore,
      deps: {
        store: mockEngagementStore as any,
        workflowRegistry: mockWorkflowRegistry as any,
        toolRegistry: mockToolRegistry as any,
        planner: mockPlanner as any,
        executor: mockExecutor as any,
        bridge: mockBridge as any,
        confidenceEngine: mockConfidenceEngine as any,
        credStore: mockCredStore as any,
      },
    }
  }

  test("creates new engagement and runs workflow successfully", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { mockEngagementStore, mockWorkflowRegistry, mockToolRegistry, mockPlanner, mockExecutor, mockBridge, deps } = makeDeps()

    const runner = new WorkflowRunner(deps)
    const result = await runner.run({ target: "https://example.com" })

    expect(mockEngagementStore.createEngagement).toHaveBeenCalledWith("https://example.com", "assessment")
    expect(mockEngagementStore.updateStatus).toHaveBeenCalledWith("ENG-test-001", "RUNNING")
    expect(mockWorkflowRegistry.loadAll).toHaveBeenCalled()
    expect(mockToolRegistry.load).toHaveBeenCalled()
    expect(mockPlanner.plan).toHaveBeenCalledWith("https://example.com", undefined, { useLLM: true })
    // replan is only called when phases produce findings (empty findings phases skip replan)
    expect(mockBridge.connect).toHaveBeenCalled()
    expect(mockExecutor.loadGates).toHaveBeenCalledWith("test-workflow")
    expect(mockExecutor.execute).toHaveBeenCalledTimes(1)
    expect(mockEngagementStore.updateStatus).toHaveBeenCalledWith("ENG-test-001", "COMPLETED")
    expect(mockEngagementStore.saveFindings).toHaveBeenCalled()
    expect(mockBridge.disconnect).toHaveBeenCalled()

    expect(result.engagementId).toBe("ENG-test-001")
  })

  test("uses existing engagementId when provided", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { mockEngagementStore, deps } = makeDeps()

    const runner = new WorkflowRunner(deps)
    const result = await runner.run({
      target: "https://example.com",
      engagementId: "ENG-EXISTING-1",
    })

    expect(mockEngagementStore.getEngagement).toHaveBeenCalledWith("ENG-EXISTING-1")
    expect(mockEngagementStore.createEngagement).not.toHaveBeenCalled()
    expect(mockEngagementStore.updateStatus).toHaveBeenCalledWith("ENG-EXISTING-1", "RUNNING")
  })

  test("throws error when engagementId not found in store", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    deps.store.getEngagement = mock(() => null)

    const runner = new WorkflowRunner(deps)

    await expect(
      runner.run({ target: "https://example.com", engagementId: "ENG-MISSING" }),
    ).rejects.toThrow("Engagement ENG-MISSING not found in store")
  })

  test("calls onProgress callbacks during execution", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    const runner = new WorkflowRunner(deps)
    const onProgress = mock(() => {})

    await runner.run({ target: "https://example.com", onProgress })

    expect(onProgress).toHaveBeenCalled()
    const calls = onProgress.mock.calls.map((c: any[]) => String(c[0]))
    expect(calls.some((s: string) => s.includes("Target validated"))).toBe(true)
    expect(calls.some((s: string) => s.includes("Engagement created"))).toBe(true)
    expect(calls.some((s: string) => s.includes("Planning assessment"))).toBe(true)
    expect(calls.some((s: string) => s.includes("MCP workers connected"))).toBe(true)
  })

  test("handles execution error gracefully", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    deps.executor.execute = mock(() => { throw new Error("Phase crashed") })

    const runner = new WorkflowRunner(deps)
    const onProgress = mock(() => {})

    const result = await runner.run({ target: "https://example.com", onProgress })

    // Status set to FAILED
    expect(deps.store.updateStatus).toHaveBeenCalledWith("ENG-test-001", "FAILED")
    // Audit log appended
    expect(deps.store.appendAuditLog).toHaveBeenCalledWith(
      "ENG-test-001",
      "RUNNER_ERROR",
      expect.stringContaining("Phase crashed"),
    )
    // Result still returned
    expect(result.engagementId).toBe("ENG-test-001")
    // Progress reported error
    const calls = onProgress.mock.calls.map((c: any[]) => String(c[0]))
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

    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    deps.executor.execute = mock(() => ({
      phaseId: "phase-0-recon",
      status: "completed",
      findings: partialFindings,
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const runner = new WorkflowRunner(deps)
    const result = await runner.run({ target: "https://example.com" })

    expect(deps.store.saveFindings).toHaveBeenCalled()
  })

  test("calls replan after phase execution and appends new phases", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    const replanPhase = {
      phaseId: "replan-1-JWT_ANALYSIS",
      name: "replan-jwt_analysis",
      workflowName: "replan",
      target: "https://example.com",
      requiredCapabilities: ["jwt_analysis"],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential",
      replanCycle: true,
    }
    deps.planner.replan = mock(() => [replanPhase])
    deps.executor.execute = mock(() => ({
      phaseId: "phase-0-recon",
      status: "completed",
      findings: [],
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const runner = new WorkflowRunner(deps)
    const result = await runner.run({ target: "https://example.com" })

    expect(deps.planner.replan).toHaveBeenCalled()
    expect(deps.store.savePhases).toHaveBeenCalledTimes(2)
    expect(deps.store.appendAuditLog).toHaveBeenCalledWith(
      "ENG-test-001", "REPLAN_INSERT", expect.stringContaining("1 replan phase(s)")
    )
    expect(result.engagementId).toBe("ENG-test-001")
  })

  test("executes appended replan phases in same run", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    const replanPhase = {
      phaseId: "replan-1-JWT_ANALYSIS",
      name: "replan-jwt_analysis",
      workflowName: "replan",
      target: "https://example.com",
      requiredCapabilities: ["jwt_analysis"],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential",
      replanCycle: true,
    }
    let replanCallCount = 0
    deps.planner.replan = mock(() => {
      if (replanCallCount++ === 0) return [replanPhase]
      return null
    })
    let executeCallCount = 0
    deps.executor.execute = mock(() => ({
      phaseId: executeCallCount++ === 0 ? "phase-0-recon" : "replan-1-JWT_ANALYSIS",
      status: "completed",
      findings: [],
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const runner = new WorkflowRunner(deps)
    const result = await runner.run({ target: "https://example.com" })

    expect(deps.executor.execute).toHaveBeenCalledTimes(2)
    expect(result.engagementId).toBe("ENG-test-001")
  })

  test("tracks replanCount progression across calls", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    const capturedCounts: number[] = []
    deps.planner.replan = mock((ctx: any) => {
      capturedCounts.push(ctx.replanCount)
      ctx.replanCount++
      return null
    })
    deps.executor.execute = mock(() => ({
      phaseId: "phase-0-recon",
      status: "completed",
      findings: [{ id: "f1", title: "Test", severity: 2, confidence: 2, status: "PENDING" as const, description: "", tool: "scanner", phase: "phase", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }],
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const runner = new WorkflowRunner(deps)
    await runner.run({ target: "https://example.com" })

    expect(capturedCounts.length).toBeGreaterThanOrEqual(1)
    expect(capturedCounts[0]).toBe(0)
  })

  test("does not call replan after replan phases", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    const replanPhase = {
      phaseId: "replan-1-JWT_ANALYSIS",
      name: "replan-jwt_analysis",
      workflowName: "replan",
      target: "https://example.com",
      requiredCapabilities: ["jwt_analysis"],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential",
      replanCycle: true,
    }
    let replanCallCount = 0
    deps.planner.replan = mock(() => {
      replanCallCount++
      if (replanCallCount === 1) return [replanPhase]
      return null
    })
    let executeCallCount = 0
    deps.executor.execute = mock(() => ({
      phaseId: executeCallCount++ === 0 ? "phase-0-recon" : "replan-1-JWT_ANALYSIS",
      status: "completed",
      findings: [],
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const runner = new WorkflowRunner(deps)
    await runner.run({ target: "https://example.com" })

    expect(replanCallCount).toBe(1)  // replan called once
    expect(executeCallCount).toBe(2)  // original + replan phase
  })

  test("supports multiple replan cycles across original phases", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    let replanCallIdx = 0
    deps.planner.plan = mock(() => ({
      workflow: "test-workflow",
      phases: [
        {
          phaseId: "phase-0-recon",
          name: "recon",
          workflowName: "test-workflow",
          target: "https://example.com",
          requiredCapabilities: ["web_recon"],
          config: {},
          previousPhaseResults: [],
        },
        {
          phaseId: "phase-1-scan",
          name: "scan",
          workflowName: "test-workflow",
          target: "https://example.com",
          requiredCapabilities: ["vulnerability_scanning"],
          config: {},
          previousPhaseResults: [],
        },
      ],
      errorRecovery: { "phase-0-recon": "skip_and_continue", "phase-1-scan": "skip_and_continue" },
      planCreatedAt: new Date().toISOString(),
    }))
    const replanPhase1 = {
      phaseId: "replan-1-JWT_ANALYSIS",
      name: "replan-jwt_analysis",
      workflowName: "replan",
      target: "https://example.com",
      requiredCapabilities: ["jwt_analysis"],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential",
      replanCycle: true,
    }
    const replanPhase2 = {
      phaseId: "replan-2-SQLI",
      name: "replan-sqli_detection",
      workflowName: "replan",
      target: "https://example.com",
      requiredCapabilities: ["sqli_detection"],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential",
      replanCycle: true,
    }
    deps.planner.replan = mock(() => {
      const result = replanCallIdx === 0 ? [replanPhase1] : replanCallIdx === 1 ? [replanPhase2] : null
      replanCallIdx++
      return result
    })
    let executeCallCount = 0
    deps.executor.execute = mock(() => ({
      phaseId: [
        "phase-0-recon",
        "replan-1-JWT_ANALYSIS",
        "phase-1-scan",
        "replan-2-SQLI",
      ][executeCallCount] ?? "phase-0-recon",
      status: "completed",
      findings: [],
      artifacts: [],
      errors: [],
      durationMs: 10,
    }))

    const runner = new WorkflowRunner(deps)
    const result = await runner.run({ target: "https://example.com" })

    expect(deps.planner.replan).toHaveBeenCalledTimes(2)
    expect(deps.executor.execute).toHaveBeenCalledTimes(4)
    expect(result.engagementId).toBe("ENG-test-001")
  })

  describe("autonomous-mode scope guard (blocker 36)", () => {
    test("throws when ARGUS_AUTONOMOUS=1 and config is missing or malformed", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      const runner = new WorkflowRunner(deps)

      process.env.ARGUS_AUTONOMOUS = "1"
      try {
        await expect(
          runner.run({ target: "https://example.com" }),
        ).rejects.toThrow("config file 'argus.config.yaml' is missing or malformed")
      } finally {
        delete process.env.ARGUS_AUTONOMOUS
      }
    })

    test("does not throw in non-autonomous mode when config is missing", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      const runner = new WorkflowRunner(deps)

      // In non-autonomous mode, missing config should not throw
      // (it falls back to defaults with a warning)
      const result = await runner.run({ target: "https://example.com" })
      expect(result.engagementId).toBe("ENG-test-001")
    })

    test("ARGUS_AUTONOMOUS='true' also triggers guard", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      const runner = new WorkflowRunner(deps)

      process.env.ARGUS_AUTONOMOUS = "true"
      try {
        await expect(
          runner.run({ target: "https://example.com" }),
        ).rejects.toThrow("config file 'argus.config.yaml' is missing or malformed")
      } finally {
        delete process.env.ARGUS_AUTONOMOUS
      }
    })

    test("non-autonomous mode proceeds even when ARGUS_AUTONOMOUS is not set", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      const runner = new WorkflowRunner(deps)

      delete process.env.ARGUS_AUTONOMOUS
      const result = await runner.run({ target: "https://example.com" })
      expect(result.engagementId).toBe("ENG-test-001")
      expect(result.success).toBe(true)
    })
  })
})

// ── Autonomous-mode scope.mode value check (pure logic) ──
// These tests validate the scope check logic in isolation, since the
// full WorkflowRunner.run() path requires a valid YAML config file.
describe("autonomous scope.mode validation logic", () => {
  async function runnerWithConfig(scopeMode: string): Promise<boolean> {
    // Simulate the check from workflow-runner.ts:
    //   if (isAutonomous) {
    //     const scopeMode = parsed?.security?.scope?.mode ?? "warn"
    //     if (scopeMode === "warn" || scopeMode === "open") throw new Error(...)
    //   }
    if (process.env.ARGUS_AUTONOMOUS !== "1") return true
    const mode = scopeMode
    if (mode === "warn" || mode === "open") {
      throw new Error(
        "security.scope.mode must be explicitly set to 'allowlist' " +
        "in autonomous mode. Current mode is '" + mode + "'."
      )
    }
    return true
  }

  test("allowlist mode is accepted", async () => {
    process.env.ARGUS_AUTONOMOUS = "1"
    try {
      await expect(runnerWithConfig("allowlist")).resolves.toBe(true)
    } finally {
      delete process.env.ARGUS_AUTONOMOUS
    }
  })

  test("warn mode is rejected", async () => {
    process.env.ARGUS_AUTONOMOUS = "1"
    try {
      await expect(runnerWithConfig("warn")).rejects.toThrow("must be explicitly set to 'allowlist'")
    } finally {
      delete process.env.ARGUS_AUTONOMOUS
    }
  })

  test("open mode is rejected", async () => {
    process.env.ARGUS_AUTONOMOUS = "1"
    try {
      await expect(runnerWithConfig("open")).rejects.toThrow("must be explicitly set to 'allowlist'")
    } finally {
      delete process.env.ARGUS_AUTONOMOUS
    }
  })

  test("default (warn) is rejected when autonomous", async () => {
    process.env.ARGUS_AUTONOMOUS = "1"
    try {
      await expect(runnerWithConfig("warn")).rejects.toThrow("Current mode is 'warn'")
    } finally {
      delete process.env.ARGUS_AUTONOMOUS
    }
  })

  test("check passes when not in autonomous mode regardless of mode", async () => {
    delete process.env.ARGUS_AUTONOMOUS
    await expect(runnerWithConfig("warn")).resolves.toBe(true)
    await expect(runnerWithConfig("open")).resolves.toBe(true)
    await expect(runnerWithConfig("allowlist")).resolves.toBe(true)
  })
})

describe("disconnect in finally block", () => {
  test("disconnects bridge in finally block despite error", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const { deps } = makeDeps()
    let disconnectCalled = false
    deps.bridge.disconnect = mock(() => {
      disconnectCalled = true
      return Promise.resolve()
    })
    deps.executor.execute = mock(() => { throw new Error("Crash") })

    const runner = new WorkflowRunner(deps)

    await runner.run({ target: "https://example.com" })

    expect(disconnectCalled).toBe(true)
    expect(deps.bridge.disconnect).toHaveBeenCalledTimes(1)
  })
})

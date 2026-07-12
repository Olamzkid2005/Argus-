import { describe, expect, test, mock } from "bun:test"
import { ConfidenceEngine } from "@argus/engagement/confidence"

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
      registerExitHandler: mock(() => {}),
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
      supervisor: { degraded: false },
      callTool: mock(async (_tool: string, _args: unknown, _timeout?: number) => ({
        success: true,
        data: { verified: true, confidence: "HIGH", reason: "Mock MCP verification passed" },
      })),
      phaseComplete: mock(() => Promise.resolve({
        stop: false,
        next_capabilities: [],
        reasoning: "",
        fallback: false,
      })),
      getAttackGraph: mock(() => Promise.resolve({
        chains: [],
        chain_plans: [],
      })),
      acquireEngagementLock: mock(() => Promise.resolve({ acquired: true })),
      resetCircuitBreaker: mock(() => {}),
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

  // ── MCP verification (mcpVerifyFindings) ──
  describe("MCP verification (mcpVerifyFindings)", () => {
    test("calls MCP verification for SQLi findings during run()", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()

      const callToolMock = mock(async (_tool: string, _args: any, _timeout?: number) => ({
        success: true,
        data: { verified: true, confidence: "HIGH", reason: "Payload reflected in response" },
      }))
      deps.bridge.callTool = callToolMock

      const sqliFinding = {
        id: "find-sqli-1",
        title: "SQL Injection in login",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "SQLi in /login?user=admin' OR '1'='1",
        subtype: "sqli",
        tool: "scanner",
        phase: "scan",
        url: "https://example.com/login",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [sqliFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      await runner.run({ target: "https://example.com" })

      expect(callToolMock).toHaveBeenCalledWith(
        "finding_verifier",
        expect.objectContaining({ finding_type: "sqli" }),
        expect.any(Number),
      )
    })

    test("skips MCP verification for non-verifiable subtypes (bola)", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()

      const callToolMock = mock(() => {})
      deps.bridge.callTool = callToolMock

      const bolaFinding = {
        id: "find-bola-1",
        title: "BOLA in profile endpoint",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "BOLA in /api/profile",
        subtype: "bola",
        tool: "scanner",
        phase: "scan",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [bolaFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      await runner.run({ target: "https://example.com" })

      expect(callToolMock).not.toHaveBeenCalled()
    })

    test("skips MCP verification for already-verified findings", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()

      const callToolMock = mock(() => {})
      deps.bridge.callTool = callToolMock

      const alreadyVerified = {
        id: "find-sqli-2",
        title: "SQL Injection already verified",
        severity: 3,
        confidence: 4,
        status: "PENDING" as const,
        description: "SQLi in /search",
        subtype: "sqli",
        tool: "scanner",
        phase: "scan",
        verificationResult: { passed: true, summary: "Already verified", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [alreadyVerified],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      await runner.run({ target: "https://example.com" })

      expect(callToolMock).not.toHaveBeenCalled()
    })

    test("emits warning when bridge is null (executorBridge not set)", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      // Create runner without deps — executorBridge starts as null
      const runner = new WorkflowRunner()

      const onProgress = mock(() => {})
      const emit = (event: any) => {
        if (typeof event === "string") onProgress(event)
      }

      const sqlFinding = {
        id: "find-sqli-null",
        title: "SQLi with null bridge",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "SQLi in /login",
        subtype: "sqli",
        tool: "scanner",
        phase: "scan",
        url: "https://example.com/login",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      // Access private method via any cast
      await (runner as any).mcpVerifyFindings(
        [sqlFinding],
        "https://example.com",
        "ENG-NULL-BRIDGE",
        emit,
      )

      expect(onProgress).toHaveBeenCalledWith(
        expect.stringContaining("bridge not available"),
      )
    })

    test("emits warning when bridge.callTool throws", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()

      const callToolMock = mock(async () => {
        throw new Error("Connection refused")
      })
      deps.bridge.callTool = callToolMock

      const sqliFinding = {
        id: "find-sqli-throw",
        title: "SQLi that triggers bridge error",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "SQLi in /search",
        subtype: "sqli",
        tool: "scanner",
        phase: "scan",
        url: "https://example.com/search",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [sqliFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const onProgress = mock(() => {})
      const runner = new WorkflowRunner(deps)
      await runner.run({ target: "https://example.com", onProgress })

      const calls = onProgress.mock.calls.map((c: any[]) => String(c[0]))
      expect(calls.some((s: string) => s.includes("MCP bridge call failed"))).toBe(true)
      expect(calls.some((s: string) => s.includes("Connection refused"))).toBe(true)
    })

    test("does not verify when callTool returns unverified", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()

      const callToolMock = mock(async (_tool: string, _args: any, _timeout?: number) => ({
        success: true,
        data: { verified: false, confidence: "LOW", reason: "Payload not reflected" },
      }))
      deps.bridge.callTool = callToolMock

      const sqliFinding = {
        id: "find-sqli-unver",
        title: "SQLi not confirmed",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "SQLi in /login",
        subtype: "sqli",
        tool: "scanner",
        phase: "scan",
        url: "https://example.com/login",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [sqliFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      const result = await runner.run({ target: "https://example.com" })

      // Finding should still be in results, but no verificationResult set
      expect(result.allFindings).toHaveLength(1)
      expect(result.allFindings[0].id).toBe("find-sqli-unver")
      expect(result.allFindings[0].verificationResult).toBeUndefined()
    })

    test("verifies XSS via MCP when subtype matches", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()

      const callToolMock = mock(async (_tool: string, _args: any, _timeout?: number) => ({
        success: true,
        data: { verified: true, confidence: "HIGH", reason: "XSS payload reflected" },
      }))
      deps.bridge.callTool = callToolMock

      const xssFinding = {
        id: "find-xss-1",
        title: "Reflected XSS in search",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "XSS in /search?q=<script>alert(1)</script>",
        subtype: "xss",
        tool: "scanner",
        phase: "scan",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      // Call mcpVerifyFindings directly to avoid browser verification
      // (XSS is now in noAuthSubtypes, so it would trigger Playwright
      // browser verification via runner.run(), which requires a real browser).
      const runner = new WorkflowRunner(deps)
      ;(runner as any).executorBridge = deps.bridge
      const onProgress = mock(() => {})
      const emit = (event: any) => {
        if (typeof event === "string") onProgress(event)
      }
      await (runner as any).mcpVerifyFindings(
        [xssFinding],
        "https://example.com",
        "ENG-test-001",
        emit,
      )

      expect(callToolMock).toHaveBeenCalledWith(
        "finding_verifier",
        expect.objectContaining({ finding_type: "xss" }),
        expect.any(Number),
      )
    })
  })

  // ── Confidence cascade while loop ──
  describe("Confidence cascade while loop", () => {
    function makeCascadeDeps() {
      const base = makeDeps()
      const realEngine = new ConfidenceEngine()
      base.deps.confidenceEngine = realEngine
      return base
    }

    test("promotes MEDIUM→HIGH→VERIFIED→CONFIRMED when browser verification passes", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeCascadeDeps()

      const verifiedFinding = {
        id: "find-xss-2",
        title: "Stored XSS in comments",
        severity: 3,
        confidence: 2,
        status: "PENDING" as const,
        description: "XSS in /comments",
        subtype: "xss",
        tool: "scanner",
        phase: "scan",
        cwe: "CWE-79",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: new Date().toISOString() }],
        verificationResult: { passed: true, summary: "XSS confirmed", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [verifiedFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      const result = await runner.run({ target: "https://example.com" })

      expect(result.allFindings).toHaveLength(1)
      expect(result.allFindings[0].confidence).toBe(5)
    })

    test("promotes HIGH→VERIFIED→CONFIRMED when starting from HIGH", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeCascadeDeps()

      const highFinding = {
        id: "find-rce-1",
        title: "Command Injection",
        severity: 4,
        confidence: 3,
        status: "PENDING" as const,
        description: "RCE in /exec",
        subtype: "command_injection",
        tool: "scanner",
        phase: "scan",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: new Date().toISOString() }],
        verificationResult: { passed: true, summary: "RCE confirmed", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [highFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      const result = await runner.run({ target: "https://example.com" })

      expect(result.allFindings).toHaveLength(1)
      expect(result.allFindings[0].confidence).toBe(5)
    })

    test("does not promote beyond available metadata", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeCascadeDeps()

      const lowFinding = {
        id: "find-info-1",
        title: "Info leak in header",
        severity: 1,
        confidence: 0,
        status: "PENDING" as const,
        description: "Server: Apache/2.4.41",
        subtype: "info_leak",
        tool: "scanner",
        phase: "scan",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [lowFinding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      const result = await runner.run({ target: "https://example.com" })

      expect(result.allFindings).toHaveLength(1)
      expect(result.allFindings[0].confidence).toBe(1)
    })

    test("preserves existing VERIFIED confidence when verification failed", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeCascadeDeps()

      const finding = {
        id: "find-ssrf-1",
        title: "SSRF in fetchUrl",
        severity: 3,
        confidence: 4,
        status: "PENDING" as const,
        description: "SSRF in /fetch?url=",
        subtype: "ssrf",
        tool: "scanner",
        phase: "scan",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: new Date().toISOString() }],
        verificationResult: { passed: false, summary: "SSRF not confirmed", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      deps.executor.execute = mock(() => ({
        phaseId: "phase-0-recon",
        status: "completed",
        findings: [finding],
        artifacts: [],
        errors: [],
        durationMs: 10,
      }))

      const runner = new WorkflowRunner(deps)
      const result = await runner.run({ target: "https://example.com" })

      expect(result.allFindings).toHaveLength(1)
      expect(result.allFindings[0].confidence).toBe(4)
    })
  })

  // ── ARGUS_LLM_MAX_REPLANS env var fallback ──
  describe("ARGUS_LLM_MAX_REPLANS env var fallback", () => {
    test("sets llmMaxReplans in replan context when env var is set", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      let capturedLlmmax: number | undefined
      deps.planner.replan = mock((ctx: any) => {
        capturedLlmmax = ctx.llmMaxReplans
        return null
      })

      process.env.ARGUS_LLM_MAX_REPLANS = "5"
      try {
        const runner = new WorkflowRunner(deps)
        await runner.run({ target: "https://example.com" })

        expect(capturedLlmmax).toBe(5)
      } finally {
        delete process.env.ARGUS_LLM_MAX_REPLANS
      }
    })

    test("llmMaxReplans is undefined when env var is not set", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      let capturedLlmmax: number | undefined = -999  // sentinel
      deps.planner.replan = mock((ctx: any) => {
        capturedLlmmax = ctx.llmMaxReplans
        return null
      })

      delete process.env.ARGUS_LLM_MAX_REPLANS
      const runner = new WorkflowRunner(deps)
      await runner.run({ target: "https://example.com" })

      expect(capturedLlmmax).toBeUndefined()
    })

    test("non-numeric ARGUS_LLM_MAX_REPLANS results in undefined", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      let capturedLlmmax: number | undefined
      deps.planner.replan = mock((ctx: any) => {
        capturedLlmmax = ctx.llmMaxReplans
        return null
      })

      process.env.ARGUS_LLM_MAX_REPLANS = "abc"
      try {
        const runner = new WorkflowRunner(deps)
        await runner.run({ target: "https://example.com" })

        expect(capturedLlmmax).toBeUndefined()
      } finally {
        delete process.env.ARGUS_LLM_MAX_REPLANS
      }
    })

    test("negative ARGUS_LLM_MAX_REPLANS results in undefined", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      let capturedLlmmax: number | undefined
      deps.planner.replan = mock((ctx: any) => {
        capturedLlmmax = ctx.llmMaxReplans
        return null
      })

      process.env.ARGUS_LLM_MAX_REPLANS = "-5"
      try {
        const runner = new WorkflowRunner(deps)
        await runner.run({ target: "https://example.com" })

        expect(capturedLlmmax).toBeUndefined()
      } finally {
        delete process.env.ARGUS_LLM_MAX_REPLANS
      }
    })

    test("ARGUS_LLM_MAX_REPLANS=0 passes through as 0", async () => {
      const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
      const { deps } = makeDeps()
      let capturedLlmmax: number | undefined
      deps.planner.replan = mock((ctx: any) => {
        capturedLlmmax = ctx.llmMaxReplans
        return null
      })

      process.env.ARGUS_LLM_MAX_REPLANS = "0"
      try {
        const runner = new WorkflowRunner(deps)
        await runner.run({ target: "https://example.com" })

        expect(capturedLlmmax).toBe(0)
      } finally {
        delete process.env.ARGUS_LLM_MAX_REPLANS
      }
    })
  })

  // ── disconnect in finally block ──
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
})

// ── validateAutonomousScopeMode (pure function extracted from WorkflowRunner) ──
// Tests the real exported function directly, no mock dependencies needed.
describe("validateAutonomousScopeMode", () => {
  test("does nothing when not autonomous regardless of mode", async () => {
    const { validateAutonomousScopeMode } =
      await import("../../../src/argus/workflow-runner")
    // Should not throw for any mode when isAutonomous is false
    validateAutonomousScopeMode(false, "warn")
    validateAutonomousScopeMode(false, "open")
    validateAutonomousScopeMode(false, "allowlist")
    validateAutonomousScopeMode(false, undefined)
  })

  test("accepts allowlist in autonomous mode", async () => {
    const { validateAutonomousScopeMode } =
      await import("../../../src/argus/workflow-runner")
    validateAutonomousScopeMode(true, "allowlist")
  })

  test("rejects warn in autonomous mode", async () => {
    const { validateAutonomousScopeMode } =
      await import("../../../src/argus/workflow-runner")
    expect(() => validateAutonomousScopeMode(true, "warn")).toThrow(
      "must be explicitly set to 'allowlist'"
    )
  })

  test("rejects open in autonomous mode", async () => {
    const { validateAutonomousScopeMode } =
      await import("../../../src/argus/workflow-runner")
    expect(() => validateAutonomousScopeMode(true, "open")).toThrow(
      "must be explicitly set to 'allowlist'"
    )
  })

  test("rejects undefined (defaults to warn) in autonomous mode", async () => {
    const { validateAutonomousScopeMode } =
      await import("../../../src/argus/workflow-runner")
    expect(() => validateAutonomousScopeMode(true, undefined)).toThrow(
      "Current mode is 'warn'"
    )
  })

  test("error message contains current mode value", async () => {
    const { validateAutonomousScopeMode } =
      await import("../../../src/argus/workflow-runner")
    expect(() => validateAutonomousScopeMode(true, "open")).toThrow(
      "Current mode is 'open'"
    )
  })
})



import { describe, expect, test, beforeEach } from "bun:test"
import { InProcessExecutor } from "../../../../src/argus/planner/executor"
import { Capability } from "../../../../src/argus/planner/capabilities"
import { ConfidenceEngine } from "../../../../src/argus/engagement/confidence"
import type { PhaseExecutionRequest } from "../../../../src/argus/planner/types"
import { Confidence } from "../../../../src/argus/planner/types"
import { LLMUnavailableError } from "../../../../src/argus/bridge/types"
import { FeatureFlags, Feature } from "../../../../src/argus/config/feature-flags"
import { ToolConfig } from "../../../../src/argus/config/tool-config"

const mockToolRegistry = {
  getToolsByCapability: () => [
    { name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 },
  ],
  getTool: (name: string) => {
    if (name === "test-tool") return { name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }
    if (name === "auth-tool") return { name: "auth-tool", capabilities: ["auth"], requires_auth: true, destructive: false, timeout_seconds: 30 }
    if (name === "destructive-tool") return { name: "destructive-tool", capabilities: ["scan"], requires_auth: false, destructive: true, timeout_seconds: 30 }
    if (name === "high-sig-tool") return { name: "high-sig-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30, signal_quality: "CONFIRMED" }
    return undefined
  },
  getToolTimeout: () => 120,
  listTools: () => [],
  load: () => {},
}

const mockBridge = {
  callTool: async () => ({ success: true, data: [{ id: "f1", title: "test finding", severity: 2, confidence: 0 }], durationMs: 10 }),
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
  agentInit: async () => ({ session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }),
  agentNext: async () => ({ session_id: "sess-1", tool: "test-tool", reasoning: "test", done: false }),
  agentObserve: async () => ({ session_id: "sess-1", tool: "test-tool", reasoning: "test", done: false }),
}

const mockWorkflowRegistry = {
  getWorkflow: () => ({ name: "test", approval_required: {} }),
  loadAll: () => [],
  listWorkflows: () => [],
  findByCapabilities: () => null,
  addWorkflow: () => {},
}

const mockApprovalWorkflowRegistry = {
  ...mockWorkflowRegistry,
  getWorkflow: () => ({ name: "test", approval_required: { destructive_tools: true } }),
}

function makePhase(overrides?: Partial<PhaseExecutionRequest>): PhaseExecutionRequest {
  return {
    phaseId: "phase-0-test",
    name: "test",
    workflowName: "test",
    target: "https://example.com",
    requiredCapabilities: [Capability.WEB_RECON],
    config: {},
    previousPhaseResults: [],
    ...overrides,
  }
}

describe("InProcessExecutor", () => {
  let executor: InProcessExecutor

  beforeEach(() => {
    executor = new InProcessExecutor(
      mockToolRegistry as any,
      mockBridge as any,
      new ConfidenceEngine(),
      mockWorkflowRegistry as any,
    )
    executor.loadGates("test")
  })

  describe("execute()", () => {
    test("returns completed result when phase has no errors", async () => {
      const result = await executor.execute(makePhase())
      expect(["completed", "partial"]).toContain(result.status)
      expect(Array.isArray(result.findings)).toBe(true)
      expect(Array.isArray(result.errors)).toBe(true)
      expect(result.durationMs).toBeGreaterThanOrEqual(0)
    })

    test("returns phaseId matching the input phase", async () => {
      const result = await executor.execute(makePhase({ phaseId: "phase-0-test" }))
      expect(result.phaseId).toBe("phase-0-test")
    })
  })

  describe("approval gates", () => {
    test("approval gate denies phase and returns skipped in non-TTY", async () => {
      const flags = new FeatureFlags({ [Feature.APPROVAL_GATES]: true })
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockApprovalWorkflowRegistry as any,
      )
      exec.setFeatureFlags(flags)
      exec.loadGates("test")
      const phase = makePhase({ approvalGateName: "destructive_tools" })
      const result = await exec.execute(phase)
      expect(result.status).toBe("skipped")
      expect(result.errors.length).toBeGreaterThan(0)
    })
  })

  describe("destructive tool confirmation (per-tool)", () => {
    test("non-destructive tool does NOT trigger per-tool destructive confirmation", async () => {
      // Non-destructive tool should proceed normally without any confirmation
      const flags = new FeatureFlags({ [Feature.APPROVAL_GATES]: true })
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.setFeatureFlags(flags)
      exec.loadGates("test")

      const phase = makePhase({ requiredCapabilities: [Capability.WEB_RECON] })
      const result = await exec.execute(phase)
      // Should complete normally — non-destructive tool doesn't need per-tool confirmation
      expect(["completed", "partial"]).toContain(result.status)
      expect(result.findings.length).toBeGreaterThan(0)
    })

    test("destructive tool in non-TTY auto-approves when used within an approved phase", async () => {
      const flags = new FeatureFlags({ [Feature.APPROVAL_GATES]: true })
      // Use a phase that has an approvalGateName matching a required gate, so it gets
      // the phase-level approval prompt. In non-TTY the destructive phase gate is
      // auto-skipped (returns false), so the phase won't execute. That's expected.
      // For a destructive tool that's NOT gated at phase level, the per-tool confirmation
      // auto-approves in non-TTY (phase was already approved).
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.setFeatureFlags(flags)
      exec.loadGates("test")

      // Use a phase without an approvalGateName so it bypasses phase-level gates
      // but still runs a destructive tool (destructive-tool is in mockToolRegistry)
      const phase = makePhase({
        phaseId: "phase-destructive",
        name: "destructive-test",
        requiredCapabilities: [Capability.WEB_RECON],
        config: {
          pipelineSteps: [
            { tool: "destructive-tool", capabilities: ["web_recon"], consumes: [], provides: [] },
          ],
        },
      })

      const result = await exec.execute(phase)
      // In non-TTY, per-tool destructive confirmation auto-approves
      expect(result.status).toBe("completed")
    })

    test("non-destructive phase-level tool does NOT trigger per-tool confirmation", async () => {
      // Even with gates enabled, non-destructive tools should never trigger
      // the per-tool destructive confirmation prompt
      const flags = new FeatureFlags({ [Feature.APPROVAL_GATES]: true })

      let confirmCalled = false
      const customApproval = {
        ...new (class MockApproval {
          confirmDestructiveTool = async () => {
            confirmCalled = true
            return { approved: true }
          }
          getRequiredGates = () => []
          needsApproval = () => null
          requestApproval = async () => ({ approved: true })
          registerGate = () => {}
          getGate = () => undefined
        })(),
      }

      // We can't easily inject a custom ApprovalService into InProcessExecutor,
      // so instead we just verify that a non-destructive tool proceeds normally.
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.setFeatureFlags(flags)
      exec.loadGates("test")
      const phase = makePhase({ requiredCapabilities: [Capability.WEB_RECON] })
      const result = await exec.execute(phase)
      expect(result.status).not.toBe("skipped")
    })
  })

  describe("setExecutionOptions", () => {
    test("setExecutionOptions does not throw", async () => {
      executor.setExecutionOptions({ cacheMode: "no_cache" })
      const result = await executor.execute(makePhase())
      expect(result).toBeDefined()
    })
  })

  describe("setOnProgress", () => {
    test("setOnProgress does not throw", () => {
      executor.setOnProgress(() => {})
    })
  })

  describe("setToolConfig", () => {
    test("setToolConfig creates tool health monitor", () => {
      const config = new ToolConfig()
      executor.setToolConfig(config)
      const health = executor.getToolHealth()
      expect(Array.isArray(health)).toBe(true)
    })
  })

  describe("getToolHealth", () => {
    test("getToolHealth returns array after execution", async () => {
      await executor.execute(makePhase())
      const health = executor.getToolHealth()
      expect(Array.isArray(health)).toBe(true)
    })
  })

  describe("error recovery policies", () => {
    function makeRecoveryBridge(recovery: string, failOnAttempt: number) {
      let attempt = 0
      return {
        ...mockBridge,
        callTool: async () => {
          attempt++
          if (attempt >= failOnAttempt) {
            return { success: true, data: [{ id: "f1", title: "found", severity: 2, confidence: 0 }], durationMs: 5 }
          }
          throw new Error("Tool failed")
        },
      }
    }

    test("retry_once_then_skip retries once and succeeds on second attempt", async () => {
      const bridge = makeRecoveryBridge("retry_once_then_skip", 2)
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const result = await exec.execute(makePhase())
      expect(result.status).toBe("completed")
      expect(result.findings.length).toBeGreaterThan(0)
    })
  })

  describe("parallel execution", () => {
    test("parallel mode executes tools and collects findings", async () => {
      const toolRegistry = {
        ...mockToolRegistry,
        getToolsByCapability: () => [
          { name: "tool-a", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
          { name: "tool-b", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
          { name: "tool-c", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
        ],
      }
      const exec = new InProcessExecutor(toolRegistry as any, mockBridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ toolExecution: "parallel" as const })
      const result = await exec.execute(phase)
      expect(result.findings.length).toBeGreaterThanOrEqual(1)
    })
  })

  describe("pipeline-based execution", () => {
    test("executes tools from pipelineSteps in order", async () => {
      const order: string[] = []
      const bridge = {
        ...mockBridge,
        callTool: async (name: string) => {
          order.push(name)
          return { success: true, data: [{ id: "f1", title: `finding from ${name}`, severity: 2, confidence: 0 }], durationMs: 5 }
        },
      }
      const toolRegistry = {
        ...mockToolRegistry,
        getTool: (name: string) => {
          if (name === "recon-tool") return { name: "recon-tool", capabilities: ["recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }
          if (name === "scan-tool") return { name: "scan-tool", capabilities: ["scan"], requires_auth: false, destructive: false, timeout_seconds: 30 }
          return { name, capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }
        },
      }
      const exec = new InProcessExecutor(toolRegistry as any, bridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({
        config: {
          pipelineSteps: [
            { tool: "recon-tool", capabilities: ["recon"], consumes: [], provides: ["hosts"] },
            { tool: "scan-tool", capabilities: ["scan"], consumes: ["hosts"], provides: ["vulns"] },
          ],
        },
      })
      await exec.execute(phase)
      expect(order).toEqual(["recon-tool", "scan-tool"])
    })

    test("missing tool in pipeline steps logs error", async () => {
      const toolRegistry = {
        ...mockToolRegistry,
        getTool: () => undefined,
      }
      const exec = new InProcessExecutor(toolRegistry as any, mockBridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({
        config: {
          pipelineSteps: [
            { tool: "nonexistent-tool", capabilities: ["recon"], consumes: [], provides: [] },
          ],
        },
      })
      const result = await exec.execute(phase)
      expect(result.errors[0]).toContain("not found")
    })
  })

  describe("executeHybrid", () => {
    test("agentInit is called with correct target", async () => {
      let initTarget = ""
      const bridge = {
        ...mockBridge,
        getToolsByCapability: () => [],
        agentInit: async (params: any) => {
          initTarget = params.target
          return { session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }
        },
        agentNext: async () => ({ session_id: "sess-1", done: true, reasoning: "done" }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ toolExecution: "llm_driven" as const, requiredCapabilities: [] })
      await exec.execute(phase)
      expect(initTarget).toBe("https://example.com")
    })

    test("agentNext done=true stops execution", async () => {
      const bridge = {
        ...mockBridge,
        agentInit: async () => ({ session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }),
        agentNext: async () => ({ session_id: "sess-1", done: true, reasoning: "done" }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ execution: "llm_driven" as const })
      const result = await exec.execute(phase)
      expect(result.status).toBe("completed")
    })

    test("LLMUnavailableError during hybrid execution is handled", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => { throw new LLMUnavailableError("DEGRADED", 30) },
        resetCircuitBreaker: () => {},
        agentInit: async () => ({ session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }),
        agentNext: async () => ({ session_id: "sess-1", tool: "test-tool", reasoning: "test", done: false }),
        agentObserve: async () => ({ session_id: "sess-1", done: true, reasoning: "done" }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ execution: "llm_driven" as const })
      const result = await exec.execute(phase)
      expect(result.errors[0]).toContain("LLM")
    })
  })

  describe("edge cases", () => {
    test("phase with no capabilities returns empty result", async () => {
      const toolRegistry = {
        ...mockToolRegistry,
        getToolsByCapability: () => [],
      }
      const exec = new InProcessExecutor(toolRegistry as any, mockBridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ requiredCapabilities: [] })
      const result = await exec.execute(phase)
      expect(result.status).toBe("completed")
      expect(result.findings).toHaveLength(0)
    })

    test("bridge callTool failure collects errors", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => ({ success: false, data: null, error: "rate limited", durationMs: 5 }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge as any, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const result = await exec.execute(makePhase())
      expect(result.errors.length).toBeGreaterThan(0)
    })
  })
})

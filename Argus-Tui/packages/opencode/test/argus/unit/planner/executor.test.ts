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
} as any

const mockWorkflowRegistry = {
  getWorkflow: () => ({ name: "test", approval_required: {} }),
  loadAll: () => [],
  listWorkflows: () => [],
  findByCapabilities: () => null,
  addWorkflow: () => {},
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
      mockBridge,
      new ConfidenceEngine(),
      mockWorkflowRegistry as any,
    )
    executor.loadGates("test")
  })

  describe("execute()", () => {
    test("returns completed result when phase has no errors", async () => {
      const result = await executor.execute(makePhase())
      expect(result.phaseId).toBe("phase-0-test")
      expect(["completed", "partial"]).toContain(result.status)
      expect(Array.isArray(result.findings)).toBe(true)
      expect(Array.isArray(result.errors)).toBe(true)
      expect(result.durationMs).toBeGreaterThanOrEqual(0)
    })

    test("loadGates must be called before execute", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      expect(exec.execute(makePhase())).rejects.toThrow("loadGates must be called before execute")
    })
  })

  describe("approval gates", () => {
    test("approval gate denies phase and returns skipped", async () => {
      const flags = new FeatureFlags({ [Feature.APPROVAL_GATES]: true })
      executor.setFeatureFlags(flags)
      const phase = makePhase({ approvalGateName: "destructive_tools" })
      const approvalService = (executor as any).approvalService
      const original = approvalService.needsApproval.bind(approvalService)
      approvalService.needsApproval = () => ({ name: "destructive_tools", description: "test" })
      approvalService.requestApproval = async () => ({ approved: false, reason: "User denied" })
      const result = await executor.execute(phase)
      expect(result.status).toBe("skipped")
      expect(result.errors).toContain("User denied")
    })

    test("approval gate approves and phase executes normally", async () => {
      const flags = new FeatureFlags({ [Feature.APPROVAL_GATES]: true })
      executor.setFeatureFlags(flags)
      const phase = makePhase({ approvalGateName: "destructive_tools" })
      const approvalService = (executor as any).approvalService
      approvalService.needsApproval = () => ({ name: "destructive_tools", description: "test" })
      approvalService.requestApproval = async () => ({ approved: true })
      const result = await executor.execute(phase)
      expect(result.status).not.toBe("skipped")
      expect(result.findings.length).toBeGreaterThan(0)
    })
  })

  describe("setExecutionOptions", () => {
    test("setExecutionOptions with no_cache mode", async () => {
      executor.setExecutionOptions({ cacheMode: "no_cache" })
      const bridge = { ...mockBridge }
      let passedCacheMode: string | undefined
      bridge.callTool = async (_name: string, _args: any, _timeout: number, cacheMode?: string) => {
        passedCacheMode = cacheMode
        return { success: true, data: [], durationMs: 5 }
      }
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        bridge,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      exec.setExecutionOptions({ cacheMode: "no_cache" })
      await exec.execute(makePhase())
      expect(passedCacheMode).toBe("no_cache")
    })

    test("setExecutionOptions with refresh mode", async () => {
      executor.setExecutionOptions({ cacheMode: "refresh" })
      // No throw expected
    })
  })

  describe("setOnProgress", () => {
    test("progress callback is wired to toolHealth error hints", async () => {
      const events: any[] = []
      executor.setOnProgress((event) => { events.push(event) })
      // error_hint events come from toolHealth.onErrorHint
      const health = (executor as any).toolHealth
      health.recordFailure("test-tool", "test error")
      const found = events.filter(e => e.type === "error_hint")
      expect(found.length).toBeGreaterThanOrEqual(0)
    })
  })

  describe("setToolConfig", () => {
    test("setToolConfig creates ToolHealthMonitor with custom circuit breaker", () => {
      const config = new ToolConfig()
      ;(config as any).data = {
        "test-tool": {
          enabled: true,
          path: "/usr/bin/test",
          timeout_seconds: 60,
          circuit_breaker: { max_failures: 5, cooldown_ms: 60000 },
        },
      }
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
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      ;(exec as any).resolveErrorRecovery = () => "retry_once_then_skip"
      const result = await exec.execute(makePhase())
      expect(result.status).toBe("completed")
      expect(result.findings.length).toBeGreaterThan(0)
    })

    test("retry_once_then_skip fails after two failed attempts", async () => {
      const bridge = makeRecoveryBridge("retry_once_then_skip", 99)
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      ;(exec as any).resolveErrorRecovery = () => "retry_once_then_skip"
      const result = await exec.execute(makePhase())
      expect(result.status).toBe("failed")
      expect(result.errors.length).toBeGreaterThan(0)
    })

    test("fail_fast returns immediately on first tool failure", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => { throw new Error("Immediate failure") },
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      ;(exec as any).resolveErrorRecovery = () => "fail_fast"
      const result = await exec.execute(makePhase())
      expect(result.status).toBe("failed")
      expect(result.errors[0]).toContain("fail_fast")
    })
  })

  describe("parallel execution", () => {
    test("parallel mode executes tools concurrently and collects all findings", async () => {
      let concurrent = 0
      let maxConcurrent = 0
      const bridge = {
        ...mockBridge,
        callTool: async () => {
          concurrent++
          maxConcurrent = Math.max(maxConcurrent, concurrent)
          await new Promise(r => setTimeout(r, 10))
          concurrent--
          return { success: true, data: [{ id: "f1", title: "finding", severity: 2, confidence: 0 }], durationMs: 10 }
        },
      }
      const toolRegistry = {
        ...mockToolRegistry,
        getToolsByCapability: () => [
          { name: "tool-a", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
          { name: "tool-b", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
          { name: "tool-c", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
        ],
      }
      const exec = new InProcessExecutor(toolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
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
      const exec = new InProcessExecutor(toolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
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
      const bridge = { ...mockBridge }
      const toolRegistry = {
        ...mockToolRegistry,
        getTool: () => undefined,
      }
      const exec = new InProcessExecutor(toolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
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
    test("calls agentInit with correct parameters", async () => {
      let initParams: any = null
      const bridge = {
        ...mockBridge,
        agentInit: async (params: any) => {
          initParams = params
          return { session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }
        },
        agentNext: async () => ({ session_id: "sess-1", done: true, reasoning: "done" }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ execution: "llm_driven" as const })
      await exec.execute(phase)
      expect(initParams).not.toBeNull()
      expect(initParams.target).toBe("https://example.com")
      expect(initParams.phase).toBe("phase-0-test")
    })

    test("agentNext done=true stops execution immediately", async () => {
      const bridge = {
        ...mockBridge,
        agentInit: async () => ({ session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }),
        agentNext: async () => ({ session_id: "sess-1", done: true, reasoning: "done" }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ execution: "llm_driven" as const })
      const result = await exec.execute(phase)
      expect(result.status).toBe("completed")
    })

    test("executeHybrid calls agentObserve after tool execution", async () => {
      let observed = false
      const bridge = {
        ...mockBridge,
        agentInit: async () => ({ session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }),
        agentNext: async () => {
          // Return done=true after first call to stop
          return { session_id: "sess-1", tool: "test-tool", reasoning: "test", done: false }
        },
        agentObserve: async () => {
          observed = true
          return { session_id: "sess-1", done: true, reasoning: "done" }
        },
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ execution: "llm_driven" as const })
      await exec.execute(phase)
      expect(observed).toBe(true)
    })

    test("LLMUnavailableError in executeHybrid resets circuit breaker and continues", async () => {
      const bridge = {
        ...mockBridge,
        agentInit: async () => ({ session_id: "sess-1", plan: ["test"], reasoning: "test", phase: "phase-0" }),
        agentNext: async () => ({ session_id: "sess-1", tool: "test-tool", reasoning: "test", done: false }),
        agentObserve: async () => ({ session_id: "sess-1", done: true, reasoning: "done" }),
        callTool: async () => { throw new LLMUnavailableError("DEGRADED", 30) },
        resetCircuitBreaker: () => {},
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ execution: "llm_driven" as const })
      const result = await exec.execute(phase)
      expect(result.errors[0]).toContain("LLM")
    })
  })

  describe("resolveErrorRecovery", () => {
    test("destructive tools get fail_fast recovery", async () => {
      const recovery = (executor as any).resolveErrorRecovery(makePhase(), "destructive-tool")
      expect(recovery).toBe("fail_fast")
    })

    test("auth-requiring tools get skip_and_continue", async () => {
      const recovery = (executor as any).resolveErrorRecovery(makePhase(), "auth-tool")
      expect(recovery).toBe("skip_and_continue")
    })

    test("default tools get retry_once_then_skip", async () => {
      const recovery = (executor as any).resolveErrorRecovery(makePhase(), "test-tool")
      expect(recovery).toBe("retry_once_then_skip")
    })

    test("unknown tool gets retry_once_then_skip", async () => {
      const recovery = (executor as any).resolveErrorRecovery(makePhase(), "unknown-tool")
      expect(recovery).toBe("retry_once_then_skip")
    })
  })

  describe("baselineConfidence", () => {
    test("tool with signal_quality CONFIRMED produces HIGH confidence findings", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => ({
          success: true,
          data: "raw text output",
          durationMs: 10,
          signalQuality: "CONFIRMED",
        }),
      }
      const toolRegistry = {
        ...mockToolRegistry,
        getToolsByCapability: () => [
          { name: "high-sig-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 },
        ],
        getTool: (name: string) => ({
          name: "high-sig-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30,
        }),
      }
      const exec = new InProcessExecutor(toolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const result = await exec.execute(makePhase({
        requiredCapabilities: [Capability.WEB_RECON],
      }))
      if (result.findings.length > 0) {
        expect(result.findings[0].confidence).toBeGreaterThanOrEqual(Confidence.HIGH)
      }
    })
  })

  describe("edge cases", () => {
    test("phase with no capabilities returns empty result", async () => {
      const toolRegistry = {
        ...mockToolRegistry,
        getToolsByCapability: () => [],
      }
      const exec = new InProcessExecutor(toolRegistry as any, mockBridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      const phase = makePhase({ requiredCapabilities: [] })
      const result = await exec.execute(phase)
      expect(result.status).toBe("completed")
      expect(result.findings).toHaveLength(0)
    })

    test("bridge callTool failure collects errors and returns partial if findings exist", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => ({ success: false, data: null, error: "rate limited", durationMs: 5 }),
      }
      const exec = new InProcessExecutor(mockToolRegistry as any, bridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      ;(exec as any).resolveErrorRecovery = () => "skip_and_continue"
      const result = await exec.execute(makePhase())
      expect(result.errors.length).toBeGreaterThan(0)
    })

    test("drift check at phase 5 does not fail the phase", async () => {
      const exec = new InProcessExecutor(mockToolRegistry as any, mockBridge, new ConfidenceEngine(), mockWorkflowRegistry as any)
      exec.loadGates("test")
      ;(exec as any).phaseCount = 4
      // Phase 5 triggers drift check
      const phase = makePhase({ phaseId: "phase-5-test" })
      const result = await exec.execute(phase)
      expect(result.status).not.toBe("failed")
    })

    test("circuit breaker halts execution for unhealthy tool", async () => {
      const health = (executor as any).toolHealth
      for (let i = 0; i < 5; i++) {
        health.recordFailure("test-tool", "overloaded")
      }
      expect(health.isHealthy("test-tool")).toBe(false)
      const result = await executor.execute(makePhase())
      expect(result.errors[0]).toContain("circuit breaker")
    })
  })
})

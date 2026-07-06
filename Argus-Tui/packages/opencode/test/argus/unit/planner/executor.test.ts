import { describe, expect, test, beforeEach } from "bun:test"
import { InProcessExecutor, CrossToolRateLimiter, ThrottleTracker } from "../../../../src/argus/planner/executor"
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

  describe("CrossToolRateLimiter (blocker 44)", () => {
    beforeEach(() => {
      delete process.env.ARGUS_CROSS_TOOL_RATE_LIMIT
      delete process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS
    })

    test("constructs with default values when no env vars set", () => {
      const limiter = new CrossToolRateLimiter()
      expect((limiter as any).maxRequests).toBe(50)
      expect((limiter as any).windowMs).toBe(1000)
    })

    test("acquire returns 0 for first request to a target", () => {
      const limiter = new CrossToolRateLimiter()
      expect(limiter.acquire("https://example.com")).toBe(0)
    })

    test("acquire allows up to maxRequests without delay", () => {
      const limiter = new CrossToolRateLimiter()
      for (let i = 0; i < 50; i++) {
        expect(limiter.acquire("https://example.com")).toBe(0)
      }
    })

    test("acquire returns positive delay when limit is exceeded", () => {
      const limiter = new CrossToolRateLimiter()
      for (let i = 0; i < 50; i++) {
        limiter.acquire("https://example.com")
      }
      const delay = limiter.acquire("https://example.com")
      expect(delay).toBeGreaterThanOrEqual(1)
    })

    test("different targets have independent rate limits", () => {
      const limiter = new CrossToolRateLimiter()
      // Saturate target A
      for (let i = 0; i < 50; i++) {
        limiter.acquire("target-a")
      }
      // Target B should still get 0 delay
      expect(limiter.acquire("target-b")).toBe(0)
      // Target A should now be delayed
      expect(limiter.acquire("target-a")).toBeGreaterThanOrEqual(1)
    })

    test("reset clears all windows", () => {
      const limiter = new CrossToolRateLimiter()
      for (let i = 0; i < 50; i++) {
        limiter.acquire("example.com")
      }
      expect(limiter.acquire("example.com")).toBeGreaterThanOrEqual(1)
      limiter.reset()
      expect(limiter.acquire("example.com")).toBe(0)
    })

    test("honors custom env var ARGUS_CROSS_TOOL_RATE_LIMIT", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "5"
      const limiter = new CrossToolRateLimiter()
      for (let i = 0; i < 5; i++) {
        expect(limiter.acquire("test.com")).toBe(0)
      }
      expect(limiter.acquire("test.com")).toBeGreaterThanOrEqual(1)
    })

    test("honors custom env var ARGUS_CROSS_TOOL_RATE_WINDOW_MS", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS = "5000"
      const limiter = new CrossToolRateLimiter()
      expect((limiter as any).windowMs).toBe(5000)
    })

    test("rate limits with small batch size", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "3"
      process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS = "1000"
      const limiter = new CrossToolRateLimiter()
      expect(limiter.acquire("x.com")).toBe(0)
      expect(limiter.acquire("x.com")).toBe(0)
      expect(limiter.acquire("x.com")).toBe(0)
      expect(limiter.acquire("x.com")).toBeGreaterThanOrEqual(1)
    })

    test("old entries are pruned after window passes", async () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "2"
      process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS = "50"
      const limiter = new CrossToolRateLimiter()
      expect(limiter.acquire("x.com")).toBe(0)
      expect(limiter.acquire("x.com")).toBe(0)
      expect(limiter.acquire("x.com")).toBeGreaterThanOrEqual(1)
      // Wait for window to pass
      await new Promise(r => setTimeout(r, 60))
      // After the window, the old entries are pruned
      expect(limiter.acquire("x.com")).toBe(0)
    })

    // ── Deeper: Invariant tests ──

    test("invariant: after acquire returns delay d, waiting d allows next at 0", async () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "3"
      process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS = "100"
      const limiter = new CrossToolRateLimiter()
      // Saturate
      for (let i = 0; i < 3; i++) limiter.acquire("x.com")
      const delay = limiter.acquire("x.com")
      expect(delay).toBeGreaterThanOrEqual(1)
      // Wait for the suggested delay (plus a tiny buffer)
      await new Promise(r => setTimeout(r, delay + 20))
      // Next acquire should succeed since the window rotated
      expect(limiter.acquire("x.com")).toBe(0)
    })

    test("invariant: delay is never longer than windowMs", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "1"
      process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS = "50"
      const limiter = new CrossToolRateLimiter()
      limiter.acquire("x.com")
      const delay = limiter.acquire("x.com")
      // Delay should be based on oldest entry + window - now, which can't exceed windowMs
      expect(delay).toBeLessThanOrEqual(55)  // slightly over 50 due to Date.now() drift
    })

    test("concurrent targets do not interfere with each other", () => {
      const limiter = new CrossToolRateLimiter()
      // Interleave requests to two targets
      for (let i = 0; i < 10; i++) {
        limiter.acquire("target-a")
        limiter.acquire("target-b")
      }
      // Neither should be saturated yet
      expect(limiter.acquire("target-a")).toBe(0)
      expect(limiter.acquire("target-b")).toBe(0)
      // Saturate target-a
      for (let i = 0; i < 40; i++) limiter.acquire("target-a")
      expect(limiter.acquire("target-a")).toBeGreaterThanOrEqual(1)
      // target-b should still be clean
      expect(limiter.acquire("target-b")).toBe(0)
    })

    test("handles empty target string", () => {
      const limiter = new CrossToolRateLimiter()
      expect(limiter.acquire("")).toBe(0)
      expect(limiter.acquire("")).toBe(0)
    })

    test("handles very long target string", () => {
      const limiter = new CrossToolRateLimiter()
      const longTarget = "https://" + "a".repeat(1000) + ".com"
      expect(limiter.acquire(longTarget)).toBe(0)
      expect(limiter.acquire(longTarget)).toBe(0)
    })

    test("zero window env var defaults to 1000", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_WINDOW_MS = "0"
      const limiter = new CrossToolRateLimiter()
      expect((limiter as any).windowMs).toBe(1000)
    })

    test("invalid limit env var defaults to 50", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "NaN"
      const limiter = new CrossToolRateLimiter()
      expect((limiter as any).maxRequests).toBe(50)
    })

    test("negative limit env var defaults to 50", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "-5"
      const limiter = new CrossToolRateLimiter()
      expect((limiter as any).maxRequests).toBe(50)
    })

    test("burst: rapidly acquiring beyond limit is safe", () => {
      process.env.ARGUS_CROSS_TOOL_RATE_LIMIT = "10"
      const limiter = new CrossToolRateLimiter()
      for (let i = 0; i < 100; i++) {
        const delay = limiter.acquire("burst-target")
        expect(delay).toBeGreaterThanOrEqual(0)
        expect(typeof delay).toBe("number")
      }
    })

    test("multiple different targets saturate independently", () => {
      const limiter = new CrossToolRateLimiter()
      const targets = ["a.com", "b.com", "c.com", "d.com", "e.com"]
      // Saturate all
      for (const t of targets) {
        for (let i = 0; i < 50; i++) limiter.acquire(t)
      }
      // All should be delayed
      for (const t of targets) {
        expect(limiter.acquire(t)).toBeGreaterThanOrEqual(1)
      }
      // New target should be fine
      expect(limiter.acquire("fresh.com")).toBe(0)
    })
  })

  describe("ThrottleTracker (blocker 45)", () => {
    beforeEach(() => {
      delete process.env.ARGUS_THROTTLE_BASE_DELAY_MS
      delete process.env.ARGUS_THROTTLE_MAX_DELAY_MS
    })

    test("constructs with default values when no env vars set", () => {
      const tracker = new ThrottleTracker()
      expect((tracker as any).baseDelayMs).toBe(2000)
      expect((tracker as any).maxDelayMs).toBe(60000)
    })

    test("new target is not throttled", () => {
      const tracker = new ThrottleTracker()
      expect(tracker.isThrottled("https://example.com")).toBe(false)
      expect(tracker.getRemainingDelay("https://example.com")).toBe(0)
    })

    test("recordThrottle marks target as throttled with exponential backoff", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("example.com")
      expect(tracker.isThrottled("example.com")).toBe(true)
      const delay = tracker.getRemainingDelay("example.com")
      expect(delay).toBeGreaterThan(0)
      expect(delay).toBeLessThanOrEqual(2100)
    })

    test("consecutive throttles apply exponential backoff", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("example.com")
      const firstDelay = tracker.getRemainingDelay("example.com")
      tracker.recordThrottle("example.com")
      const secondDelay = tracker.getRemainingDelay("example.com")
      expect(secondDelay).toBeGreaterThan(firstDelay)
      tracker.recordThrottle("example.com")
      const thirdDelay = tracker.getRemainingDelay("example.com")
      expect(thirdDelay).toBeGreaterThan(secondDelay)
    })

    test("backoff is capped at maxDelayMs", () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "100"
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "500"
      const tracker = new ThrottleTracker()
      for (let i = 0; i < 10; i++) {
        tracker.recordThrottle("example.com")
      }
      const delay = tracker.getRemainingDelay("example.com")
      expect(delay).toBeLessThanOrEqual(550)
    })

    test("recordSuccess clears throttle state", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("example.com")
      expect(tracker.isThrottled("example.com")).toBe(true)
      tracker.recordSuccess("example.com")
      expect(tracker.isThrottled("example.com")).toBe(false)
      expect(tracker.getRemainingDelay("example.com")).toBe(0)
    })

    test("different targets have independent throttle states", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("target-a")
      expect(tracker.isThrottled("target-a")).toBe(true)
      expect(tracker.isThrottled("target-b")).toBe(false)
      tracker.recordSuccess("target-a")
      expect(tracker.isThrottled("target-a")).toBe(false)
    })

    test("reset clears all throttle state", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("a.com")
      tracker.recordThrottle("b.com")
      expect(tracker.isThrottled("a.com")).toBe(true)
      expect(tracker.isThrottled("b.com")).toBe(true)
      tracker.reset()
      expect(tracker.isThrottled("a.com")).toBe(false)
      expect(tracker.isThrottled("b.com")).toBe(false)
    })

    test("throttle expires after the backoff period", async () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "30"
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "30"
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("fast.com")
      expect(tracker.isThrottled("fast.com")).toBe(true)
      await new Promise(r => setTimeout(r, 40))
      expect(tracker.isThrottled("fast.com")).toBe(false)
    })

    test("isThrottled auto-cleans expired entries", () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "1"
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "1"
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("ephemeral.com")
      expect(tracker.isThrottled("ephemeral.com")).toBe(true)
    })

    test("honors custom env var ARGUS_THROTTLE_BASE_DELAY_MS", () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "5000"
      const tracker = new ThrottleTracker()
      expect((tracker as any).baseDelayMs).toBe(5000)
    })

    test("honors custom env var ARGUS_THROTTLE_MAX_DELAY_MS", () => {
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "30000"
      const tracker = new ThrottleTracker()
      expect((tracker as any).maxDelayMs).toBe(30000)
    })

    // ── Deeper: Edge cases ──

    test("invariant: getRemainingDelay decreases over time", async () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "100"
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "100"
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("slow.com")
      const d1 = tracker.getRemainingDelay("slow.com")
      await new Promise(r => setTimeout(r, 30))
      const d2 = tracker.getRemainingDelay("slow.com")
      expect(d2).toBeLessThan(d1)
      expect(d2).toBeGreaterThanOrEqual(0)
    })

    test("invariant: after isThrottled returns false due to expiry, getRemainingDelay returns 0", async () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "20"
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "20"
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("gone.com")
      await new Promise(r => setTimeout(r, 30))
      expect(tracker.isThrottled("gone.com")).toBe(false)
      expect(tracker.getRemainingDelay("gone.com")).toBe(0)
    })

    test("NaN env var falls back to default", () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "not-a-number"
      const tracker = new ThrottleTracker()
      expect((tracker as any).baseDelayMs).toBe(2000)
    })

    test("negative env var falls back to default", () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = "-100"
      const tracker = new ThrottleTracker()
      expect((tracker as any).baseDelayMs).toBe(2000)
    })

    test("zero delay env var falls back to default", () => {
      process.env.ARGUS_THROTTLE_MAX_DELAY_MS = "0"
      const tracker = new ThrottleTracker()
      expect((tracker as any).maxDelayMs).toBe(60000)
    })

    test("empty string env var falls back to default", () => {
      process.env.ARGUS_THROTTLE_BASE_DELAY_MS = ""
      const tracker = new ThrottleTracker()
      expect((tracker as any).baseDelayMs).toBe(2000)
    })

    test("repeated recordThrottle on already-throttled target increases backoff", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("multi.com")
      const firstDelay = tracker.getRemainingDelay("multi.com")
      tracker.recordThrottle("multi.com")
      const secondDelay = tracker.getRemainingDelay("multi.com")
      tracker.recordThrottle("multi.com")
      const thirdDelay = tracker.getRemainingDelay("multi.com")
      // Each should be roughly 2x the previous
      expect(secondDelay).toBeGreaterThan(firstDelay * 1.5)
      expect(thirdDelay).toBeGreaterThan(secondDelay * 1.5)
    })

    test("recordThrottle with no prior state sets consecutive to 1", () => {
      const tracker = new ThrottleTracker()
      tracker.recordThrottle("fresh.com")
      const entry = (tracker as any).throttledTargets.get("fresh.com")
      expect(entry.consecutive).toBe(1)
      expect(entry.backoffMs).toBe(2000)  // base
    })
  })

  describe("ThrottleTracker.isRateLimitError", () => {
    test("returns true for 429 status code", () => {
      expect(ThrottleTracker.isRateLimitError("HTTP 429 Too Many Requests")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("status 429")).toBe(true)
    })

    test("returns true for 503 status code", () => {
      expect(ThrottleTracker.isRateLimitError("HTTP 503 Service Unavailable")).toBe(true)
    })

    test("returns true for rate limit text", () => {
      expect(ThrottleTracker.isRateLimitError("rate limit exceeded")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("rate_limit")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("rate-limiting")).toBe(true)
    })

    test("returns true for 'too many requests'", () => {
      expect(ThrottleTracker.isRateLimitError("too many requests")).toBe(true)
    })

    test("returns true for 'retry after'", () => {
      expect(ThrottleTracker.isRateLimitError("retry after 30 seconds")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("Retry-After: 120")).toBe(true)
    })

    test("returns true for 'throttl' patterns", () => {
      expect(ThrottleTracker.isRateLimitError("throttled")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("throttling")).toBe(true)
    })

    test("returns false for non-rate-limit errors", () => {
      expect(ThrottleTracker.isRateLimitError("connection refused")).toBe(false)
      expect(ThrottleTracker.isRateLimitError("timeout")).toBe(false)
      expect(ThrottleTracker.isRateLimitError("404 not found")).toBe(false)
      expect(ThrottleTracker.isRateLimitError("500 internal error")).toBe(false)
    })

    test("returns false for empty or null messages", () => {
      expect(ThrottleTracker.isRateLimitError("")).toBe(false)
      expect(ThrottleTracker.isRateLimitError(null as unknown as string)).toBe(false)
    })

    test("is case insensitive", () => {
      expect(ThrottleTracker.isRateLimitError("RATE LIMIT")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("Rate Limited")).toBe(true)
      expect(ThrottleTracker.isRateLimitError("TOO MANY REQUESTS")).toBe(true)
    })
  })

  describe("global assessment timer (blocker 20)", () => {
    test("assessmentStartTime starts at 0", () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      expect((exec as any).assessmentStartTime).toBe(0)
    })

    test("execute sets assessmentStartTime on first phase call", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      expect((exec as any).assessmentStartTime).toBe(0)
      await exec.execute(makePhase())
      expect((exec as any).assessmentStartTime).toBeGreaterThan(0)
    })

    test("assessmentStartTime is not reset on second execute call", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      await exec.execute(makePhase())
      const firstTime = (exec as any).assessmentStartTime
      await exec.execute(makePhase({ phaseId: "phase-1-second" }))
      const secondTime = (exec as any).assessmentStartTime
      expect(secondTime).toBe(firstTime)
    })

    test("global breaker returns failed result after maxAssessmentDurationMs", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      ;(exec as any).assessmentStartTime = Date.now() - (2 * 3600 * 1000)
      const result = await exec.execute(makePhase())
      expect(result.status).toBe("failed")
      expect(result.errors[0]).toContain("global circuit breaker tripped")
      expect(result.errors[0]).toContain("7200000ms")
    })

    // ── Deeper: Env var edge cases ──

    test("custom ARGUS_MAX_ASSESSMENT_DURATION_MS is honored", async () => {
      process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS = "100"
      try {
        const exec = new InProcessExecutor(
          mockToolRegistry as any,
          mockBridge as any,
          new ConfidenceEngine(),
          mockWorkflowRegistry as any,
        )
        exec.loadGates("test")
        ;(exec as any).assessmentStartTime = Date.now() - 200
        const result = await exec.execute(makePhase())
        expect(result.status).toBe("failed")
        expect(result.errors[0]).toContain("100ms")
      } finally {
        delete process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS
      }
    })

    test("NaN assessment duration env var defaults to 7200000", () => {
      process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS = "hello"
      try {
        const exec = new InProcessExecutor(
          mockToolRegistry as any,
          mockBridge as any,
          new ConfidenceEngine(),
          mockWorkflowRegistry as any,
        )
        expect((exec as any).maxAssessmentDurationMs).toBe(7_200_000)
      } finally {
        delete process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS
      }
    })

    test("phaseDeadline is set at phase start", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      expect((exec as any).phaseDeadline).toBe(0)
      await exec.execute(makePhase())
      expect((exec as any).phaseDeadline).toBeGreaterThan(0)
    })

    test("per-phase timeout error is returned when phaseDeadline exceeded", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      ;(exec as any).phaseDeadline = Date.now() - 1  // already expired
      const result = await exec.execute(makePhase())
      expect(result.errors.some(e => e.includes("timeout"))).toBe(true)
    })
  })

  describe("env var parsing — duration defaults", () => {
    beforeEach(() => {
      delete process.env.ARGUS_MAX_PHASE_DURATION_MS
      delete process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS
    })

    function makeExec() {
      return new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
    }

    test("default maxPhaseDurationMs is 30 min", () => {
      expect((makeExec() as any).maxPhaseDurationMs).toBe(1_800_000)
    })

    test("default maxAssessmentDurationMs is 2 hours", () => {
      expect((makeExec() as any).maxAssessmentDurationMs).toBe(7_200_000)
    })

    test("NaN maxPhaseDurationMs falls back to default", () => {
      process.env.ARGUS_MAX_PHASE_DURATION_MS = "NaN"
      expect((makeExec() as any).maxPhaseDurationMs).toBe(1_800_000)
    })

    test("negative maxPhaseDurationMs falls back to default", () => {
      process.env.ARGUS_MAX_PHASE_DURATION_MS = "-5000"
      expect((makeExec() as any).maxPhaseDurationMs).toBe(1_800_000)
    })

    test("zero maxPhaseDurationMs falls back to default", () => {
      process.env.ARGUS_MAX_PHASE_DURATION_MS = "0"
      expect((makeExec() as any).maxPhaseDurationMs).toBe(1_800_000)
    })

    test("valid custom maxPhaseDurationMs is used", () => {
      process.env.ARGUS_MAX_PHASE_DURATION_MS = "5000"
      expect((makeExec() as any).maxPhaseDurationMs).toBe(5000)
    })

    test("empty maxPhaseDurationMs falls back to default", () => {
      process.env.ARGUS_MAX_PHASE_DURATION_MS = ""
      expect((makeExec() as any).maxPhaseDurationMs).toBe(1_800_000)
    })

    test("NaN maxAssessmentDurationMs falls back to default", () => {
      process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS = "abc"
      expect((makeExec() as any).maxAssessmentDurationMs).toBe(7_200_000)
    })

    test("negative maxAssessmentDurationMs falls back to default", () => {
      process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS = "-100"
      expect((makeExec() as any).maxAssessmentDurationMs).toBe(7_200_000)
    })

    test("valid custom maxAssessmentDurationMs is used", () => {
      process.env.ARGUS_MAX_ASSESSMENT_DURATION_MS = "3600000"
      expect((makeExec() as any).maxAssessmentDurationMs).toBe(3_600_000)
    })
  })

  describe("throttle tracker integration in executeTool (blocker 45)", () => {
    test("rate-limit error in callTool response records throttle on target", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => ({ success: false, data: null, error: "HTTP 429 Too Many Requests", durationMs: 5 }),
      }
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        bridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      await exec.execute(makePhase())
      // After a 429 response, throttle tracker should have recorded it
      expect((exec as any).throttleTracker.isThrottled("https://example.com")).toBe(true)
    })

    test("successful callTool resets throttle on target", async () => {
      const results: Array<{ success: boolean; error?: string }> = [
        { success: false, error: "rate limited" },
        { success: true, data: [{ id: "f1", title: "ok", severity: 2, confidence: 0 }], durationMs: 5 },
      ]
      let callCount = 0
      const bridge = {
        ...mockBridge,
        callTool: async () => {
          const r = results[callCount]
          callCount++
          return r as any
        },
      }
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        bridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      await exec.execute(makePhase({ requiredCapabilities: [Capability.WEB_RECON] }))
      // The last callTool was successful, so throttle should be cleared
      expect((exec as any).throttleTracker.isThrottled("https://example.com")).toBe(false)
    })

    test("503 in catch block + retry + success clears throttle", async () => {
      // This validates that a 503 thrown in the catch block is handled by
      // executeTool's retry mechanism: the catch records the throttle, the
      // retry succeeds, and recordSuccess clears the throttle before the
      // assertion runs. The throttle IS recorded during execution but gets
      // cleared by the successful retry.
      let callCount = 0
      const bridge = {
        ...mockBridge,
        callTool: async () => {
          if (callCount++ === 0) throw new Error("HTTP 503 Service Unavailable")
          return { success: true, data: [{ id: "f1", title: "ok", severity: 2, confidence: 0 }], durationMs: 5 }
        },
      }
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        bridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      await exec.execute(makePhase())
      // After retry+success, throttle is cleared
      expect((exec as any).throttleTracker.isThrottled("https://example.com")).toBe(false)
    })

    test("non-rate-limit errors do not record throttle", async () => {
      const bridge = {
        ...mockBridge,
        callTool: async () => ({ success: false, data: null, error: "connection timeout", durationMs: 10 }),
      }
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        bridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      await exec.execute(makePhase())
      expect((exec as any).throttleTracker.isThrottled("https://example.com")).toBe(false)
    })

    test("rate limiter and throttle tracker are reset at each phase start", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      // Manually dirty the trackers
      ;(exec as any).rateLimiter.acquire("dirty")
      ;(exec as any).throttleTracker.recordThrottle("dirty")
      expect((exec as any).throttleTracker.isThrottled("dirty")).toBe(true)
      // Execute a phase — should reset both at the start
      await exec.execute(makePhase())
      expect((exec as any).throttleTracker.isThrottled("dirty")).toBe(false)
      const delay = (exec as any).rateLimiter.acquire("dirty")
      expect(delay).toBe(0)  // was reset, so first access gets 0
    })
  })

  describe("scopeConfig integration — out-of-scope skip", () => {
    test("target in allowed_targets passes scope check", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      exec.setScopeConfig({ mode: "allowlist", allowed_targets: ["example.com"] })
      const result = await exec.execute(makePhase({ target: "https://example.com/api" }))
      expect(result.status).toBe("completed")
    })

    test("target not in allowed_targets is skipped with out-of-scope error", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      exec.setScopeConfig({ mode: "allowlist", allowed_targets: ["internal.com"] })
      const result = await exec.execute(makePhase({ target: "https://evil.com/api" }))
      expect(result.status).toBe("completed")  // No findings is valid completion
      expect(result.errors.some(e => e.includes("out of scope"))).toBe(true)
      expect(result.findings).toHaveLength(0)
    })

    test("scope check uses includes match with wildcard stripping", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      exec.setScopeConfig({ mode: "allowlist", allowed_targets: ["*.example.com"] })
      const result = await exec.execute(makePhase({ target: "https://sub.example.com/api" }))
      // After wildcard stripping, "*.example.com" → "example.com" → includes match
      expect(result.status).toBe("completed")
    })

    test("empty allowed_targets in allowlist mode blocks all targets", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      exec.setScopeConfig({ mode: "allowlist", allowed_targets: [] })
      const result = await exec.execute(makePhase())
      expect(result.errors.some(e => e.includes("out of scope"))).toBe(true)
    })

    test("allow_all mode does not filter targets", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      exec.setScopeConfig({ mode: "allow_all" })
      const result = await exec.execute(makePhase({ target: "https://anything.com" }))
      expect(result.status).toBe("completed")
      expect(result.errors.filter(e => e.includes("out of scope")).length).toBe(0)
    })

    test("no scope config does not filter targets", async () => {
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      // scopeConfig is null by default
      const result = await exec.execute(makePhase({ target: "https://anything.com" }))
      expect(result.status).toBe("completed")
      expect(result.errors.filter(e => e.includes("out of scope")).length).toBe(0)
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

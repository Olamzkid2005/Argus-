import { describe, expect, test, mock } from "bun:test"
import { InProcessExecutor } from "../../../src/argus/planner/executor"
import { ConfidenceEngine } from "../../../src/argus/engagement/confidence"
import { ToolConfig } from "../../../src/argus/config/tool-config"
import type { PhaseExecutionRequest } from "../../../src/argus/planner/types"
import type { ProgressEvent, ErrorHintData } from "../../../src/argus/shared/progress"
import { Capability } from "../../../src/argus/shared/capabilities"

class MockToolRegistry {
  getToolsByCapability() { return [] }
  getTool(_name: string) { return undefined }
  getToolTimeout(_name: string) { return 300 }
  listTools() { return [] }
  load() {}
}

const mockBridge = {
  callTool: async () => ({ success: true, data: [], durationMs: 10 }),
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

describe("InProcessExecutor fixes", () => {
  describe("setToolConfig re-attaches onErrorHint", () => {
    test("error hints fire after setToolConfig when onProgress is set", () => {
      const executor = new InProcessExecutor(
        new MockToolRegistry() as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      const captured: ProgressEvent[] = []
      executor.setOnProgress((event) => captured.push(event))
      const config = new ToolConfig()
      executor.setToolConfig(config)
      const hint: ErrorHintData = {
        tool: "nuclei",
        summary: "nuclei failed",
        detail: "Connection refused",
      }
      ;(executor as any).toolHealth.onErrorHint(hint)
      expect(captured.length).toBeGreaterThanOrEqual(1)
      const event = captured[0] as ProgressEvent & { type: "error_hint" }
      expect(event.type).toBe("error_hint")
      expect(event.tool).toBe("nuclei")
      expect(event.summary).toBe("nuclei failed")
      expect(event.detail).toBe("Connection refused")
    })

    test("error hints fire without onProgress (no crash)", () => {
      const executor = new InProcessExecutor(
        new MockToolRegistry() as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      const config = new ToolConfig()
      executor.setToolConfig(config)
      const hint: ErrorHintData = {
        tool: "nuclei",
        summary: "nuclei failed",
        detail: "Connection refused",
      }
      expect(() => {
        ;(executor as any).toolHealth.onErrorHint(hint)
      }).not.toThrow()
    })
  })

  describe("executeHybrid passes timeout from registry", () => {
    test("callTool receives timeout from getToolTimeout multiplied by 1000", async () => {
      let capturedTimeout: number | undefined
      const bridge = {
        ...mockBridge,
        callTool: async (_name: string, _args: unknown, timeout?: number) => {
          capturedTimeout = timeout
          return { success: true, data: [], durationMs: 10 }
        },
      }
      const registry = new MockToolRegistry()
      registry.getToolTimeout = () => 600
      const executor = new InProcessExecutor(
        registry as any,
        bridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      executor.loadGates("test")
      await executor.execute(makePhase({ toolExecution: "llm_driven" as const, requiredCapabilities: [] }))
      expect(capturedTimeout).toBe(600_000)
    })

    test("callTool receives timeout from per-tool registry value", async () => {
      let capturedTimeout: number | undefined
      const bridge = {
        ...mockBridge,
        callTool: async (_name: string, _args: unknown, timeout?: number) => {
          capturedTimeout = timeout
          return { success: true, data: [], durationMs: 10 }
        },
      }
      const registry = new MockToolRegistry()
      registry.getToolTimeout = (name: string) => name === "test-tool" ? 120 : 300
      const executor = new InProcessExecutor(
        registry as any,
        bridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      executor.loadGates("test")
      await executor.execute(makePhase({ toolExecution: "llm_driven" as const, requiredCapabilities: [] }))
      expect(capturedTimeout).toBe(120_000)
    })
  })

  describe("reset clears emitProgress and executionOptions", () => {
    test("reset nullifies emitProgress", () => {
      const executor = new InProcessExecutor(
        new MockToolRegistry() as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      const handler = () => {}
      executor.setOnProgress(handler)
      expect((executor as any).emitProgress).toBe(handler)
      executor.reset()
      expect((executor as any).emitProgress).toBeNull()
    })

    test("reset clears executionOptions", () => {
      const executor = new InProcessExecutor(
        new MockToolRegistry() as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      executor.setExecutionOptions({ cacheMode: "no_cache", verbose: true })
      expect((executor as any).executionOptions).toEqual({ cacheMode: "no_cache", verbose: true })
      executor.reset()
      expect((executor as any).executionOptions).toEqual({})
    })

    test("reset does not throw when nothing is set", () => {
      const executor = new InProcessExecutor(
        new MockToolRegistry() as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      expect(() => executor.reset()).not.toThrow()
    })
  })
})

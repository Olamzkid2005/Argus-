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

  describe("consumeVerificationResult", () => {
    function makeExecutor() {
      return new InProcessExecutor(
        new MockToolRegistry() as any,
        mockBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
    }

    test("cascades MEDIUM→HIGH→VERIFIED→CONFIRMED in single call", () => {
      const executor = makeExecutor()
      const finding = {
        id: "find-sqli-1",
        title: "SQL Injection",
        severity: 3,
        confidence: 2, // MEDIUM
        status: "PENDING" as const,
        description: "SQLi in login",
        tool: "scanner",
        phase: "scan",
        cwe: "CWE-89",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: "" }],
        verificationResult: { passed: true, summary: "Confirmed", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const result = executor.consumeVerificationResult(finding)
      expect(result).toBe(5) // CONFIRMED
      expect(finding.confidence).toBe(5) // In-place mutation
    })

    test("cascades HIGH→VERIFIED→CONFIRMED when starting from HIGH", () => {
      const executor = makeExecutor()
      const finding = {
        id: "find-xss-1",
        title: "Reflected XSS",
        severity: 3,
        confidence: 3, // HIGH
        status: "PENDING" as const,
        description: "XSS in search",
        tool: "scanner",
        phase: "scan",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: "" }],
        verificationResult: { passed: true, summary: "Confirmed", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const result = executor.consumeVerificationResult(finding)
      expect(result).toBe(5) // CONFIRMED
      expect(finding.confidence).toBe(5)
    })

    test("does not promote when finding has no metadata beyond baseline", () => {
      const executor = makeExecutor()
      const finding = {
        id: "find-info-1",
        title: "Info leak",
        severity: 0,
        confidence: 0, // INFORMATIONAL
        status: "PENDING" as const,
        description: "Server header leak",
        tool: "scanner",
        phase: "scan",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const result = executor.consumeVerificationResult(finding)
      // INFORMATIONAL→LOW is unconditional, then no further promotions
      expect(result).toBe(1) // LOW
      expect(finding.confidence).toBe(1)
    })

    test("keeps CONFIRMED when already confirmed", () => {
      const executor = makeExecutor()
      const finding = {
        id: "find-rce-1",
        title: "RCE Confirmed",
        severity: 4,
        confidence: 5, // Already CONFIRMED
        status: "CONFIRMED" as const,
        description: "RCE in upload endpoint",
        tool: "scanner",
        phase: "scan",
        verificationResult: { passed: true, summary: "Confirmed", verifier: "browser", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const result = executor.consumeVerificationResult(finding)
      expect(result).toBe(5) // Stays CONFIRMED
      expect(finding.confidence).toBe(5)
    })

    test("does not promote to CONFIRMED when verificationResult.passed is false", () => {
      const executor = makeExecutor()
      const finding = {
        id: "find-ssrf-1",
        title: "SSRF Probe",
        severity: 3,
        confidence: 4, // VERIFIED (from evidence)
        status: "PENDING" as const,
        description: "SSRF in fetch",
        tool: "scanner",
        phase: "scan",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: "" }],
        verificationResult: { passed: false, summary: "Probe failed", verifier: "ssrf", verifiedAt: new Date().toISOString() },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const result = executor.consumeVerificationResult(finding)
      // VERIFIED stays VERIFIED because passed=false prevents promotion to CONFIRMED
      expect(result).toBe(4)
      expect(finding.confidence).toBe(4)
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

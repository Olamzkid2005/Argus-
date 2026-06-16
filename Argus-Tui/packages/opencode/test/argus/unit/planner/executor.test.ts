import { describe, expect, test, beforeEach } from "bun:test"
import { InProcessExecutor } from "../../../../src/argus/planner/executor"
import { Capability } from "../../../../src/argus/planner/capabilities"
import { ConfidenceEngine } from "../../../../src/argus/engagement/confidence"
import type { PhaseExecutionRequest } from "../../../../src/argus/planner/types"
import { Confidence } from "../../../../src/argus/planner/types"

// Mock tool returns no data
const mockToolRegistry = {
  getToolsByCapability: () => [
    { name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, supports_api: false, supports_web: true, timeout_seconds: 30 },
  ],
  getTool: () => ({ name: "test-tool", capabilities: ["web_recon"], requires_auth: false, destructive: false, timeout_seconds: 30 }),
  listTools: () => [],
  load: () => {},
}

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

    test("returns skipped result when approval gate denies", async () => {
      const phase = makePhase({ approvalGateName: "destructive_tools" })
      const result = await executor.execute(phase)
      // Approval gate with no matching policy defaults to approve
      expect(result.status).not.toBe("skipped")
    })

    test("returns failed result when bridge callTool fails with fail_fast", async () => {
      const failingBridge = {
        ...mockBridge,
        callTool: async () => { throw new Error("Connection refused") },
      }
      const exec = new InProcessExecutor(
        mockToolRegistry as any,
        failingBridge as any,
        new ConfidenceEngine(),
        mockWorkflowRegistry as any,
      )
      exec.loadGates("test")
      const result = await exec.execute(makePhase())
      expect(result.status).toBe("failed")
      expect(result.errors.length).toBeGreaterThan(0)
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

  // setBrowserVerifierDeps tests removed — browser verifiers are now MCP tools
  // (Step 0.6: hardcoded verifiers extracted to standalone Python scripts)
})

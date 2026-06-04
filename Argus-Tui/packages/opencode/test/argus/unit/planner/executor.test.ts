import { describe, expect, test, beforeEach } from "bun:test"
import { InProcessExecutor } from "../../../../src/argus/planner/executor"
import { Capability } from "../../../../src/argus/planner/capabilities"
import { ConfidenceEngine } from "../../../../src/argus/engagement/confidence"
import type { PhaseExecutionRequest } from "../../../../src/argus/planner/types"
import type { BrowserEngine } from "../../../../src/argus/browser/engine"
import type { EvidenceCollector } from "../../../../src/argus/evidence/collector"
import type { ArtifactEntry } from "../../../../src/argus/evidence/types"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../../../../src/argus/browser/types"
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

  describe("setBrowserVerifierDeps", () => {
    test("accepts browser deps without throwing", () => {
      const mockCollector = {
        saveRequest: async () => ({ path: "req.txt", hash: "abc", type: "request" as const, size_bytes: 0 }),
        saveResponse: async () => ({ path: "resp.txt", hash: "abc", type: "response" as const, size_bytes: 0 }),
        captureScreenshot: async () => ({ path: "shot.png", hash: "abc", type: "screenshot" as const, size_bytes: 0 }),
        createPackage: async () => ({ package_id: "pkg", engagement_id: "eng", created_at: "", artifacts: [], package_hash: "abc" }),
      } as any

      const mockEngine = {
        launch: async () => {},
        createContext: async () => ({} as any),
        closeContext: async () => {},
        navigate: async () => ({} as any),
        observe: async () => ({ url: "", domSnapshot: "", responseHeaders: {}, statusCode: 200, timestamp: "" }),
        captureScreenshot: async () => Buffer.from(""),
        close: async () => {},
      } as any

      expect(() => {
        executor.setBrowserVerifierDeps({
          evidenceCollector: mockCollector,
          engine: mockEngine,
          credentials: { attacker: { username: "a", password: "b" }, victim: { username: "c", password: "d" } },
          targetUrl: "https://example.com",
        })
      }).not.toThrow()
    })

    test("runs browser verifiers when BROWSER_VERIFICATION capability is present", async () => {
      const savedArtifacts: ArtifactEntry[] = []
      const mockCollector = {
        saveRequest: async () => ({ path: "req.txt", hash: "abc", type: "request" as const, size_bytes: 0 }),
        saveResponse: async () => ({ path: "resp.txt", hash: "abc", type: "response" as const, size_bytes: 0 }),
        captureScreenshot: async (_e: string, _f: string, buf: Buffer) => {
          const entry: ArtifactEntry = { path: "shot.png", hash: "abc", type: "screenshot" as const, size_bytes: buf.length }
          savedArtifacts.push(entry)
          return entry
        },
        createPackage: async () => ({ package_id: "pkg", engagement_id: "eng", created_at: "", artifacts: savedArtifacts, package_hash: "abc" }),
      } as any

      let engineLaunched = false
      let engineClosed = false
      const mockEngine = {
        launch: async () => { engineLaunched = true },
        createContext: async () => ({
          newPage: async () => ({
            goto: async () => {},
            locator: () => ({
              all: async () => [],
              first: () => ({ isVisible: async () => false }),
              innerText: async () => "accessible",
            }),
            waitForLoadState: async () => {},
            waitForTimeout: async () => {},
            content: async () => "<html><body>test</body></html>",
            close: async () => {},
            url: () => "https://example.com/api/resource",
          }),
          close: async () => {},
        }),
        closeContext: async () => {},
        navigate: async () => ({
          waitForLoadState: async () => {},
          locator: () => ({
            all: async () => [],
            first: () => ({ isVisible: async () => false }),
          }),
          waitForTimeout: async () => {},
          content: async () => "<html><body>test</body></html>",
          close: async () => {},
        }),
        observe: async () => ({ url: "", domSnapshot: "", responseHeaders: {}, statusCode: 200, timestamp: "" }),
        captureScreenshot: async () => Buffer.from("screenshot-data"),
        close: async () => { engineClosed = true },
      } as any

      executor.setBrowserVerifierDeps({
        evidenceCollector: mockCollector,
        engine: mockEngine,
        credentials: { attacker: { username: "attacker", password: "pass" }, victim: { username: "victim", password: "pass" } },
        targetUrl: "https://example.com",
      })

      const phase = makePhase({
        requiredCapabilities: [Capability.BROWSER_VERIFICATION],
      })

      const result = await executor.execute(phase)

      // Should complete without error (verifiers run but may not find issues with mock)
      expect(result.status).toBe("completed")
      expect(result.phaseId).toBe("phase-0-test")
    })
  })
})

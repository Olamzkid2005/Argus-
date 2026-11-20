import { afterAll, beforeAll, describe, expect, mock, test } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"
import { resetTargetValidator } from "../../../src/argus/shared/target-validator"

let dir: string
let prevCwd: string

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), "argus-heal-"))
  writeFileSync(
    join(dir, "argus.config.yaml"),
    'security:\n  scope:\n    mode: allowlist\n    allowed_targets:\n      - example.com\n',
    "utf-8",
  )
  prevCwd = process.cwd()
  process.chdir(dir)
  process.env.ARGUS_AUTONOMOUS = "1"
  process.env.ARGUS_AUTO_APPROVE = "1"
  process.env.ARGUS_SCOPE_MODE = "allowlist"
  process.env.ARGUS_ALLOWED_TARGETS = "example.com"
  // The scope policy is a process-wide singleton that caches the config it read
  // from the first cwd it saw. Drop any instance an earlier test file in this
  // process already loaded, so this suite starts from its own config.
  resetTargetValidator()
})

afterAll(() => {
  process.chdir(prevCwd)
  delete process.env.ARGUS_AUTONOMOUS
  delete process.env.ARGUS_AUTO_APPROVE
  delete process.env.ARGUS_SCOPE_MODE
  delete process.env.ARGUS_ALLOWED_TARGETS
  // Restore the shared validator to the state the next test file expects. The
  // cached instance still holds this suite's allowlist otherwise, and the git
  // host check in the planner then rejects hosts every other test may use.
  resetTargetValidator()
  rmSync(dir, { recursive: true, force: true })
})

function makeDeps(opts: { toolsFor: (caps: string[]) => unknown[]; execute: any }) {
  const store = {
    createEngagement: mock(() => ({ id: "ENG-heal" })),
    getEngagement: mock(() => ({ id: "ENG-heal" })),
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
    getEvidenceByEngagement: mock(() => []),
    getFinding: mock(() => null),
    getFindingAnalysis: mock(() => null),
    getValidAnalysis: mock(() => null),
  }
  const phase = (id: string, caps: string[]) => ({
    phaseId: id,
    name: id,
    workflowName: "w",
    target: "https://example.com",
    requiredCapabilities: caps,
    config: {},
    previousPhaseResults: [],
  })
  const planner = {
    plan: mock(() => ({
      workflow: "test-workflow",
      phases: [phase("recon", ["web_recon"]), phase("scan", ["vulnerability_scanning"])],
      errorRecovery: { recon: "skip_and_continue" },
      planCreatedAt: new Date().toISOString(),
    })),
    replan: mock(() => null),
  }
  const executor = {
    execute: opts.execute,
    loadGates: mock(() => {}),
    setFeatureFlags: mock(() => {}),
    setExecutionOptions: mock(() => {}),
    setOnProgress: mock(() => {}),
    setToolConfig: mock(() => {}),
    getToolHealth: mock(() => []),
  }
  const bridge = {
    connect: mock(() => Promise.resolve()),
    disconnect: mock(() => Promise.resolve()),
    isHealthy: mock(() => Promise.resolve(true)),
    killChild: mock(() => {}),
    restartWorker: mock(() => Promise.resolve()),
    setRegistryTools: mock(() => {}),
    supervisor: { degraded: false },
    callTool: mock(async () => ({ success: true, data: {} })),
    phaseComplete: mock(() => Promise.resolve({ stop: false, next_capabilities: [], reasoning: "", fallback: false })),
    getAttackGraph: mock(() => Promise.resolve({ chains: [], chain_plans: [] })),
    acquireEngagementLock: mock(() => Promise.resolve({ acquired: true })),
    resetCircuitBreaker: mock(() => {}),
  }
  return {
    store,
    deps: {
      store: store as any,
      workflowRegistry: { loadAll: mock(() => []), getWorkflow: mock(() => null), findByCapabilities: mock(() => null), listWorkflows: mock(() => []), addWorkflow: mock(() => {}) } as any,
      toolRegistry: {
        load: mock(() => {}),
        selectBest: mock((caps: string[]) => opts.toolsFor(caps)),
        getTool: mock(() => undefined),
        getToolsByCapability: mock(() => []),
        getCapabilities: mock(() => []),
        // A real registry always lists its definitions; an empty one means the
        // definitions failed to load, which is not evidence of a coverage gap.
        listTools: mock(() => [{ name: "t" }]),
        findBestTools: mock(() => []),
        setConfig: mock(() => {}),
        getToolTimeout: mock(() => 120),
        setWorkerToolStatus: mock(() => []),
        getWorkerBlockReason: mock(() => undefined),
        isWorkerBlocked: mock(() => false),
      } as any,
      planner: planner as any,
      executor: executor as any,
      bridge: bridge as any,
      confidenceEngine: { promote: mock((f: any) => f.confidence ?? 0), shouldFinalize: mock(() => false) } as any,
      credStore: {
        load: mock(() => {}),
        getAllCredentials: mock(() => ({})),
        clear: mock(() => {}),
        getCredentials: mock(() => null),
        listRoles: mock(() => []),
        getDefaultRole: mock(() => undefined),
        getDefaultCredentials: mock(() => null),
      } as any,
    },
  }
}

const okResult = (id: string) => ({ phaseId: id, status: "completed", findings: [], artifacts: [], errors: [], durationMs: 1 })

describe("self-healing autonomous loop", () => {
  test("retries a throwing phase, then continues to the remaining phases", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    let reconAttempts = 0
    const execute = mock(async (phase: any) => {
      if (phase.phaseId === "recon") {
        reconAttempts++
        if (reconAttempts === 1) throw new Error("scanner exploded")
        return okResult(phase.phaseId)
      }
      return okResult(phase.phaseId)
    })
    const { deps } = makeDeps({ toolsFor: () => [{ name: "t" }], execute })
    const result = await new WorkflowRunner(deps).run({ target: "https://example.com" })

    expect(reconAttempts).toBe(2)                       // retried once
    expect(execute.mock.calls.map((c: any[]) => c[0].phaseId)).toEqual(["recon", "recon", "scan"])
    expect(result.success).toBe(true)
    expect(result.degradations).toBeUndefined()         // retry succeeded → nothing degraded
  })

  test("skips a phase whose capability has no installed tool and keeps going", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const execute = mock(async (phase: any) => okResult(phase.phaseId))
    const { store, deps } = makeDeps({
      toolsFor: (caps) => (caps.includes("web_recon") ? [] : [{ name: "t" }]),
      execute,
    })
    const result = await new WorkflowRunner(deps).run({ target: "https://example.com" })

    expect(execute.mock.calls.map((c: any[]) => c[0].phaseId)).toEqual(["scan"])
    expect(result.success).toBe(true)
    // A capability no tool can perform is a clean skip that names the
    // capability, not degraded coverage — otherwise a run missing one optional
    // tool reports Partial even though every runnable phase completed.
    expect(result.degradations ?? []).not.toContainEqual(expect.stringContaining("capability-missing"))
    expect(store.savePhase).toHaveBeenCalledWith("ENG-heal", expect.objectContaining({
      id: "recon",
      status: "SKIPPED",
      error: expect.stringContaining("web_recon"),
    }))
  })

  test("skips a phase that keeps throwing and reports the failure", async () => {
    const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
    const execute = mock(async (phase: any) => {
      if (phase.phaseId === "recon") throw new Error("scanner exploded")
      return okResult(phase.phaseId)
    })
    const { store, deps } = makeDeps({ toolsFor: () => [{ name: "t" }], execute })
    const result = await new WorkflowRunner(deps).run({ target: "https://example.com" })

    expect(result.success).toBe(true)
    expect(result.degradations?.some((d) => d.includes("phase-failed") && d.includes("scanner exploded"))).toBe(true)
    expect(store.savePhase).toHaveBeenCalledWith("ENG-heal", expect.objectContaining({ id: "recon", status: "FAILED" }))
    expect(execute.mock.calls.map((c: any[]) => c[0].phaseId)).toEqual(["recon", "recon", "scan"])
  })
})

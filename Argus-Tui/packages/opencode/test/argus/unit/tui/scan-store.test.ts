import { describe, it, expect, mock, beforeEach } from "bun:test"

mock.module("solid-js/store", () => {
  let state: any = {}
  return {
    createStore: (initial: any) => {
      state = { ...initial }
      return [
        state,
        (path: any, ...args: any[]) => {
          if (typeof path === "function") {
            Object.assign(state, path(state))
          } else if (typeof path === "object" && path !== null) {
            Object.assign(state, path)
          } else if (typeof path === "string") {
            if (args.length === 1) {
              if (typeof args[0] === "function") {
                state[path] = args[0](state[path] ?? [])
              } else {
                state[path] = args[0]
              }
            } else if (args.length === 2) {
              state[path] ??= []
              state[path][args[0]] = args[1]
            } else if (args.length === 3) {
              state[path] ??= []
              state[path][args[0]] ??= {}
              state[path][args[0]][args[1]] = args[2]
            }
          }
        },
      ]
    },
  }
})

const {
  getScanState,
  initScan,
  setActiveEngagement,
  addPhase,
  completePhase,
  appendLog,
  completeScan,
  setTotalFindings,
  addErrorHint,
  clearErrorHints,
  resetScan,
  handleProgressEvent,
} = await import("../../../../src/argus/tui/scan-store")

describe("scan-store", () => {
  beforeEach(() => {
    resetScan()
  })

  it("getScanState() returns initial state", () => {
    const state = getScanState()
    expect(state.target).toBe("")
    expect(state.engagementId).toBe("")
    expect(state.status).toBe("idle")
    expect(state.phases).toEqual([])
    expect(state.totalFindings).toBe(0)
    expect(state.currentPhase).toBe(0)
    expect(state.log).toEqual([])
    expect(state.startTime).toBe(0)
    expect(state.durationMs).toBe(0)
  })

  it("initScan() sets target, engagementId, status=running, startTime", () => {
    initScan("https://test.com", "eng-789")
    const state = getScanState()
    expect(state.target).toBe("https://test.com")
    expect(state.engagementId).toBe("eng-789")
    expect(state.status).toBe("running")
    expect(state.startTime).toBeGreaterThan(0)
  })

  it("addPhase() adds phase to list with status=running", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    const state = getScanState()
    expect(state.phases).toHaveLength(1)
    expect(state.phases[0].name).toBe("recon")
    expect(state.phases[0].index).toBe(0)
    expect(state.phases[0].total).toBe(3)
    expect(state.phases[0].status).toBe("running")
    expect(state.phases[0].findings).toBe(0)
    expect(state.phases[0].errors).toEqual([])
    expect(state.currentPhase).toBe(0)
  })

  it("completePhase() sets phase to completed, updates findings", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    completePhase("phase-0", 5, [])
    const state = getScanState()
    expect(state.phases[0].status).toBe("completed")
    expect(state.phases[0].findings).toBe(5)
    expect(state.totalFindings).toBe(5)
  })

  it("completePhase() sets phase to failed when errors present", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    completePhase("phase-0", 0, ["connection error"])
    const state = getScanState()
    expect(state.phases[0].status).toBe("failed")
    expect(state.phases[0].errors).toEqual(["connection error"])
  })

  it("completePhase() with explicit partial status", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    completePhase("phase-0", 3, ["some errors"], "partial")
    const state = getScanState()
    expect(state.phases[0].status).toBe("partial")
    expect(state.phases[0].findings).toBe(3)
  })

  it("completePhase() is idempotent — second call does not change status", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    completePhase("phase-0", 5, [], "completed")
    completePhase("phase-0", 0, ["error"], "failed")
    const state = getScanState()
    expect(state.phases[0].status).toBe("completed")
    expect(state.phases[0].findings).toBe(5)
  })

  it("appendLog() appends to log array", () => {
    initScan("https://test.com", "eng-1")
    appendLog("phase 1 starting")
    appendLog("phase 1 complete")
    const state = getScanState()
    expect(state.log).toEqual(["phase 1 starting", "phase 1 complete"])
  })

  it("completeScan(true) sets status=completed and durationMs", () => {
    initScan("https://test.com", "eng-1")
    completeScan(true)
    const state = getScanState()
    expect(state.status).toBe("completed")
    expect(state.durationMs).toBeGreaterThanOrEqual(0)
  })

  it("completeScan(false) sets status=failed", () => {
    initScan("https://test.com", "eng-1")
    completeScan(false)
    const state = getScanState()
    expect(state.status).toBe("failed")
  })

  it("setTotalFindings sets totalFindings count", () => {
    initScan("https://test.com", "eng-1")
    setTotalFindings(42)
    expect(getScanState().totalFindings).toBe(42)
  })

  // --- Findings accumulation tests (Fix 3: cumulative findings on resume) ---

  it("completePhase accumulates findings across multiple completed phases", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "p0", name: "recon", index: 0, total: 3 })
    addPhase({ id: "p1", name: "scan", index: 1, total: 3 })
    addPhase({ id: "p2", name: "analyze", index: 2, total: 3 })

    completePhase("p0", 10, [])
    expect(getScanState().totalFindings).toBe(10)

    completePhase("p1", 20, [])
    expect(getScanState().totalFindings).toBe(30)

    completePhase("p2", 5, [])
    expect(getScanState().totalFindings).toBe(35)
  })

  it("completePhase is idempotent for findings count — completing a phase twice doesn't add more", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "p0", name: "recon", index: 0, total: 2 })
    completePhase("p0", 10, [], "completed")
    expect(getScanState().totalFindings).toBe(10)
    // Second call should be a no-op (phase already completed)
    completePhase("p0", 10, [], "completed")
    expect(getScanState().totalFindings).toBe(10)
  })

  it("resume scenario: completePhase accumulates correctly without setTotalFindings double-counting", () => {
    // Simulates scan.tsx resume: phases are completed from DB state without calling setTotalFindings
    initScan("https://test.com", "eng-1")
    addPhase({ id: "p0", name: "recon", index: 0, total: 2 })
    addPhase({ id: "p1", name: "scan", index: 1, total: 2 })

    // Resume: restore phases from DB — completePhase adds per-phase counts
    completePhase("p0", 10, [], "completed")  // totalFindings: 0 + 10 = 10
    completePhase("p1", 5, [], "completed")   // totalFindings: 10 + 5 = 15

    // totalFindings should be exactly the sum of per-phase findings
    expect(getScanState().totalFindings).toBe(15)

    // If setTotalFindings with total from DB were called here (as in the original bug),
    // it would set totalFindings to the DB total = 15, which happens to be correct
    // IF the totals match. But if there are additional findings outside completed phases,
    // setTotalFindings would overwrite the accumulated sum incorrectly.
    // Since the fix removes the setTotalFindings call, totalFindings stays at 15.
  })

  it("finding from a failed phase does not affect findings total when errors are present", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "p0", name: "recon", index: 0, total: 2 })
    // The default resolution: errors.length > 0 && findings === 0 => status "failed"
    completePhase("p0", 0, ["connection error"])
    expect(getScanState().phases[0].status).toBe("failed")
    expect(getScanState().phases[0].findings).toBe(0)
    expect(getScanState().totalFindings).toBe(0)
  })

  it("addErrorHint adds error hints", () => {
    initScan("https://test.com", "eng-1")
    addErrorHint({ tool: "nuclei", summary: "test", detail: "detail" })
    expect(getScanState().errorHints).toHaveLength(1)
    expect(getScanState().errorHints[0].tool).toBe("nuclei")
  })

  it("clearErrorHints clears all error hints", () => {
    initScan("https://test.com", "eng-1")
    addErrorHint({ tool: "nuclei", summary: "test", detail: "detail" })
    clearErrorHints()
    expect(getScanState().errorHints).toHaveLength(0)
  })

  it("resetScan() resets to initial state", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    appendLog("something")
    resetScan()
    const state = getScanState()
    expect(state.target).toBe("")
    expect(state.engagementId).toBe("")
    expect(state.status).toBe("idle")
    expect(state.phases).toEqual([])
    expect(state.totalFindings).toBe(0)
    expect(state.log).toEqual([])
  })

  describe("handleProgressEvent", () => {
    it("phase_start adds a phase", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 3, phaseIndex: 0 })
      const state = getScanState()
      expect(state.phases).toHaveLength(1)
      expect(state.phases[0].name).toBe("recon")
    })

    it("phase_complete marks phase as completed", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 3, phaseIndex: 0 })
      await handleProgressEvent({ type: "phase_complete", phaseId: "p1", name: "recon", findings: 5, status: "COMPLETED" })
      expect(getScanState().phases[0].status).toBe("completed")
      expect(getScanState().phases[0].findings).toBe(5)
    })

    it("phase_complete with PARTIAL status marks phase as partial", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 3, phaseIndex: 0 })
      await handleProgressEvent({ type: "phase_complete", phaseId: "p1", name: "recon", findings: 3, status: "PARTIAL" })
      expect(getScanState().phases[0].status).toBe("partial")
    })

    it("phase_error marks phase as failed with error", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 3, phaseIndex: 0 })
      await handleProgressEvent({ type: "phase_error", phaseId: "p1", name: "recon", error: "connection failed" })
      expect(getScanState().phases[0].status).toBe("failed")
      expect(getScanState().phases[0].errors[0]).toBe("connection failed")
    })

    it("finding event appends log entry", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "finding", phaseId: "p1", severity: "HIGH", title: "SQL injection" })
      expect(getScanState().log[0]).toContain("SQL injection")
    })

    it("scan_complete sets status to completed", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "scan_complete", totalFindings: 10 })
      expect(getScanState().status).toBe("completed")
    })

    it("analysis_progress updates analysis counters", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "analysis_progress", current: 3, total: 10 })
      expect(getScanState().analysisCurrent).toBe(3)
      expect(getScanState().analysisTotal).toBe(10)
    })

    it("tool_start and tool_complete append log entries", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "tool_start", phaseId: "p1", tool: "nuclei" })
      await handleProgressEvent({ type: "tool_complete", phaseId: "p1", tool: "nuclei", findings: 5 })
      const log = getScanState().log
      expect(log[0]).toContain("nuclei")
      expect(log[1]).toContain("nuclei")
    })

    it("error_hint adds error hint and log entry", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "error_hint", tool: "nuclei", summary: "rate limited", detail: "API limit reached", docsUrl: "https://docs.example.com" })
      expect(getScanState().errorHints).toHaveLength(1)
      expect(getScanState().errorHints[0].tool).toBe("nuclei")
      expect(getScanState().errorHints[0].summary).toBe("rate limited")
      expect(getScanState().log[0]).toContain("rate limited")
    })

    it("handles progress events with engagementId scoping", async () => {
      initScan("https://a.com", "eng-a")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 1, phaseIndex: 0 }, "eng-a")
      expect(getScanState().engagementId).toBe("eng-a")
      expect(getScanState().phases).toHaveLength(1)
    })
  })

  describe("setActiveEngagement", () => {
    it("switches to a previously saved engagement state", () => {
      initScan("https://a.com", "eng-a")
      addPhase({ id: "p1", name: "recon", index: 0, total: 2 })
      initScan("https://b.com", "eng-b")
      expect(getScanState().engagementId).toBe("eng-b")
      setActiveEngagement("eng-a")
      expect(getScanState().engagementId).toBe("eng-a")
      expect(getScanState().target).toBe("https://a.com")
    })

    it("switching back to an engagement preserves its phases", () => {
      initScan("https://a.com", "eng-a")
      addPhase({ id: "p1", name: "recon", index: 0, total: 2 })
      initScan("https://b.com", "eng-b")
      addPhase({ id: "p2", name: "scan", index: 0, total: 1 })
      setActiveEngagement("eng-a")
      expect(getScanState().phases).toHaveLength(1)
      expect(getScanState().phases[0].name).toBe("recon")
    })
  })
})

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
  addPhase,
  completePhase,
  appendLog,
  completeScan,
  resetScan,
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
    completePhase(0, 5, [])
    const state = getScanState()
    expect(state.phases[0].status).toBe("completed")
    expect(state.phases[0].findings).toBe(5)
    expect(state.totalFindings).toBe(5)
  })

  it("completePhase() sets phase to failed when errors present", () => {
    initScan("https://test.com", "eng-1")
    addPhase({ id: "phase-0", name: "recon", index: 0, total: 3 })
    completePhase(0, 0, ["connection error"])
    const state = getScanState()
    expect(state.phases[0].status).toBe("failed")
    expect(state.phases[0].errors).toEqual(["connection error"])
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
})

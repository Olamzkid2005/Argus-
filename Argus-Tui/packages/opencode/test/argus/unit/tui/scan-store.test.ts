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
  setPlannerModel,
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
    expect(state.llmPlanningStatus).toBe("idle")
    expect(state.llmPlanningTargetAnalysis).toBe("")
    expect(state.llmPlanningSuggestions).toEqual([])
    expect(state.llmPlanningError).toBe("")
    expect(state.llmReplanEntries).toEqual([])
    expect(state.llmReplanStatus).toBe("idle")
    expect(state.llmPlanningModel).toBe("")
    expect(state.llmPlanningModelConfig).toBe("")
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

  it("setPlannerModel() updates llmPlanningModel and llmPlanningModelConfig", () => {
    initScan("https://test.com", "eng-1")
    expect(getScanState().llmPlanningModel).toBe("")
    expect(getScanState().llmPlanningModelConfig).toBe("")

    setPlannerModel("anthropic/claude-sonnet-4", "ARGUS_PLANNER_MODEL=claude-sonnet-4 (switched)")

    expect(getScanState().llmPlanningModel).toBe("anthropic/claude-sonnet-4")
    expect(getScanState().llmPlanningModelConfig).toBe("ARGUS_PLANNER_MODEL=claude-sonnet-4 (switched)")
  })

  it("setPlannerModel() can be called multiple times to update model", () => {
    initScan("https://test.com", "eng-1")
    setPlannerModel("openai/gpt-4o-mini", "config-a")
    expect(getScanState().llmPlanningModel).toBe("openai/gpt-4o-mini")

    setPlannerModel("openai/gpt-4o", "config-b")
    expect(getScanState().llmPlanningModel).toBe("openai/gpt-4o")
    expect(getScanState().llmPlanningModelConfig).toBe("config-b")
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

    it("verification_start sets verification status to running", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "verification_start", phaseId: "p1", total: 5 })
      const state = getScanState()
      expect(state.verificationStatus).toBe("running")
      expect(state.verificationTotal).toBe(5)
      expect(state.verificationCurrent).toBe(0)
      expect(state.verificationPassed).toBe(0)
      expect(state.verificationFailed).toBe(0)
    })

    it("verification_progress updates verification counters", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "verification_start", phaseId: "p1", total: 3 })
      await handleProgressEvent({ type: "verification_progress", phaseId: "p1", current: 1, total: 3, findingTitle: "XSS", findingSubtype: "xss" })
      const state = getScanState()
      expect(state.verificationCurrent).toBe(1)
      expect(state.verificationTotal).toBe(3)
      expect(state.log.some(l => l.includes("XSS"))).toBe(true)
    })

    it("verification_complete sets verification status and results", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "verification_start", phaseId: "p1", total: 3 })
      await handleProgressEvent({ type: "verification_complete", phaseId: "p1", passed: 2, failed: 1, total: 3 })
      const state = getScanState()
      expect(state.verificationStatus).toBe("completed")
      expect(state.verificationPassed).toBe(2)
      expect(state.verificationFailed).toBe(1)
      expect(state.log.some(l => l.includes("passed"))).toBe(true)
    })

    it("handles progress events with engagementId scoping", async () => {
      initScan("https://a.com", "eng-a")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 1, phaseIndex: 0 }, "eng-a")
      expect(getScanState().engagementId).toBe("eng-a")
      expect(getScanState().phases).toHaveLength(1)
    })

    // ── LLM Planning events ────────────────────────────────────────

    it("llm_planning_start sets status=running, clears previous state, appends log", async () => {
      initScan("https://test.com", "eng-1")
      // Set some pre-existing state to verify it gets cleared
      await handleProgressEvent({ type: "llm_planning_complete", phase: "initial", targetAnalysis: "old analysis", suggestions: [{ capabilities: ["web_recon"], reasoning: "old reason" }], llmModel: "openai/gpt-4o-old", modelEnvDescription: "old config" })
      expect(getScanState().llmPlanningStatus).toBe("completed")

      await handleProgressEvent({ type: "llm_planning_start", phase: "initial" })
      const state = getScanState()
      expect(state.llmPlanningStatus).toBe("running")
      expect(state.llmPlanningTargetAnalysis).toBe("")
      expect(state.llmPlanningSuggestions).toEqual([])
      expect(state.llmPlanningError).toBe("")
      expect(state.log.some(l => l.includes("LLM analysis started"))).toBe(true)
    })

    it("llm_planning_start with replan phase appends correct log", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "llm_planning_start", phase: "replan" })
      expect(getScanState().llmPlanningStatus).toBe("running")
      expect(getScanState().log.some(l => l.includes("replan planning"))).toBe(true)
    })

    it("llm_planning_complete sets status=completed, stores analysis and suggestions", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "llm_planning_start", phase: "initial" })
      await handleProgressEvent({
        type: "llm_planning_complete",
        phase: "initial",
        llmModel: "openai/gpt-4o-mini",
        modelEnvDescription: "ARGUS_PLANNER_MODEL=gpt-4o-mini (default)",
        targetAnalysis: "Web application with login form. Recommend standard assessment phases.",
        suggestions: [
          { capabilities: ["web_recon", "technology_detection"], reasoning: "Identify tech stack and attack surface." },
          { capabilities: ["vulnerability_scanning", "template_scanning"], reasoning: "Automated vulnerability detection." },
          { capabilities: ["browser_verification"], reasoning: "Browser-based exploit verification." },
        ],
      })
      const state = getScanState()
      expect(state.llmPlanningStatus).toBe("completed")
      expect(state.llmPlanningTargetAnalysis).toBe("Web application with login form. Recommend standard assessment phases.")
      expect(state.llmPlanningSuggestions).toHaveLength(3)
      expect(state.llmPlanningSuggestions[0].capabilities).toEqual(["web_recon", "technology_detection"])
      expect(state.llmPlanningSuggestions[0].reasoning).toBe("Identify tech stack and attack surface.")
      expect(state.llmPlanningSuggestions[1].capabilities).toEqual(["vulnerability_scanning", "template_scanning"])
      expect(state.llmPlanningSuggestions[2].capabilities).toEqual(["browser_verification"])
      // Verify llmPlanningModel and llmPlanningModelConfig are stored from event fields
      expect(state.llmPlanningModel).toBe("openai/gpt-4o-mini")
      expect(state.llmPlanningModelConfig).toBe("ARGUS_PLANNER_MODEL=gpt-4o-mini (default)")
      expect(state.log.some(l => l.includes("3 phase suggestion(s)"))).toBe(true)
    })

    it("llm_planning_complete with empty suggestions still updates state", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "llm_planning_start", phase: "initial" })
      await handleProgressEvent({
        type: "llm_planning_complete",
        phase: "initial",
        llmModel: "openai/gpt-4o-mini",
        modelEnvDescription: "",
        targetAnalysis: "",
        suggestions: [],
      })
      const state = getScanState()
      expect(state.llmPlanningStatus).toBe("completed")
      expect(state.llmPlanningTargetAnalysis).toBe("")
      expect(state.llmPlanningSuggestions).toEqual([])
      expect(state.log.some(l => l.includes("0 phase suggestion(s)"))).toBe(true)
    })

    it("llm_planning_error sets status=failed, stores error message", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "llm_planning_start", phase: "initial" })
      await handleProgressEvent({
        type: "llm_planning_error",
        phase: "initial",
        error: "API rate limit exceeded",
      })
      const state = getScanState()
      expect(state.llmPlanningStatus).toBe("failed")
      expect(state.llmPlanningError).toBe("API rate limit exceeded")
      expect(state.log.some(l => l.includes("API rate limit exceeded"))).toBe(true)
    })

    it("llm_planning_error is non-blocking — other state unaffected", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 3, phaseIndex: 0 })
      await handleProgressEvent({
        type: "llm_planning_error",
        phase: "initial",
        error: "LLM unavailable",
      })
      const state = getScanState()
      expect(state.llmPlanningStatus).toBe("failed")
      expect(state.phases).toHaveLength(1)  // phases still intact
      expect(state.phases[0].name).toBe("recon")
    })

    // ── LLM Replan events ───────────────────────────────────────────

    it("llm_replan_analysis with capabilities appends entry and log", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "https://test.com",
        reasoning: "SQL injection found in login form. Recommend deeper testing.",
        suggestedCapabilities: ["sqli_detection", "post_exploitation"],
        stopAssessment: false,
        llmModel: "openai/gpt-4o-mini",
      })
      const state = getScanState()
      expect(state.llmReplanStatus).toBe("completed")
      expect(state.llmReplanEntries).toHaveLength(1)
      expect(state.llmReplanEntries[0].phaseName).toBe("https://test.com")
      expect(state.llmReplanEntries[0].reasoning).toBe("SQL injection found in login form. Recommend deeper testing.")
      expect(state.llmReplanEntries[0].suggestedCapabilities).toEqual(["sqli_detection", "post_exploitation"])
      expect(state.llmReplanEntries[0].stopAssessment).toBe(false)
      expect(state.llmReplanEntries[0].llmModel).toBe("openai/gpt-4o-mini")
      expect(state.log.some(l => l.includes("sqli_detection, post_exploitation"))).toBe(true)
    })

    it("llm_replan_analysis with stopAssessment=true logs stop recommendation", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "https://test.com",
        reasoning: "All critical findings have been identified and verified. Assessment is complete.",
        suggestedCapabilities: [],
        stopAssessment: true,
        llmModel: "openai/gpt-4o-mini",
      })
      const state = getScanState()
      expect(state.llmReplanEntries).toHaveLength(1)
      expect(state.llmReplanEntries[0].stopAssessment).toBe(true)
      expect(state.log.some(l => l.includes("stopping assessment"))).toBe(true)
    })

    it("llm_replan_analysis with empty capabilities does not log capabilities line", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "https://test.com",
        reasoning: "No additional capabilities needed.",
        suggestedCapabilities: [],
        stopAssessment: false,
        llmModel: "openai/gpt-4o-mini",
      })
      const state = getScanState()
      expect(state.llmReplanEntries).toHaveLength(1)
      // When stopAssessment=false and capabilities is empty, neither log branch fires
      expect(state.log.some(l => l.includes("stopping assessment"))).toBe(false)
      expect(state.log.some(l => l.includes("suggests next capabilities"))).toBe(false)
    })

    it("multiple llm_replan_analysis events accumulate entries", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "phase-recon",
        reasoning: "Found open ports, recommend scanning.",
        suggestedCapabilities: ["port_scanning"],
        stopAssessment: false,
        llmModel: "openai/gpt-4o-mini",
      })
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "phase-scan",
        reasoning: "Found SQL injection, recommend exploitation.",
        suggestedCapabilities: ["sqli_detection", "post_exploitation"],
        stopAssessment: false,
        llmModel: "anthropic/claude-sonnet-4",
      })
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "phase-exploit",
        reasoning: "All findings addressed.",
        suggestedCapabilities: [],
        stopAssessment: true,
        llmModel: "openai/gpt-4o-mini",
      })
      const state = getScanState()
      expect(state.llmReplanEntries).toHaveLength(3)
      expect(state.llmReplanEntries[0].phaseName).toBe("phase-recon")
      expect(state.llmReplanEntries[1].phaseName).toBe("phase-scan")
      expect(state.llmReplanEntries[2].phaseName).toBe("phase-exploit")
      expect(state.llmReplanEntries[2].stopAssessment).toBe(true)
      // Latest status is "completed" (set by the last event)
      expect(state.llmReplanStatus).toBe("completed")
    })

    it("llm_replan_analysis does not interfere with other scan state", async () => {
      initScan("https://test.com", "eng-1")
      await handleProgressEvent({ type: "phase_start", phaseId: "p1", name: "recon", total: 3, phaseIndex: 0 })
      await handleProgressEvent({
        type: "llm_replan_analysis",
        label: "phase-recon",
        reasoning: "Continue with scanning.",
        suggestedCapabilities: ["vulnerability_scanning"],
        stopAssessment: false,
        llmModel: "openai/gpt-4o-mini",
      })
      const state = getScanState()
      expect(state.phases).toHaveLength(1) // phases unchanged
      expect(state.phases[0].status).toBe("running")
      expect(state.llmReplanEntries).toHaveLength(1)
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

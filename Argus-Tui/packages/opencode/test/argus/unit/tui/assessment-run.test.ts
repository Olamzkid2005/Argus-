import { beforeEach, describe, expect, test } from "bun:test"
import type { WorkflowRunOptions, WorkflowRunResult } from "../../../../src/argus/workflow-runner"
import { isAssessmentRunning, requestAssessmentStop, runTuiAssessment } from "../../../../src/argus/tui/assessment-run"
import { getScanState, resetScan } from "../../../../src/argus/tui/scan-store"

function result(overrides: Partial<WorkflowRunResult> = {}): WorkflowRunResult {
  return {
    engagementId: "ENG-1",
    findings: 0,
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    info: 0,
    durationMs: 0,
    success: true,
    allFindings: [],
    ...overrides,
  }
}

beforeEach(() => resetScan())

describe("runTuiAssessment", () => {
  test("streams structured progress into the scan store", async () => {
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-7", target: options.target, created: true })
        await options.onProgress?.({ type: "phase_start", phaseId: "phase-0", name: "recon", total: 2, phaseIndex: 0 })
        await options.onProgress?.({
          type: "phase_complete",
          phaseId: "phase-0",
          name: "recon",
          findings: 2,
          status: "COMPLETED",
        })
        await options.onProgress?.({ type: "scan_complete", totalFindings: 2 })
        return result({ engagementId: "ENG-7", findings: 2 })
      },
    }

    const outcome = await runTuiAssessment(
      { target: "https://lab.example", model: "openai/gpt-4o-mini" },
      { runner, navigate: false },
    )

    const state = getScanState()
    expect(outcome.status).toBe("completed")
    expect(outcome.engagementId).toBe("ENG-7")
    expect(state.engagementId).toBe("ENG-7")
    expect(state.target).toBe("https://lab.example")
    expect(state.phases).toHaveLength(1)
    expect(state.phases[0]!.name).toBe("recon")
    expect(state.phases[0]!.status).toBe("completed")
    expect(state.totalFindings).toBe(2)
    expect(state.status).toBe("completed")
    expect(state.llmPlanningModel).toBe("openai/gpt-4o-mini")
  })

  test("routes plain progress strings to the scan log", async () => {
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-8", target: options.target, created: true })
        await options.onProgress?.("✓ Engagement created")
        return result({ engagementId: "ENG-8" })
      },
    }

    await runTuiAssessment({ target: "https://lab.example" }, { runner, navigate: false })
    expect(getScanState().log).toContain("✓ Engagement created")
  })

  test("marks the scan failed when the run fails", async () => {
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-9", target: options.target, created: true })
        return result({ engagementId: "ENG-9", success: false, error: "worker crashed" })
      },
    }

    const outcome = await runTuiAssessment({ target: "https://lab.example" }, { runner, navigate: false })
    expect(outcome.status).toBe("failed")
    expect(getScanState().status).toBe("failed")
    expect(getScanState().log.join("\n")).toContain("worker crashed")
  })

  test("marks the scan failed when the service throws", async () => {
    const runner = {
      async run(): Promise<WorkflowRunResult> {
        throw new Error("worker refused to start")
      },
    }

    await expect(runTuiAssessment({ target: "https://lab.example" }, { runner, navigate: false })).rejects.toThrow(
      "worker refused to start",
    )
    expect(getScanState().status).toBe("failed")
    expect(getScanState().log.join("\n")).toContain("worker refused to start")
  })

  test("a late failure wins over an emitted scan_complete", async () => {
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-10", target: options.target, created: true })
        await options.onProgress?.({ type: "scan_complete", totalFindings: 1 })
        return result({ engagementId: "ENG-10", success: false, error: "late failure" })
      },
    }

    await runTuiAssessment({ target: "https://lab.example" }, { runner, navigate: false })
    expect(getScanState().status).toBe("failed")
  })

  test("reports partial coverage when a phase errors but the run succeeds", async () => {
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-11", target: options.target, created: true })
        await options.onProgress?.({ type: "phase_error", phaseId: "phase-0", name: "recon", error: "tool timeout" })
        return result({ engagementId: "ENG-11", success: true })
      },
    }

    const outcome = await runTuiAssessment({ target: "https://lab.example" }, { runner, navigate: false })
    expect(outcome.status).toBe("partial")
    expect(getScanState().status).toBe("partial")
  })

  test("reports a stopped run without claiming success", async () => {
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-12", target: options.target, created: true })
        return result({ engagementId: "ENG-12", success: false, stopped: true })
      },
    }

    const outcome = await runTuiAssessment({ target: "https://lab.example" }, { runner, navigate: false })
    expect(outcome.status).toBe("stopped")
    expect(getScanState().status).toBe("stopped")
  })

  test("a duplicate submission joins the in-flight run instead of launching twice", async () => {
    let runs = 0
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const runner = {
      async run(options: WorkflowRunOptions) {
        runs++
        options.onEngagement?.({ id: "ENG-13", target: options.target, created: true })
        await gate
        return result({ engagementId: "ENG-13" })
      },
    }

    const first = runTuiAssessment({ target: "https://dup.example" }, { runner, navigate: false })
    const second = runTuiAssessment({ target: "https://dup.example" }, { runner, navigate: false })

    expect(second).toBe(first)
    release()
    await Promise.all([first, second])
    expect(runs).toBe(1)
  })

  test("a stop request is visible to the runner and cleared after the run", async () => {
    let observed = false
    const runner = {
      async run(options: WorkflowRunOptions) {
        options.onEngagement?.({ id: "ENG-14", target: options.target, created: true })
        expect(isAssessmentRunning("https://stop.example")).toBe(true)
        expect(requestAssessmentStop("https://stop.example")).toBe(true)
        observed = options.shouldStop?.() ?? false
        return result({ engagementId: "ENG-14", success: false, stopped: true })
      },
    }

    await runTuiAssessment({ target: "https://stop.example" }, { runner, navigate: false })
    expect(observed).toBe(true)
    expect(isAssessmentRunning("https://stop.example")).toBe(false)
  })

  test("assessment modules never reference the coding agent", async () => {
    const sources = ["assessment/service.ts", "tui/assessment-run.ts"]
    for (const source of sources) {
      const text = await Bun.file(new URL(`../../../../src/argus/${source}`, import.meta.url)).text()
      expect(text).not.toContain("sdk.client.session.prompt")
      expect(text).not.toContain("sdk.client")
    }

    const prompt = await Bun.file(
      new URL("../../../../src/cli/cmd/tui/component/prompt/index.tsx", import.meta.url),
    ).text()
    expect(prompt).toContain("runTuiAssessment")
    expect(prompt).not.toContain("formatFindingsSummary")
    expect(prompt).not.toContain("store.createEngagement")
  })
})

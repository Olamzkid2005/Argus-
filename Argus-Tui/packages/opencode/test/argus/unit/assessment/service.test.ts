import { describe, expect, test } from "bun:test"
import { Feature } from "../../../../src/argus/config/feature-flags"
import type { WorkflowRunOptions, WorkflowRunResult } from "../../../../src/argus/workflow-runner"
import { parseAssessmentArgs, runAssessment } from "../../../../src/argus/assessment/service"

function emptyResult(overrides: Partial<WorkflowRunResult> = {}): WorkflowRunResult {
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

function stubRunner(result: WorkflowRunResult = emptyResult()) {
  const calls: WorkflowRunOptions[] = []
  return {
    calls,
    runner: {
      async run(options: WorkflowRunOptions) {
        calls.push(options)
        return result
      },
    },
  }
}

function modelSpy() {
  const calls: string[] = []
  return {
    calls,
    switchModel(model: string) {
      calls.push(model)
    },
  }
}

describe("assessment service", () => {
  test("launches the runner exactly once with the requested policy", async () => {
    const { calls, runner } = stubRunner()
    await runAssessment(
      {
        target: "  https://lab.example  ",
        mode: "assess",
        cacheMode: "no_cache",
        verbose: true,
        credsPath: "/tmp/creds.json",
        features: { [Feature.LLM_FINDING_ANALYSIS]: true },
        engagementId: "ENG-9",
      },
      {},
      { runner },
    )

    expect(calls).toHaveLength(1)
    const options = calls[0]!
    expect(options.target).toBe("https://lab.example")
    expect(options.useLLM).toBe(true)
    expect(options.cacheMode).toBe("no_cache")
    expect(options.verbose).toBe(true)
    expect(options.credsPath).toBe("/tmp/creds.json")
    expect(options.engagementId).toBe("ENG-9")
    expect(options.features?.[Feature.LLM_FINDING_ANALYSIS]).toBe(true)
  })

  test("recon mode disables LLM planning and an explicit override wins", async () => {
    const first = stubRunner()
    await runAssessment({ target: "https://lab.example", mode: "recon" }, {}, { runner: first.runner })
    expect(first.calls[0]!.useLLM).toBe(false)

    const second = stubRunner()
    await runAssessment({ target: "https://lab.example", mode: "recon", useLLM: true }, {}, { runner: second.runner })
    expect(second.calls[0]!.useLLM).toBe(true)
  })

  test("hands the selected model to the planner before launching", async () => {
    const order: string[] = []
    const models = modelSpy()
    const { runner } = stubRunner()
    await runAssessment(
      { target: "https://lab.example", model: "openai/gpt-4o-mini" },
      {},
      {
        runner: {
          async run(options) {
            order.push("run")
            return runner.run(options)
          },
        },
        switchModel: (model) => {
          order.push("model")
          models.switchModel(model)
        },
      },
    )

    expect(models.calls).toEqual(["openai/gpt-4o-mini"])
    expect(order).toEqual(["model", "run"])
  })

  test("does not switch models when none is selected", async () => {
    const models = modelSpy()
    const { runner } = stubRunner()
    await runAssessment({ target: "https://lab.example" }, {}, { runner, switchModel: models.switchModel })
    expect(models.calls).toEqual([])
  })

  test("forwards the cooperative stop predicate", async () => {
    const { calls, runner } = stubRunner()
    const shouldStop = () => true
    await runAssessment({ target: "https://lab.example", shouldStop }, {}, { runner })
    expect(calls[0]!.shouldStop).toBe(shouldStop)
  })

  test("forwards progress and engagement hooks to the runner", async () => {
    const { calls, runner } = stubRunner()
    const onProgress = () => {}
    const onEngagement = () => {}
    await runAssessment({ target: "https://lab.example" }, { onProgress, onEngagement }, { runner })

    expect(calls[0]!.onProgress).toBe(onProgress)
    expect(calls[0]!.onEngagement).toBe(onEngagement)
  })

  test("rejects an empty target without launching", async () => {
    const { calls, runner } = stubRunner()
    await expect(runAssessment({ target: "   " }, {}, { runner })).rejects.toThrow("authorized target")
    expect(calls).toHaveLength(0)
  })

  test("returns a failed result unchanged", async () => {
    const failed = emptyResult({ success: false, error: "worker crashed" })
    const { runner } = stubRunner(failed)
    const result = await runAssessment({ target: "https://lab.example" }, {}, { runner })
    expect(result.success).toBe(false)
    expect(result.error).toBe("worker crashed")
  })
})

describe("parseAssessmentArgs", () => {
  test("strips flags from the target", () => {
    expect(parseAssessmentArgs("https://lab.example --no-cache --verbose")).toEqual({
      target: "https://lab.example",
      cacheMode: "no_cache",
      verbose: true,
    })
  })

  test("supports the flag first", () => {
    expect(parseAssessmentArgs("--refresh-cache https://lab.example").target).toBe("https://lab.example")
  })

  test("--no-cache wins when both cache flags are present", () => {
    expect(parseAssessmentArgs("https://lab.example --no-cache --refresh-cache").cacheMode).toBe("no_cache")
  })

  test("returns an empty target when only flags are supplied", () => {
    expect(parseAssessmentArgs("--no-cache").target).toBe("")
  })
})

import { afterEach, describe, expect, it } from "bun:test"
import type { AssessmentRequest } from "../../../src/argus/assessment/service"
import { findArgusTuiCommand, setAssessmentLauncher } from "../../../src/argus/tui-commands"
import type { TuiAssessmentOutcome } from "../../../src/argus/tui/assessment-run"

function outcome(success = true, error?: string): TuiAssessmentOutcome {
  return { result: { success, error } } as unknown as TuiAssessmentOutcome
}

describe("assess/recon command handlers", () => {
  afterEach(() => setAssessmentLauncher(undefined))

  it("/assess launches the shared assessment service exactly once", async () => {
    const calls: AssessmentRequest[] = []
    setAssessmentLauncher(async (request) => {
      calls.push(request)
      return outcome()
    })

    const output = await findArgusTuiCommand("assess")!.handler("https://lab.example --no-cache")

    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({
      target: "https://lab.example",
      mode: "assess",
      cacheMode: "no_cache",
    })
    expect(output).toContain("Assessment completed")
  })

  it("/scan uses the same path as /assess", async () => {
    const calls: AssessmentRequest[] = []
    setAssessmentLauncher(async (request) => {
      calls.push(request)
      return outcome()
    })

    const output = await findArgusTuiCommand("scan")!.handler("https://lab.example")

    expect(calls).toHaveLength(1)
    expect(calls[0]!.mode).toBe("assess")
    expect(output).toContain("Assessment completed")
  })

  it("/recon launches recon mode", async () => {
    const calls: AssessmentRequest[] = []
    setAssessmentLauncher(async (request) => {
      calls.push(request)
      return outcome()
    })

    const output = await findArgusTuiCommand("recon")!.handler("https://lab.example")

    expect(calls).toHaveLength(1)
    expect(calls[0]!.mode).toBe("recon")
    expect(output).toContain("Recon completed")
  })

  it("reports usage and never launches without a target", async () => {
    let launched = false
    setAssessmentLauncher(async () => {
      launched = true
      return outcome()
    })

    const output = await findArgusTuiCommand("assess")!.handler("--no-cache")

    expect(launched).toBe(false)
    expect(output).toContain("Usage: /assess")
  })

  it("/stop reports when nothing is running", async () => {
    const output = await findArgusTuiCommand("stop")!.handler("")
    expect(output).toContain("No assessment is running")
  })

  it("surfaces a failed run as an error instead of reporting success", async () => {
    setAssessmentLauncher(async () => outcome(false, "worker crashed"))

    await expect(findArgusTuiCommand("assess")!.handler("https://lab.example")).rejects.toThrow("worker crashed")
  })
})

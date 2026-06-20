import { describe, expect, test, jest, mock } from "bun:test"
import type { WorkflowRunResult } from "../../../../src/argus/workflow-runner"

// Mock WorkflowRunner and ReportGenerator
const mockRun = mock<(opts: any) => Promise<WorkflowRunResult>>()
const mockGenerateMarkdown = mock<(findings: any[], engagementId: string, target: string, type: string) => string>()

mock.module("../../../../src/argus/workflow-runner", () => ({
  WorkflowRunner: mock(() => ({
    run: mockRun,
  })),
}))

mock.module("../../../../src/argus/reporting/generator", () => ({
  ReportGenerator: mock(() => ({
    generateMarkdown: mockGenerateMarkdown,
  })),
}))

const makeEmptyResult = (overrides: Partial<WorkflowRunResult> = {}): WorkflowRunResult => ({
  allFindings: [],
  engagementId: "eng-1",
  phaseResults: {},
  toolsExecuted: new Set(),
  replanCount: 0,
  ...overrides,
})

describe("assessCommand", () => {
  beforeEach(() => {
    mockRun.mockReset()
    mockGenerateMarkdown.mockReset()
    // Manually clear the module cache so re-imports get fresh mocks
  })

  test("delegates to WorkflowRunner.run with target", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com")

    expect(mockRun).toHaveBeenCalledTimes(1)
    const callOpts = mockRun.mock.calls[0][0]
    expect(callOpts.target).toBe("https://example.com")
  })

  test("passes useLLM option to WorkflowRunner", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", { useLLM: false })

    expect(mockRun.mock.calls[0][0].useLLM).toBe(false)
  })

  test("passes workersPath option to WorkflowRunner", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", { workersPath: "/custom/path" })

    expect(mockRun.mock.calls[0][0].workersPath).toBe("/custom/path")
  })

  test("passes cacheMode option to WorkflowRunner", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", { cacheMode: "no_cache" })

    expect(mockRun.mock.calls[0][0].cacheMode).toBe("no_cache")
  })

  test("does NOT write markdown report when writeReport is false", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", { writeReport: false })

    expect(mockGenerateMarkdown).not.toHaveBeenCalled()
  })

  test("writes markdown report by default when findings exist", async () => {
    const findings = [{ id: "f-1", title: "Test", severity: "HIGH" }]
    mockRun.mockResolvedValue(makeEmptyResult({ allFindings: findings }))
    mockGenerateMarkdown.mockReturnValue("# Report content")
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com")

    expect(mockGenerateMarkdown).toHaveBeenCalledWith(
      findings,
      "eng-1",
      "https://example.com",
      "assessment",
    )
  })

  test("calls onProgress callback for string events", async () => {
    mockRun.mockImplementation(async (opts: any) => {
      opts.onProgress?.("Custom progress message")
      return makeEmptyResult()
    })
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const onProgress = mock<(event: any) => void>()

    await assessCommand("https://example.com", { onProgress })

    expect(onProgress).toHaveBeenCalledWith("Custom progress message")
  })

  test("returns the WorkflowRunResult", async () => {
    const expectedResult = makeEmptyResult({ engagementId: "eng-42" })
    mockRun.mockResolvedValue(expectedResult)
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    const result = await assessCommand("https://example.com")

    expect(result.engagementId).toBe("eng-42")
  })

  test("handles empty target string gracefully", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await expect(assessCommand("")).resolves.toBeDefined()
  })

  test("forwards errors from WorkflowRunner", async () => {
    mockRun.mockRejectedValue(new Error("Worker crashed"))
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await expect(assessCommand("https://example.com")).rejects.toThrow("Worker crashed")
  })
})

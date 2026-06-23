import { describe, expect, test, beforeEach, afterEach, mock } from "bun:test"
import { WorkflowRunner } from "../../../../src/argus/workflow-runner"
import { ReportGenerator } from "../../../../src/argus/reporting/generator"
import type { WorkflowRunResult } from "../../../../src/argus/workflow-runner"

// Use prototype-level mocking instead of mock.module to avoid cross-file leakage

const mockRun = mock<(opts: any) => Promise<WorkflowRunResult>>()
const mockGenerateMarkdown = mock<(findings: any[], engagementId: string, target: string, type: string) => string>()

let originalRun: any
let originalGenerateMarkdown: any

beforeEach(() => {
  // Save originals and patch prototype methods
  originalRun = WorkflowRunner.prototype.run
  originalGenerateMarkdown = ReportGenerator.prototype.generateMarkdown

  WorkflowRunner.prototype.run = mockRun as any
  ReportGenerator.prototype.generateMarkdown = mockGenerateMarkdown as any

  mockRun.mockReset()
  mockGenerateMarkdown.mockReset()
})

// Restore prototypes after each test to prevent leaking
afterEach(() => {
  if (originalRun) WorkflowRunner.prototype.run = originalRun
  if (originalGenerateMarkdown) ReportGenerator.prototype.generateMarkdown = originalGenerateMarkdown
})

const makeEmptyResult = (overrides: Partial<WorkflowRunResult> = {}): WorkflowRunResult => ({
  allFindings: [],
  engagementId: "eng-1",
  toolsExecuted: new Set(),
  replanCount: 0,
  ...overrides,
} as unknown as WorkflowRunResult)

describe("assessCommand", () => {
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
    const findings: any[] = [{ id: "f-1", title: "Test", severity: "HIGH" }]
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

  test("passes verbose option to WorkflowRunner", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", { verbose: true })

    expect(mockRun.mock.calls[0][0].verbose).toBe(true)
  })

  test("passes multiple combined options simultaneously", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", {
      cacheMode: "refresh",
      credsPath: "/path/to/creds.json",
      features: { approval_gates: true },
      verbose: true,
      useLLM: false,
    })

    const opts = mockRun.mock.calls[0][0]
    expect(opts.cacheMode).toBe("refresh")
    expect(opts.credsPath).toBe("/path/to/creds.json")
    expect(opts.features).toEqual({ approval_gates: true })
    expect(opts.verbose).toBe(true)
    expect(opts.useLLM).toBe(false)
  })

  test("default onProgress is a function that writes to stderr without crashing", async () => {
    const originalStderrWrite = process.stderr.write
    const written: string[] = []
    process.stderr.write = (chunk: any) => { written.push(String(chunk)); return true }

    try {
      mockRun.mockImplementation(async (opts: any) => {
        // Trigger all the cliProgress branches
        opts.onProgress?.("Raw string message")
        opts.onProgress?.({ type: "phase_start", phaseIndex: 0, total: 3, name: "recon" })
        opts.onProgress?.({ type: "phase_complete", phaseId: "p1", name: "recon", findings: 5, status: "completed" })
        opts.onProgress?.({ type: "phase_error", phaseId: "p1", name: "recon", error: "timeout" })
        opts.onProgress?.({ type: "finding", severity: "4", title: "Critical bug" })
        opts.onProgress?.({ type: "phase_replan", count: 2 })
        opts.onProgress?.({ type: "scan_complete", totalFindings: 10 })
        opts.onProgress?.({ type: "unexpected_event", data: "ignored" } as any)
        return makeEmptyResult()
      })

      const { assessCommand } = await import("../../../../src/argus/commands/assess")
      await assessCommand("https://example.com")

      // Should not crash and should write expected strings to stderr
      expect(written.length).toBeGreaterThan(0)
      expect(written.some((w) => w.includes("Raw string message"))).toBe(true)
      expect(written.some((w) => w.includes("Phase 1/3"))).toBe(true)
      expect(written.some((w) => w.includes("5 finding(s)"))).toBe(true)
      expect(written.some((w) => w.includes("timeout"))).toBe(true)
      expect(written.some((w) => w.includes("[CRITICAL] Critical bug"))).toBe(true)
      expect(written.some((w) => w.includes("2 new phase(s)"))).toBe(true)
      expect(written.some((w) => w.includes("10 total finding(s)"))).toBe(true)
    } finally {
      process.stderr.write = originalStderrWrite
    }
  })

  test("forwards errors from WorkflowRunner", async () => {
    mockRun.mockRejectedValue(new Error("Worker crashed"))
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await expect(assessCommand("https://example.com")).rejects.toThrow("Worker crashed")
  })

  test("passes credsPath option to WorkflowRunner", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { credsPath: "/path/to/creds.json" })
    expect(mockRun.mock.calls[0][0].credsPath).toBe("/path/to/creds.json")
  })

  test("passes features option to WorkflowRunner", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const features = { approval_gates: true }
    await assessCommand("https://example.com", { features })
    expect(mockRun.mock.calls[0][0].features).toEqual(features)
  })

  test("does NOT write markdown report when no findings exist", async () => {
    const emptyResult = makeEmptyResult()
    mockRun.mockResolvedValue(emptyResult)
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")
    expect(mockGenerateMarkdown).not.toHaveBeenCalled()
  })

  test("calls onProgress for ProgressEvent objects", async () => {
    mockRun.mockImplementation(async (opts: any) => {
      opts.onProgress?.({ type: "phase_complete", phaseId: "p1", name: "recon", findings: 5, status: "completed" })
      return makeEmptyResult()
    })
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const onProgress = mock<(event: any) => void>()
    await assessCommand("https://example.com", { onProgress })
    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ type: "phase_complete" })
    )
  })

  test("sets default onProgress when not provided", async () => {
    mockRun.mockImplementation(async (opts: any) => {
      expect(typeof opts.onProgress).toBe("function")
      return makeEmptyResult()
    })
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")
  })

  test("returns empty findings summary for empty results", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const result: any = await assessCommand("https://example.com")
    expect(result.allFindings).toEqual([])
    expect(result.engagementId).toBe("eng-1")
    expect(result.replanCount).toBe(0)
  })

  test("passes cacheMode 'normal' explicitly", async () => {
    mockRun.mockResolvedValue(makeEmptyResult())
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    await assessCommand("https://example.com", { cacheMode: "normal" })

    expect(mockRun.mock.calls[0][0].cacheMode).toBe("normal")
  })

  test("forwards WorkflowRunResult with toolsExecuted set", async () => {
    const opts: any = {
      toolsExecuted: new Set(["nmap", "nuclei"]),
      allFindings: [{ id: "f-1", title: "XSS", severity: "HIGH" } as any],
    }
    mockRun.mockResolvedValue(makeEmptyResult(opts))
    const { assessCommand } = await import("../../../../src/argus/commands/assess")

    const output: any = await assessCommand("https://example.com")

    expect(output.toolsExecuted).toBeDefined()
    expect(output.toolsExecuted.size).toBe(2)
    expect(output.allFindings).toHaveLength(1)
  })
})

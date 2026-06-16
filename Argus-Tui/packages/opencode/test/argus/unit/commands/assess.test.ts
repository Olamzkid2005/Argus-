import { describe, expect, test, beforeAll, afterEach, mock } from "bun:test"

const mockRunResult = {
  engagementId: "ENG-test",
  findings: 2,
  critical: 1,
  high: 1,
  medium: 0,
  low: 0,
  durationMs: 100,
  success: true,
  allFindings: [
    { id: "f1", title: "Critical SQL Injection", severity: 4, confidence: 3, status: "CONFIRMED" as const, description: "SQLi in login", tool: "nuclei", phase: "vuln_scan", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    { id: "f2", title: "XSS Vulnerability", severity: 3, confidence: 2, status: "CONFIRMED" as const, description: "XSS in search", tool: "nuclei", phase: "vuln_scan", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  ],
}

let capturedOnProgress: ((event: any) => void) | null = null
let capturedRunOptions: any = null
let mockRunOverrides: any = null

describe("cliProgress", () => {
  beforeAll(() => {
    mock.module("../../../../src/argus/workflow-runner", () => ({
      WorkflowRunner: mock(() => ({
        run: mock(async (opts: any) => {
          capturedRunOptions = opts
          capturedOnProgress = opts.onProgress
          return mockRunResult
        }),
      })),
    }))

    mock.module("../../../../src/argus/reporting/generator", () => ({
      ReportGenerator: mock(() => ({
        generateMarkdown: mock(() => "# Report\n\nTest report content"),
      })),
    }))
  })

  afterEach(() => {
    capturedOnProgress = null
    capturedRunOptions = null
    mockRunOverrides = null
  })

  test("writes string events to stderr", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!("custom string message")

    expect(writes.some(w => w.includes("custom string message"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("writes phase_start event to stderr", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "phase_start", phaseId: "p1", name: "Recon", total: 3, phaseIndex: 0 })

    expect(writes.some(w => w.includes("Phase 1/3"))).toBe(true)
    expect(writes.some(w => w.includes("Recon"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("writes phase_complete event to stderr", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "phase_complete", phaseId: "p1", name: "Recon", findings: 3, status: "COMPLETED" })

    expect(writes.some(w => w.includes("✓") && w.includes("3 finding"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("writes phase_error event to stderr", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "phase_error", phaseId: "p1", name: "Recon", error: "Connection timeout" })

    expect(writes.some(w => w.includes("✗") && w.includes("Connection timeout"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("writes finding event with severity label to stderr", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "finding", phaseId: "p1", severity: "3", title: "SQL Injection" })

    expect(writes.some(w => w.includes("[HIGH]") && w.includes("SQL Injection"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("resolves severity 0 to INFO label", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "finding", phaseId: "p1", severity: "0", title: "Info-level note" })

    expect(writes.some(w => w.includes("[INFO]") && w.includes("Info-level note"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("falls back to raw severity string when parseInt fails", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "finding", phaseId: "p1", severity: "5", title: "Out-of-range severity" })

    expect(writes.some(w => w.includes("[5]") && w.includes("Out-of-range severity"))).toBe(true)
    process.stderr.write = origWrite
  })

  test("writes scan_complete event to stderr", async () => {
    const writes: string[] = []
    const origWrite = process.stderr.write.bind(process.stderr)
    process.stderr.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    capturedOnProgress!({ type: "scan_complete", totalFindings: 5 })

    expect(writes.some(w => w.includes("5 total finding"))).toBe(true)
    process.stderr.write = origWrite
  })
})

describe("assessCommand", () => {
  beforeAll(() => {
    mock.module("../../../../src/argus/workflow-runner", () => ({
      WorkflowRunner: mock(() => ({
        run: mock(async (opts: any) => {
          capturedRunOptions = opts
          capturedOnProgress = opts.onProgress
          return mockRunOverrides ?? mockRunResult
        }),
      })),
    }))

    mock.module("../../../../src/argus/reporting/generator", () => ({
      ReportGenerator: mock(() => ({
        generateMarkdown: mock(() => "# Report\n\nTest report content"),
      })),
    }))
  })

  afterEach(() => {
    mockRunOverrides = null
    capturedRunOptions = null
    capturedOnProgress = null
  })

  test("generates and writes report to stdout when findings exist", async () => {
    const stdoutWrites: string[] = []
    const origStdout = process.stdout.write.bind(process.stdout)
    process.stdout.write = mock((chunk: unknown) => { stdoutWrites.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const result = await assessCommand("https://example.com")

    expect(stdoutWrites.some(w => w.includes("Report"))).toBe(true)
    expect(result).toEqual(mockRunResult)
    expect(result.allFindings.length).toBe(2)
    process.stdout.write = origStdout
  })

  test("does not write report when no findings", async () => {
    mockRunOverrides = {
      engagementId: "ENG-empty",
      findings: 0, critical: 0, high: 0, medium: 0, low: 0,
      durationMs: 50, success: true,
      allFindings: [],
    }

    const stdoutWrites: string[] = []
    const origStdout = process.stdout.write.bind(process.stdout)
    process.stdout.write = mock((chunk: unknown) => { stdoutWrites.push(String(chunk)); return true })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const result = await assessCommand("https://example.com")

    expect(stdoutWrites.length).toBe(0)
    expect(result.findings).toBe(0)
    process.stdout.write = origStdout
  })

  test("passes through custom onProgress callback", async () => {
    const progressEvents: any[] = []
    const customOnProgress = mock((event: any) => { progressEvents.push(event) })

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { onProgress: customOnProgress })

    expect(capturedRunOptions.onProgress).toBe(customOnProgress)
  })

  test("uses cliProgress as default onProgress when none provided", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    expect(capturedRunOptions.onProgress).toBeDefined()
    expect(typeof capturedRunOptions.onProgress).toBe("function")
  })

  test("passes target to runner", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://my-target.com")

    expect(capturedRunOptions.target).toBe("https://my-target.com")
  })

  test("passes useLLM option to runner", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { useLLM: false })

    expect(capturedRunOptions.useLLM).toBe(false)
  })

  test("passes workersPath option to runner", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { workersPath: "/tmp/custom_mcp_server.py" })

    expect(capturedRunOptions.workersPath).toBe("/tmp/custom_mcp_server.py")
  })

  test("passes credsPath option to runner", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { credsPath: "/tmp/creds.json" })

    expect(capturedRunOptions.credsPath).toBe("/tmp/creds.json")
  })

  test("passes cacheMode option to runner", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { cacheMode: "no_cache" })

    expect(capturedRunOptions.cacheMode).toBe("no_cache")
  })

  test("passes features option to runner", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { features: { llm_finding_analysis: false } })

    expect(capturedRunOptions.features).toEqual({ llm_finding_analysis: false })
  })

  test("returns the workflow result directly", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const result = await assessCommand("https://example.com")

    expect(result).toHaveProperty("engagementId", "ENG-test")
    expect(result).toHaveProperty("findings", 2)
    expect(result).toHaveProperty("success", true)
  })
})

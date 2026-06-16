import { describe, expect, test, mock } from "bun:test"

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

type RunFn = (opts: any) => Promise<typeof mockRunResult>
let latestRunFn: RunFn = async (opts: any) => {
  if (opts.onProgress) {
    opts.onProgress("custom string message")
  }
  return mockRunResult
}

mock.module("../../../../src/argus/workflow-runner", () => ({
  WorkflowRunner: mock(() => ({
    run: mock(async (opts: any) => latestRunFn(opts)),
  })),
}))

mock.module("../../../../src/argus/reporting/generator", () => ({
  ReportGenerator: mock(() => ({
    generateMarkdown: mock(() => "# Report\n\nTest report content"),
  })),
}))

describe("assessCommand", () => {
  test("returns workflow result", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const result = await assessCommand("https://example.com")
    expect(result).toHaveProperty("engagementId", "ENG-test")
    expect(result.success).toBe(true)
  })

  test("generates report when findings exist", async () => {
    const writes: string[] = []
    const origWrite = process.stdout.write.bind(process.stdout)
    process.stdout.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true }) as any

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    expect(writes.some(w => w.includes("Report"))).toBe(true)
    process.stdout.write = origWrite
  })

  test("skips report generation when no findings", async () => {
    latestRunFn = async () => ({ ...mockRunResult, findings: 0, allFindings: [] })
    const writes: string[] = []
    const origWrite = process.stdout.write.bind(process.stdout)
    process.stdout.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true }) as any

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    expect(writes).toHaveLength(0)
    process.stdout.write = origWrite
    latestRunFn = async (opts: any) => {
      if (opts.onProgress) opts.onProgress("custom string message")
      return mockRunResult
    }
  })

  test("passes target to runner", async () => {
    let capturedTarget = ""
    latestRunFn = async (opts: any) => { capturedTarget = opts.target; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")
    expect(capturedTarget).toBe("https://example.com")
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("passes useLLM option", async () => {
    let captured: any = null
    latestRunFn = async (opts: any) => { captured = opts; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { useLLM: false })
    expect(captured.useLLM).toBe(false)
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("passes workersPath option", async () => {
    let captured: any = null
    latestRunFn = async (opts: any) => { captured = opts; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { workersPath: "/custom/path/mcp_server.py" })
    expect(captured.workersPath).toBe("/custom/path/mcp_server.py")
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("passes credsPath option", async () => {
    let captured: any = null
    latestRunFn = async (opts: any) => { captured = opts; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { credsPath: "/path/creds.json" })
    expect(captured.credsPath).toBe("/path/creds.json")
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("passes cacheMode option as no_cache", async () => {
    let captured: any = null
    latestRunFn = async (opts: any) => { captured = opts; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { cacheMode: "no_cache" })
    expect(captured.cacheMode).toBe("no_cache")
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("passes cacheMode option as refresh", async () => {
    let captured: any = null
    latestRunFn = async (opts: any) => { captured = opts; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { cacheMode: "refresh" })
    expect(captured.cacheMode).toBe("refresh")
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("forwards custom onProgress callback", async () => {
    const events: any[] = []
    latestRunFn = async (opts: any) => {
      opts.onProgress?.({ type: "finding", phaseId: "p1", severity: "HIGH", title: "test" })
      return mockRunResult
    }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", {
      onProgress: (event) => { events.push(event) },
    })
    expect(events.length).toBeGreaterThan(0)
    expect(events[0].type).toBe("finding")
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })

  test("passes features option", async () => {
    let captured: any = null
    latestRunFn = async (opts: any) => { captured = opts; return mockRunResult }
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", { features: { llm_finding_analysis: false } })
    expect(captured.features).toEqual({ llm_finding_analysis: false })
    latestRunFn = async (opts: any) => { if (opts.onProgress) opts.onProgress("custom string message"); return mockRunResult }
  })
})

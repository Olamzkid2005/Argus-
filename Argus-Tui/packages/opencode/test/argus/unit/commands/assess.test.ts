import { describe, expect, test, mock } from "bun:test"

const mockRunResult = {
  engagementId: "ENG-mock",
  findings: 2,
  critical: 1,
  high: 1,
  medium: 0,
  low: 0,
  durationMs: 100,
  success: true,
  allFindings: [
    { id: "f1", title: "Finding 1", severity: 4, confidence: 3, status: "CONFIRMED" as const, description: "desc", tool: "nuclei", phase: "vuln_scan", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    { id: "f2", title: "Finding 2", severity: 3, confidence: 2, status: "CONFIRMED" as const, description: "desc", tool: "nuclei", phase: "vuln_scan", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  ],
}

mock.module("../../../../src/argus/workflow-runner", () => ({
  WorkflowRunner: mock(() => ({
    run: mock(async (opts: any) => {
      if (opts.onProgress) {
        opts.onProgress("starting")
        opts.onProgress({ type: "finding", phaseId: "p1", severity: "HIGH", title: "test" })
      }
      return mockRunResult
    }),
  })),
}))

describe("assessCommand", () => {
  test("returns workflow result", async () => {
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    const result = await assessCommand("https://example.com")
    expect(result).toHaveProperty("engagementId", "ENG-mock")
    expect(result.success).toBe(true)
  })

  test("generates report to stdout when findings exist", async () => {
    const writes: string[] = []
    const orig = process.stdout.write.bind(process.stdout)
    process.stdout.write = mock((chunk: unknown) => { writes.push(String(chunk)); return true }) as any

    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com")

    expect(writes.length).toBeGreaterThan(0)
    expect(writes.some(w => String(w).includes("Report"))).toBe(true)
    process.stdout.write = orig
  })

  test("forwards custom onProgress callback", async () => {
    const events: any[] = []
    const { assessCommand } = await import("../../../../src/argus/commands/assess")
    await assessCommand("https://example.com", {
      onProgress: (event) => { events.push(event) },
    })
    expect(events.length).toBeGreaterThan(0)
  })
})

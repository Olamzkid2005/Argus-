import { describe, expect, test } from "bun:test"
import type { ProgressEvent, ProgressCallback } from "../../../src/argus/shared/progress"

describe("ProgressEvent types", () => {
  test("phase_start event has correct shape", () => {
    const event: ProgressEvent = { type: "phase_start", phaseId: "p1", name: "recon", total: 5, phaseIndex: 0 }
    expect(event.type).toBe("phase_start")
    expect(event.phaseId).toBe("p1")
    expect(event.name).toBe("recon")
    expect(event.total).toBe(5)
    expect(event.phaseIndex).toBe(0)
  })

  test("phase_complete event has correct shape", () => {
    const event: ProgressEvent = { type: "phase_complete", phaseId: "p1", name: "recon", findings: 3, status: "COMPLETED" }
    expect(event.type).toBe("phase_complete")
    expect(event.findings).toBe(3)
  })

  test("phase_error event has error field", () => {
    const event: ProgressEvent = { type: "phase_error", phaseId: "p1", name: "recon", error: "connection failed" }
    expect(event.error).toBe("connection failed")
  })

  test("tool_start event has tool field", () => {
    const event: ProgressEvent = { type: "tool_start", phaseId: "p1", tool: "nuclei" }
    expect(event.tool).toBe("nuclei")
  })

  test("tool_complete event has tool and findings", () => {
    const event: ProgressEvent = { type: "tool_complete", phaseId: "p1", tool: "nuclei", findings: 5 }
    expect(event.findings).toBe(5)
  })

  test("finding event has severity and title", () => {
    const event: ProgressEvent = { type: "finding", phaseId: "p1", severity: "HIGH", title: "SQL injection" }
    expect(event.severity).toBe("HIGH")
    expect(event.title).toBe("SQL injection")
  })

  test("scan_complete event has totalFindings", () => {
    const event: ProgressEvent = { type: "scan_complete", totalFindings: 42 }
    expect(event.totalFindings).toBe(42)
  })

  test("ProgressCallback is assignable", () => {
    const cb: ProgressCallback = (event: ProgressEvent) => {
      if (event.type === "scan_complete") {
        expect(event.totalFindings).toBeGreaterThanOrEqual(0)
      }
    }
    cb({ type: "scan_complete", totalFindings: 10 })
  })
})

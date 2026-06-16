import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { join } from "path"
import { mkdtempSync, rmSync } from "fs"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"
import type { ProgressEvent } from "../../../../src/argus/shared/progress"

let dbDir: string
let store: EngagementStore
let engId: string

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "report-test-"))
  store = new EngagementStore(join(dbDir, "test.db"))
  const eng = store.createEngagement("https://example.com", "assignment")
  engId = eng.id
  store.saveFindings(eng.id, [
    {
      id: "find-1",
      title: "XSS",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "",
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ])
})

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

describe("reportCommand", () => {
  test('returns "Engagement not found" when engagement doesn\'t exist', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const result = await reportCommand("eng-missing", "markdown", store)
    expect(result).toContain("not found")
  })

  test("generates markdown by default", async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const eId = engagements[0].id
    const result = await reportCommand(eId, "markdown", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  test('generates JSON when format="json"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const eId = engagements[0].id
    const result = await reportCommand(eId, "json", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  test('generates SARIF when format="sarif"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const eId = engagements[0].id
    const result = await reportCommand(eId, "sarif", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  test('generates HTML when format="html"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const eId = engagements[0].id
    const result = await reportCommand(eId, "html", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })
})

describe("enhanceReportWithAnalysis", () => {
  test("processes 10 findings in concurrency-limited batches (max 3), emits progress, and handles failures gracefully", async () => {
    // Create engagement with 10 findings
    const testDir = mkdtempSync(join(tmpdir(), "enhance-report-test-"))
    const testStore = new EngagementStore(join(testDir, "test.db"))
    const testEng = testStore.createEngagement("https://test-target.com", "assignment")

    const findings = Array.from({ length: 10 }, (_, i) => ({
      id: `test-find-${i + 1}`,
      title: `Test Finding ${i + 1}`,
      severity: 2,
      confidence: 2,
      status: "PENDING" as const,
      description: `Description for finding ${i + 1}`,
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }))
    testStore.saveFindings(testEng.id, findings)

    // Track concurrency
    let currentConcurrent = 0
    let maxConcurrent = 0
    let callCount = 0
    const warnCalls: unknown[][] = []

    // Mock console.warn
    const origWarn = console.warn
    console.warn = (...args: unknown[]) => {
      warnCalls.push(args)
    }

    try {
      // Create mock analyzer to inject directly
      const mockAnalyzer = {
        async analyze(finding: any, _evidence: any[]) {
          currentConcurrent++
          if (currentConcurrent > maxConcurrent) maxConcurrent = currentConcurrent
          callCount++

          await new Promise((r) => setTimeout(r, 20))

          currentConcurrent--

          if (finding.id === "test-find-5") {
            throw new Error("Simulated analysis failure")
          }

          return {
            findingId: finding.id,
            explanation: `Analysis for ${finding.id}`,
            impact: ["Potential data exposure", "Unauthorized access risk"],
            remediation: ["Apply input validation", "Use parameterized queries"],
            model: "test-model",
            generatedAt: Date.now(),
            findingUpdatedAt: Date.now(),
          }
        },
      }

      const { enhanceReportWithAnalysis } = await import("../../../../src/argus/commands/report")

      const progressEvents: ProgressEvent[] = []
      const onProgress = (event: ProgressEvent) => {
        progressEvents.push(event)
      }

      const results = await enhanceReportWithAnalysis(testEng.id, onProgress, mockAnalyzer, testStore)

      // 1. Concurrency limited to 3
      expect(maxConcurrent).toBeLessThanOrEqual(3)
      expect(callCount).toBe(10)

      // 2. Progress events: before each batch (0,3,6,9) + final (10) = 5 events
      expect(progressEvents.length).toBe(5)
      expect(progressEvents[0]).toEqual({ type: "analysis_progress", current: 0, total: 10 })
      expect(progressEvents[1]).toEqual({ type: "analysis_progress", current: 3, total: 10 })
      expect(progressEvents[2]).toEqual({ type: "analysis_progress", current: 6, total: 10 })
      expect(progressEvents[3]).toEqual({ type: "analysis_progress", current: 9, total: 10 })
      expect(progressEvents[4]).toEqual({ type: "analysis_progress", current: 10, total: 10 })

      // 3. Failed analysis doesn't block — 9 results (finding 5 failed)
      expect(results.length).toBe(9)
      expect(results.find((r) => r.findingId === "test-find-5")).toBeUndefined()

      // 4. All other findings present
      const resultIds = results.map((r) => r.findingId).sort()
      const expectedIds = Array.from({ length: 10 }, (_, i) => `test-find-${i + 1}`)
        .filter((id) => id !== "test-find-5")
        .sort()
      expect(resultIds).toEqual(expectedIds)

      // 5. Each result has required fields
      for (const r of results) {
        expect(r.explanation).toBeTruthy()
        expect(r.impact.length).toBeGreaterThan(0)
        expect(r.remediation.length).toBeGreaterThan(0)
        expect(r.model).toBe("test-model")
        expect(r.generatedAt).toBeGreaterThan(0)
      }

      // 6. console.warn was called for the failure
      expect(
        warnCalls.some(
          (args) => args.some((a) => typeof a === "string" && a.includes("Analysis failed"))
        )
      ).toBe(true)

    } finally {
      console.warn = origWarn
      try { rmSync(testDir, { recursive: true, force: true }) } catch {}
    }
  })

  test("returns empty array when engagement has no findings", async () => {
    const testDir = mkdtempSync(join(tmpdir(), "enhance-report-empty-"))
    const testStore = new EngagementStore(join(testDir, "test.db"))
    const testEng = testStore.createEngagement("https://empty-target.com", "assignment")

    try {
      const { enhanceReportWithAnalysis } = await import("../../../../src/argus/commands/report")
      const results = await enhanceReportWithAnalysis(testEng.id, undefined, undefined, testStore)
      expect(results).toEqual([])
    } finally {
      try { rmSync(testDir, { recursive: true, force: true }) } catch {}
    }
  })
})

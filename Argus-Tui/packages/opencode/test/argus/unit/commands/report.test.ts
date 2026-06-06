import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { join } from "path"
import { mkdtempSync, rmSync } from "fs"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"

let dbDir: string
let store: EngagementStore

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "report-test-"))
  store = new EngagementStore(join(dbDir, "test.db"))
  const eng = store.createEngagement("https://example.com", "assignment")
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
    const engId = engagements[0].id
    const result = await reportCommand(engId, "markdown", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  test('generates JSON when format="json"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const engId = engagements[0].id
    const result = await reportCommand(engId, "json", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  test('generates SARIF when format="sarif"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const engId = engagements[0].id
    const result = await reportCommand(engId, "sarif", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  test('generates HTML when format="html"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const engagements = store.listEngagements()
    const engId = engagements[0].id
    const result = await reportCommand(engId, "html", store)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })
})

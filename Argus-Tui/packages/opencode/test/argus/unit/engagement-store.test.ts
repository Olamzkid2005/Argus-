import { describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import type { FindingAnalysis } from "../../../src/argus/shared/types"

let dbDir: string

function makeStore(): { store: EngagementStore; cleanup: () => void } {
  if (!dbDir) dbDir = mkdtempSync(join(tmpdir(), "argus-engagement-store-test-"))
  const dbPath = join(dbDir, `test-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`)
  const store = new EngagementStore(dbPath)
  return { store, cleanup: () => { try { rmSync(dbPath) } catch {} } }
}

function makeAnalysis(findingId: string, overrides?: Partial<FindingAnalysis>): FindingAnalysis {
  return {
    findingId,
    explanation: "Test explanation",
    impact: ["impact1", "impact2"],
    remediation: ["fix1"],
    model: "test-model",
    generatedAt: Date.now(),
    findingUpdatedAt: Date.now(),
    ...overrides,
  }
}

function seedFinding(store: EngagementStore, id: string, engagementId: string) {
  store.saveFindings(engagementId, [{
    id,
    title: "Test Finding",
    severity: 2,
    confidence: 2,
    status: "PENDING",
    description: "test",
    tool: "nuclei",
    phase: "phase-1",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }])
}

describe("EngagementStore — analysis methods", () => {
  test("saveFindingAnalysis + getFindingAnalysis roundtrip", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    seedFinding(store, "find-1", eng.id)
    const analysis = makeAnalysis("find-1")
    store.saveFindingAnalysis(analysis)
    const loaded = store.getFindingAnalysis("find-1")
    expect(loaded).not.toBeNull()
    expect(loaded!.findingId).toBe("find-1")
    expect(loaded!.explanation).toBe("Test explanation")
    expect(loaded!.impact).toEqual(["impact1", "impact2"])
    expect(loaded!.remediation).toEqual(["fix1"])
    expect(loaded!.model).toBe("test-model")
    cleanup()
  })

  test("getFindingAnalysis returns null for unknown ID", () => {
    const { store, cleanup } = makeStore()
    const result = store.getFindingAnalysis("nonexistent")
    expect(result).toBeNull()
    cleanup()
  })

  test("deleteFindingAnalysis removes analysis", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    seedFinding(store, "find-2", eng.id)
    store.saveFindingAnalysis(makeAnalysis("find-2"))
    store.deleteFindingAnalysis("find-2")
    const result = store.getFindingAnalysis("find-2")
    expect(result).toBeNull()
    cleanup()
  })

  test("getValidAnalysis returns non-stale data", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    seedFinding(store, "find-3", eng.id)
    const analysis = makeAnalysis("find-3", { findingUpdatedAt: Date.now() })
    store.saveFindingAnalysis(analysis)
    const valid = store.getValidAnalysis("find-3")
    expect(valid).not.toBeNull()
    expect(valid!.findingId).toBe("find-3")
    cleanup()
  })

  test("getValidAnalysis returns null with stale data", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const futureDate = new Date(Date.now() + 100000).toISOString()
    seedFinding(store, "find-4", eng.id)
    // Manually update the finding's updated_at to be in the future
    const { Database } = require("bun:sqlite")
    const sqlite = new Database(store.dbPath)
    sqlite.exec(`UPDATE findings SET updated_at = ${Date.now() + 100000} WHERE id = 'find-4'`)
    sqlite.close()
    const analysis = makeAnalysis("find-4", { findingUpdatedAt: Date.now() - 50000 })
    store.saveFindingAnalysis(analysis)
    const valid = store.getValidAnalysis("find-4")
    expect(valid).toBeNull()
    cleanup()
  })

  test("getValidAnalysis returns null with no cached data", () => {
    const { store, cleanup } = makeStore()
    const result = store.getValidAnalysis("nonexistent")
    expect(result).toBeNull()
    cleanup()
  })

  test("getFindingAnalysis handles malformed JSON gracefully", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    seedFinding(store, "corrupt-id", eng.id)
    const { Database } = require("bun:sqlite")
    const sqlite = new Database(store.dbPath)
    sqlite.exec(`
      INSERT OR REPLACE INTO finding_analysis (finding_id, explanation, impact, remediation, model, generated_at, finding_updated_at)
      VALUES ('corrupt-id', 'explanation', 'not-valid-json', '["fix1"]', 'test', ${Date.now()}, ${Date.now()})
    `)
    sqlite.close()
    const result = store.getFindingAnalysis("corrupt-id")
    expect(result).toBeNull()
    cleanup()
  })
})

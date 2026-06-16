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

describe("EngagementStore — engagement CRUD", () => {
  test("createEngagement returns engagement with correct fields", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    expect(eng.id).toMatch(/^ENG-/)
    expect(eng.target).toBe("https://test.com")
    expect(eng.workflow).toBe("assessment")
    expect(eng.status).toBe("CREATED")
    expect(eng.workflowVersion).toBe(1)
    expect(eng.schemaVersion).toBe(1)
    cleanup()
  })

  test("createEngagement can specify custom workflow", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "full_assessment")
    expect(eng.workflow).toBe("full_assessment")
    cleanup()
  })

  test("getEngagement returns null for nonexistent ID", () => {
    const { store, cleanup } = makeStore()
    const result = store.getEngagement("NONEXISTENT")
    expect(result).toBeNull()
    cleanup()
  })

  test("getEngagement returns engagement for existing ID", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.id).toBe(eng.id)
    expect(loaded!.target).toBe("https://test.com")
    cleanup()
  })

  test("updateStatus transitions status correctly", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    expect(store.getEngagement(eng.id)!.status).toBe("RUNNING")
    store.updateStatus(eng.id, "COMPLETED")
    expect(store.getEngagement(eng.id)!.status).toBe("COMPLETED")
    cleanup()
  })

  test("listEngagements returns all engagements ordered by recency", () => {
    const { store, cleanup } = makeStore()
    const e1 = store.createEngagement("https://a.com", "assessment")
    const e2 = store.createEngagement("https://b.com", "assessment")
    const list = store.listEngagements()
    expect(list.length).toBeGreaterThanOrEqual(2)
    expect(list.map(e => e.id)).toContain(e1.id)
    expect(list.map(e => e.id)).toContain(e2.id)
    cleanup()
  })

  test("listEngagements returns empty when no engagements exist", () => {
    const { store, cleanup } = makeStore()
    const list = store.listEngagements()
    expect(list).toHaveLength(0)
    cleanup()
  })

  test("saveEngagement updates all fields", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveEngagement({ ...eng, target: "https://updated.com", workflowVersion: 2 })
    const loaded = store.getEngagement(eng.id)
    expect(loaded!.target).toBe("https://updated.com")
    expect(loaded!.workflowVersion).toBe(2)
    cleanup()
  })
})

describe("EngagementStore — phase CRUD", () => {
  function makePhaseRecord(engagementId: string, index: number) {
    return {
      id: `phase-${index}-test`,
      engagementId,
      name: `phase-${index}`,
      status: "PENDING" as "PENDING" | "RUNNING" | "COMPLETED" | "PARTIAL" | "FAILED" | "SKIPPED",
      capabilities: ["web_recon"],
      executionMode: "sequential" as const,
      replanCycle: false,
      startedAt: undefined as string | undefined,
    }
  }

  test("savePhases persists phases and getPhases retrieves them", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const phases = [makePhaseRecord(eng.id, 0), makePhaseRecord(eng.id, 1)]
    store.savePhases(eng.id, phases)
    const loaded = store.getPhases(eng.id)
    expect(loaded).toHaveLength(2)
    expect(loaded[0].id).toMatch(/^phase-/)
    expect(loaded[0].engagementId).toBe(eng.id)
    expect(loaded[0].status).toBe("PENDING")
    cleanup()
  })

  test("savePhase updates existing phase", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const phase = makePhaseRecord(eng.id, 0)
    store.savePhases(eng.id, [phase])
    phase.status = "RUNNING"
    phase.startedAt = new Date().toISOString()
    store.savePhase(eng.id, phase)
    const loaded = store.getPhases(eng.id)
    expect(loaded[0].status).toBe("RUNNING")
    expect(loaded[0].startedAt).toBeDefined()
    cleanup()
  })

  test("getPhases returns empty for engagement with no phases", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const loaded = store.getPhases(eng.id)
    expect(loaded).toHaveLength(0)
    cleanup()
  })
})

describe("EngagementStore — findings CRUD", () => {
  function makeFinding(id: string) {
    return {
      id,
      title: `Finding ${id}`,
      severity: 2,
      confidence: 2,
      status: "PENDING" as const,
      description: "test description",
      tool: "nuclei",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
  }

  test("saveFindings persists findings and getFindings retrieves them", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveFindings(eng.id, [makeFinding("find-1"), makeFinding("find-2")])
    const loaded = store.getFindings(eng.id)
    expect(loaded).toHaveLength(2)
    expect(loaded.map(f => f.id)).toContain("find-1")
    cleanup()
  })

  test("getFinding returns null for nonexistent finding", () => {
    const { store, cleanup } = makeStore()
    const result = store.getFinding("nonexistent")
    expect(result).toBeNull()
    cleanup()
  })

  test("getFinding returns finding for existing ID", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveFindings(eng.id, [makeFinding("find-get-1")])
    const result = store.getFinding("find-get-1")
    expect(result).not.toBeNull()
    expect(result!.title).toBe("Finding find-get-1")
    cleanup()
  })

  test("saveFindings updates existing finding on conflict", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveFindings(eng.id, [makeFinding("find-upd")])
    store.saveFindings(eng.id, [{ ...makeFinding("find-upd"), severity: 4 }])
    const loaded = store.getFinding("find-upd")
    expect(loaded!.severity).toBe(4)
    cleanup()
  })

  test("getFindings returns findings ordered by severity descending", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveFindings(eng.id, [
      { ...makeFinding("find-low"), severity: 1 },
      { ...makeFinding("find-high"), severity: 4 },
      { ...makeFinding("find-med"), severity: 2 },
    ])
    const loaded = store.getFindings(eng.id)
    expect(loaded[0].severity).toBeGreaterThanOrEqual(loaded[1].severity)
    cleanup()
  })
})

describe("EngagementStore — audit log", () => {
  test("appendAuditLog creates retrievable entry", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.appendAuditLog(eng.id, "TEST_EVENT", "test message")
    const log = store.getAuditLog(eng.id)
    expect(log.length).toBeGreaterThanOrEqual(1)
    expect(log[0].eventType).toBe("TEST_EVENT")
    expect(log[0].message).toBe("test message")
    cleanup()
  })

  test("getAuditLog returns entries ordered by recency", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.appendAuditLog(eng.id, "FIRST", "first event")
    store.appendAuditLog(eng.id, "SECOND", "second event")
    const log = store.getAuditLog(eng.id)
    expect(log.length).toBeGreaterThanOrEqual(2)
    expect(log[0].eventType).toBe("SECOND")
    cleanup()
  })

  test("getAuditLog returns empty for engagement with no log", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const log = store.getAuditLog(eng.id)
    expect(log).toHaveLength(0)
    cleanup()
  })

  test("appendAuditLog stores metadata", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.appendAuditLog(eng.id, "TEST", "msg", { key: "value", num: 42 })
    const log = store.getAuditLog(eng.id)
    expect(log[0].metadata).toEqual({ key: "value", num: 42 })
    cleanup()
  })
})

describe("EngagementStore — evidence packages", () => {
  test("saveEvidencePackage and getEvidencePackages roundtrip", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveFindings(eng.id, [{
      id: "find-ev-1", title: "test", severity: 2, confidence: 2, status: "PENDING",
      description: "test", tool: "nuclei", phase: "phase-1",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }])
    const pkgId = "pkg-1"
    store.saveEvidencePackage(pkgId, "find-ev-1", "abc123")
    const packages = store.getEvidencePackages("find-ev-1")
    expect(packages).toHaveLength(1)
    expect(packages[0].id).toBe(pkgId)
    expect(packages[0].packageHash).toBe("abc123")
    cleanup()
  })

  test("getEvidencePackages returns empty for finding with no packages", () => {
    const { store, cleanup } = makeStore()
    const packages = store.getEvidencePackages("nonexistent")
    expect(packages).toHaveLength(0)
    cleanup()
  })
})

describe("EngagementStore — workflow snapshots", () => {
  test("saveWorkflowSnapshot and getWorkflowSnapshots roundtrip", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    store.saveWorkflowSnapshot("snap-1", eng.id, "test-workflow", 1, "{}")
    const snapshots = store.getWorkflowSnapshots(eng.id)
    expect(snapshots.length).toBeGreaterThanOrEqual(1)
    expect(snapshots[0].workflowName).toBe("test-workflow")
    cleanup()
  })
})

describe("EngagementStore — evidence by engagement", () => {
  test("getEvidenceByEngagement returns empty for engagement with no evidence", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(0)
    cleanup()
  })
})



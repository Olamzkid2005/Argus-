import { afterAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import type { FindingAnalysis } from "../../../src/argus/shared/types"

let dbDir: string

afterAll(() => {
  if (dbDir) {
    rmSync(dbDir, { recursive: true, force: true })
  }
})

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

describe("EngagementStore — connection pragmas", () => {
  test("sets PRAGMA busy_timeout = 5000 on initialization", () => {
    const { store, cleanup } = makeStore()
    // Access the store's own connection (PRAGMA busy_timeout is per-connection)
    const sqlite = (store as any)._sqlite
    const row = sqlite.query("PRAGMA busy_timeout").get() as Record<string, unknown>
    // The column name may vary by SQLite version; use Object.values to get the value
    const value = Object.values(row!)[0]
    expect(value).toBe(5000)
    cleanup()
  })

  test("sets PRAGMA journal_mode = WAL on initialization", () => {
    const { store, cleanup } = makeStore()
    // journal_mode is database-level, verifiable from a separate connection
    const { Database } = require("bun:sqlite")
    const sqlite = new Database(store.dbPath)
    const row = sqlite.query("PRAGMA journal_mode").get() as Record<string, unknown>
    const value = Object.values(row!)[0] as string
    expect(value.toLowerCase()).toBe("wal")
    sqlite.close()
    cleanup()
  })

  test("sets PRAGMA foreign_keys = ON on initialization", () => {
    const { store, cleanup } = makeStore()
    // foreign_keys is per-connection; use the store's own connection
    const sqlite = (store as any)._sqlite
    const row = sqlite.query("PRAGMA foreign_keys").get() as Record<string, unknown>
    const value = Object.values(row!)[0]
    expect(value).toBe(1)
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

  test("getEvidenceByEngagement returns findings with no evidence packages", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-no-ev", title: "No Evidence", severity: 1, confidence: 1, status: "PENDING", description: "no ev", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].findingId).toBe("f-no-ev")
    expect(evidence[0].findingTitle).toBe("No Evidence")
    expect(evidence[0].packages).toHaveLength(0)
    cleanup()
  })

  test("getEvidenceByEngagement correctly filters packages by finding ID", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-with-ev", title: "Has Evidence", severity: 1, confidence: 1, status: "PENDING", description: "has ev", tool: "t", phase: "p1", created_at: now, updated_at: now },
      { id: "f-without", title: "No Evidence", severity: 1, confidence: 1, status: "PENDING", description: "no ev", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    store.saveEvidencePackage("pkg-1", "f-with-ev", "hash1")
    store.saveEvidencePackage("pkg-2", "f-with-ev", "hash2")
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(2)
    const withEv = evidence.find((e) => e.findingId === "f-with-ev")
    expect(withEv?.packages).toHaveLength(2)
    const withoutEv = evidence.find((e) => e.findingId === "f-without")
    expect(withoutEv?.packages).toHaveLength(0)
    cleanup()
  })

  test("getEvidenceByEngagement returns artifacts nested within packages", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-art", title: "With Artifacts", severity: 1, confidence: 1, status: "PENDING", description: "arts", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    store.saveEvidencePackage("pkg-art", "f-art", "hash-art")
    store.saveArtifact("art-1", "pkg-art", "/path/to/file", "sha256abc", 1024, "artifact")
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].packages).toHaveLength(1)
    expect(evidence[0].packages[0].artifacts).toHaveLength(1)
    expect(evidence[0].packages[0].artifacts[0].path).toBe("/path/to/file")
    expect(evidence[0].packages[0].artifacts[0].sizeBytes).toBe(1024)
    cleanup()
  })

  test("multiple packages with multiple artifacts per package", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://multi.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-multi", title: "Multi", severity: 1, confidence: 1, status: "PENDING", description: "multi", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    // 3 packages, each with 2 artifacts = 6 artifacts total
    for (let p = 1; p <= 3; p++) {
      store.saveEvidencePackage(`pkg-${p}`, "f-multi", `hash-${p}`)
      for (let a = 1; a <= 2; a++) {
        store.saveArtifact(`art-${p}-${a}`, `pkg-${p}`, `/path/${p}/${a}`, `sha256-${p}-${a}`, p * a * 100, "artifact")
      }
    }
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].packages).toHaveLength(3)
    evidence[0].packages.forEach((pkg, i) => {
      expect(pkg.id).toBe(`pkg-${i + 1}`)
      expect(pkg.artifacts).toHaveLength(2)
      expect(pkg.artifacts[0].path).toBe(`/path/${i + 1}/1`)
      expect(pkg.artifacts[1].path).toBe(`/path/${i + 1}/2`)
    })
    cleanup()
  })

  test("multiple findings each with own packages and artifacts", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://multi-findings.com", "assessment")
    const now = new Date().toISOString()
    // 3 findings, each with 1 package containing 1 artifact
    for (let f = 1; f <= 3; f++) {
      store.saveFindings(eng.id, [{
        id: `f-${f}`, title: `Finding ${f}`, severity: 1, confidence: 1,
        status: "PENDING", description: `finding ${f}`, tool: "t", phase: "p1",
        created_at: now, updated_at: now,
      }])
      store.saveEvidencePackage(`pkg-f${f}`, `f-${f}`, `hash-f${f}`)
      store.saveArtifact(`art-f${f}`, `pkg-f${f}`, `/path/f${f}.txt`, `sha256-f${f}`, f * 200, "artifact")
    }
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(3)
    evidence.forEach((item, i) => {
      expect(item.findingId).toBe(`f-${i + 1}`)
      expect(item.findingTitle).toBe(`Finding ${i + 1}`)
      expect(item.packages).toHaveLength(1)
      expect(item.packages[0].id).toBe(`pkg-f${i + 1}`)
      expect(item.packages[0].artifacts).toHaveLength(1)
      expect(item.packages[0].artifacts[0].id).toBe(`art-f${i + 1}`)
    })
    cleanup()
  })

  test("does not leak evidence across engagements", () => {
    const { store, cleanup } = makeStore()
    const eng1 = store.createEngagement("https://a.com", "assessment")
    const eng2 = store.createEngagement("https://b.com", "assessment")
    const now = new Date().toISOString()
    // Eng1: one finding with package+artifact
    store.saveFindings(eng1.id, [
      { id: "f-eng1", title: "From Eng1", severity: 1, confidence: 1, status: "PENDING", description: "eng1", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    store.saveEvidencePackage("pkg-eng1", "f-eng1", "hash-eng1")
    store.saveArtifact("art-eng1", "pkg-eng1", "/eng1.txt", "sha256-e1", 100, "artifact")
    // Eng2: one finding with package+artifact (different IDs)
    store.saveFindings(eng2.id, [
      { id: "f-eng2", title: "From Eng2", severity: 1, confidence: 1, status: "PENDING", description: "eng2", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    store.saveEvidencePackage("pkg-eng2", "f-eng2", "hash-eng2")
    store.saveArtifact("art-eng2", "pkg-eng2", "/eng2.txt", "sha256-e2", 200, "artifact")
    // Query only eng1 — should not include eng2 data
    const evidence = store.getEvidenceByEngagement(eng1.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].findingId).toBe("f-eng1")
    expect(evidence[0].findingTitle).toBe("From Eng1")
    expect(evidence[0].packages).toHaveLength(1)
    expect(evidence[0].packages[0].id).toBe("pkg-eng1")
    expect(evidence[0].packages[0].artifacts).toHaveLength(1)
    expect(evidence[0].packages[0].artifacts[0].id).toBe("art-eng1")
    cleanup()
  })

  test("mixed packages: some with artifacts, some without", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://mixed.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-mixed", title: "Mixed", severity: 1, confidence: 1, status: "PENDING", description: "mixed", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    // Package with artifact
    store.saveEvidencePackage("pkg-with", "f-mixed", "hash-with")
    store.saveArtifact("art-with", "pkg-with", "/with.txt", "sha256-w", 100, "artifact")
    // Package without artifact
    store.saveEvidencePackage("pkg-without", "f-mixed", "hash-without")
    // Verify package with artifact has 1 artifact, package without has 0
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].packages).toHaveLength(2)
    const withArt = evidence[0].packages.find((p) => p.id === "pkg-with")!
    expect(withArt.artifacts).toHaveLength(1)
    expect(withArt.artifacts[0].id).toBe("art-with")
    const withoutArt = evidence[0].packages.find((p) => p.id === "pkg-without")!
    expect(withoutArt.artifacts).toHaveLength(0)
    cleanup()
  })

  test("returns empty for non-existent engagement ID", () => {
    const { store, cleanup } = makeStore()
    const evidence = store.getEvidenceByEngagement("ENG-NONEXISTENT")
    expect(evidence).toHaveLength(0)
    cleanup()
  })

  test("finding with many packages each having one artifact", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://many-pkgs.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-many", title: "Many", severity: 1, confidence: 1, status: "PENDING", description: "many pkgs", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    // 5 packages, each with 1 artifact
    for (let p = 1; p <= 5; p++) {
      store.saveEvidencePackage(`mpkg-${p}`, "f-many", `hash-${p}`)
      store.saveArtifact(`mart-${p}`, `mpkg-${p}`, `/multi/${p}`, `sha256-m-${p}`, p * 50, "artifact")
    }
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].packages).toHaveLength(5)
    evidence[0].packages.forEach((pkg, i) => {
      expect(pkg.id).toBe(`mpkg-${i + 1}`)
      expect(pkg.artifacts).toHaveLength(1)
      expect(pkg.artifacts[0].id).toBe(`mart-${i + 1}`)
    })
    cleanup()
  })

  test("artifacts with different types are preserved", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://types.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-types", title: "Types", severity: 1, confidence: 1, status: "PENDING", description: "types", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    store.saveEvidencePackage("pkg-types", "f-types", "hash-types")
    store.saveArtifact("art-screenshot", "pkg-types", "/screenshot.png", "sha256-ss", 2048, "screenshot")
    store.saveArtifact("art-log", "pkg-types", "/output.log", "sha256-log", 512, "log")
    store.saveArtifact("art-http", "pkg-types", "/request.bin", "sha256-http", 128, "http_traffic")
    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].packages).toHaveLength(1)
    const artifacts = evidence[0].packages[0].artifacts
    expect(artifacts).toHaveLength(3)
    const screenshot = artifacts.find((a) => a.id === "art-screenshot")!
    expect(screenshot.type).toBe("screenshot")
    expect(screenshot.sizeBytes).toBe(2048)
    const log = artifacts.find((a) => a.id === "art-log")!
    expect(log.type).toBe("log")
    expect(log.sizeBytes).toBe(512)
    const http = artifacts.find((a) => a.id === "art-http")!
    expect(http.type).toBe("http_traffic")
    expect(http.sizeBytes).toBe(128)
    cleanup()
  })
})

describe("EngagementStore — getFindingCountsByEngagementIds", () => {
  test("returns empty map for empty IDs array", () => {
    const { store, cleanup } = makeStore()
    const result = store.getFindingCountsByEngagementIds([])
    expect(result).toBeInstanceOf(Map)
    expect(result.size).toBe(0)
    cleanup()
  })

  test("returns empty map when engagements have no findings", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const result = store.getFindingCountsByEngagementIds([eng.id])
    expect(result.size).toBe(0)
    cleanup()
  })

  test("returns correct total, critical, and confirmed counts", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const now = new Date().toISOString()
    // 5 findings: 2 low (severity < 4), 1 critical, 1 CONFIRMED, 1 FINALIZED+critical
    store.saveFindings(eng.id, [
      { id: "f-low-1", title: "Low1", severity: 2, confidence: 2, status: "PENDING", description: "low 1", tool: "nuclei", phase: "p1", created_at: now, updated_at: now },
      { id: "f-low-2", title: "Low2", severity: 1, confidence: 2, status: "PENDING", description: "low 2", tool: "nuclei", phase: "p1", created_at: now, updated_at: now },
      { id: "f-crit", title: "Critical", severity: 8, confidence: 3, status: "PENDING", description: "critical", tool: "nuclei", phase: "p1", created_at: now, updated_at: now },
      { id: "f-conf", title: "Confirmed", severity: 3, confidence: 2, status: "CONFIRMED", description: "confirmed", tool: "nuclei", phase: "p1", created_at: now, updated_at: now },
      { id: "f-final", title: "Finalized", severity: 7, confidence: 3, status: "FINALIZED", description: "finalized", tool: "nuclei", phase: "p1", created_at: now, updated_at: now },
    ])
    const result = store.getFindingCountsByEngagementIds([eng.id])
    expect(result.size).toBe(1)
    const counts = result.get(eng.id)
    expect(counts).toBeDefined()
    expect(counts!.total).toBe(5)
    expect(counts!.critical).toBe(2) // severity >= 4: f-crit (8), f-final (7)
    expect(counts!.confirmed).toBe(2) // CONFIRMED or FINALIZED: f-conf, f-final
    cleanup()
  })

  test("handles engagements with only low-severity PENDING findings", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://test.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "f-a", title: "A", severity: 1, confidence: 1, status: "PENDING", description: "a", tool: "t", phase: "p1", created_at: now, updated_at: now },
      { id: "f-b", title: "B", severity: 2, confidence: 1, status: "PENDING", description: "b", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    const result = store.getFindingCountsByEngagementIds([eng.id])
    const counts = result.get(eng.id)!
    expect(counts.total).toBe(2)
    expect(counts.critical).toBe(0)
    expect(counts.confirmed).toBe(0)
    cleanup()
  })

  test("aggregates counts separately for multiple engagements", () => {
    const { store, cleanup } = makeStore()
    const eng1 = store.createEngagement("https://a.com", "assessment")
    const eng2 = store.createEngagement("https://b.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng1.id, [
      { id: "e1-f1", title: "F1", severity: 4, confidence: 3, status: "FINALIZED", description: "f1", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    store.saveFindings(eng2.id, [
      { id: "e2-f1", title: "F1", severity: 2, confidence: 2, status: "PENDING", description: "f1", tool: "t", phase: "p1", created_at: now, updated_at: now },
      { id: "e2-f2", title: "F2", severity: 1, confidence: 1, status: "PENDING", description: "f2", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    const result = store.getFindingCountsByEngagementIds([eng1.id, eng2.id])
    expect(result.size).toBe(2)
    expect(result.get(eng1.id)).toEqual({ total: 1, critical: 1, confirmed: 1 })
    expect(result.get(eng2.id)).toEqual({ total: 2, critical: 0, confirmed: 0 })
    cleanup()
  })

  test("only returns entries for engagements that have findings", () => {
    const { store, cleanup } = makeStore()
    const engWith = store.createEngagement("https://with.com", "assessment")
    const engWithout = store.createEngagement("https://without.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(engWith.id, [
      { id: "f-only", title: "Only", severity: 1, confidence: 1, status: "PENDING", description: "only", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    const result = store.getFindingCountsByEngagementIds([engWith.id, engWithout.id])
    expect(result.size).toBe(1)
    expect(result.has(engWith.id)).toBe(true)
    expect(result.has(engWithout.id)).toBe(false)
    cleanup()
  })

  test("correctly counts critical (severity >= 4) separately from total", () => {
    const { store, cleanup } = makeStore()
    const eng = store.createEngagement("https://sev.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "s-3", title: "S3", severity: 3, confidence: 1, status: "PENDING", description: "s3", tool: "t", phase: "p1", created_at: now, updated_at: now },
      { id: "s-4", title: "S4", severity: 4, confidence: 1, status: "PENDING", description: "s4", tool: "t", phase: "p1", created_at: now, updated_at: now },
      { id: "s-5", title: "S5", severity: 5, confidence: 1, status: "PENDING", description: "s5", tool: "t", phase: "p1", created_at: now, updated_at: now },
      { id: "s-10", title: "S10", severity: 10, confidence: 1, status: "PENDING", description: "s10", tool: "t", phase: "p1", created_at: now, updated_at: now },
    ])
    const result = store.getFindingCountsByEngagementIds([eng.id])
    const counts = result.get(eng.id)!
    expect(counts.total).toBe(4)
    expect(counts.critical).toBe(3) // severities 4, 5, 10
    expect(counts.confirmed).toBe(0)
    cleanup()
  })
})



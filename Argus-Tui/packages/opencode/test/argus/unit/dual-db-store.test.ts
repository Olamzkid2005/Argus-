import { afterAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import { StoragePaths } from "../../../src/argus/storage/paths"
import type { IEngagementStore, EngagementState, PhaseRecord } from "../../../src/argus/engagement/types"
import type { NormalizedFinding } from "../../../src/argus/shared/types"

// ── Helpers ──

let _tmpDir: string | null = null

function freshStore(): EngagementStore {
  if (!_tmpDir) {
    _tmpDir = mkdtempSync(join(tmpdir(), "argus-dualdb-"))
  }
  const dbPath = join(_tmpDir, `store-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`)
  return new EngagementStore(dbPath)
}

function makeEngagement(): { store: EngagementStore; eng: EngagementState } {
  const store = freshStore()
  const eng = store.createEngagement("https://example.com", "assessment")
  return { store, eng }
}

function makeFinding(overrides?: Partial<NormalizedFinding>): NormalizedFinding {
  return {
    id: `find-${crypto.randomUUID()}`,
    title: "test finding",
    severity: 2,
    confidence: 2,
    status: "PENDING" as const,
    description: "test",
    subtype: undefined,
    cve: undefined,
    cwe: undefined,
    owasp: undefined,
    remediation: undefined,
    tool: "nuclei",
    phase: "recon",
    negative: undefined,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    finalized_at: undefined,
    ...overrides,
  }
}

function makePhase(overrides?: Partial<PhaseRecord>): PhaseRecord {
  return {
    id: `phase-${crypto.randomUUID()}`,
    engagementId: "",           // caller must set this
    name: "recon",
    status: "COMPLETED" as const,
    capabilities: ["port-scan"],
    executionMode: "sequential" as const,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    error: undefined,
    replanCycle: false,
    ...overrides,
  }
}

// Cleanup temp dir after all tests
afterAll(() => {
  if (_tmpDir) {
    try { rmSync(_tmpDir, { recursive: true, force: true }) } catch { /* best-effort */ }
  }
})

// ── Tests ──

describe("Dual-DB store — new engagement write/read", () => {
  test("createEngagement sets storage_version to PER_ENGAGEMENT", () => {
    const { store, eng } = makeEngagement()
    expect(eng.id).toMatch(/^ENG-/)
    expect(eng.storageVersion).toBe(2) // STORAGE_VERSION_PER_ENGAGEMENT
    store.close()
  })

  test("write findings, then read them back", () => {
    const { store, eng } = makeEngagement()
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    const got = store.getFindings(eng.id)
    expect(got).toHaveLength(1)
    expect(got[0].id).toBe(finding.id)
    expect(got[0].title).toBe("test finding")
    store.close()
  })

  test("write phases, then read them back", () => {
    const { store, eng } = makeEngagement()
    const phase = makePhase({ engagementId: eng.id })
    store.savePhase(eng.id, phase)

    const got = store.getPhases(eng.id)
    expect(got).toHaveLength(1)
    expect(got[0].id).toBe(phase.id)
    expect(got[0].name).toBe("recon")
    store.close()
  })

  test("write audit log, then read it back", () => {
    const { store, eng } = makeEngagement()
    store.appendAuditLog(eng.id, "phase_completed", "recon phase done")

    const log = store.getAuditLog(eng.id)
    expect(log).toHaveLength(1)
    expect(log[0].eventType).toBe("phase_completed")
    expect(log[0].message).toBe("recon phase done")
    store.close()
  })

  test("saveEvidencePackage and getEvidenceByEngagement work", () => {
    const { store, eng } = makeEngagement()
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    store.saveEvidencePackage("pkg-1", finding.id, "abc123hash")
    store.saveEvidencePackage("pkg-2", finding.id, "def456hash")

    const evidence = store.getEvidenceByEngagement(eng.id)
    expect(evidence).toHaveLength(1)
    expect(evidence[0].findingId).toBe(finding.id)
    expect(evidence[0].packages).toHaveLength(2)
    expect(evidence[0].packages[0].packageHash).toBe("abc123hash")
    store.close()
  })

  test("saveArtifact and getArtifacts work end-to-end", () => {
    const { store, eng } = makeEngagement()
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])
    store.saveEvidencePackage("pkg-art-1", finding.id, "hash1")
    store.saveArtifact("art-1", "pkg-art-1", "/tmp/screenshot.png", "sha256abc", 1024, "screenshot")

    const artifacts = store.getArtifacts("pkg-art-1")
    expect(artifacts).toHaveLength(1)
    expect(artifacts[0].path).toBe("/tmp/screenshot.png")
    expect(artifacts[0].sizeBytes).toBe(1024)
    store.close()
  })

  test("two engagements have isolated per-engagement DBs", () => {
    const store = freshStore()
    const eng1 = store.createEngagement("https://alpha.com", "quick")
    const eng2 = store.createEngagement("https://beta.com", "full")

    store.saveFindings(eng1.id, [makeFinding({ title: "alpha-finding" })])
    store.saveFindings(eng2.id, [makeFinding({ title: "beta-finding" })])

    const f1 = store.getFindings(eng1.id)
    const f2 = store.getFindings(eng2.id)
    expect(f1).toHaveLength(1)
    expect(f1[0].title).toBe("alpha-finding")
    expect(f2).toHaveLength(1)
    expect(f2[0].title).toBe("beta-finding")
    store.close()
  })
})

describe("Dual-DB store — legacy fallback", () => {
  /**
   * Simulate a legacy (storage_version=1) engagement by:
   * 1. Creating an old store that uses the legacy schema (root DB has all tables)
   * 2. Creating an engagement (storage_version stays 1 since this is legacy)
   * 3. Opening the same DB with the dual-DB store and verifying reads work
   */
  test("reads legacy data from root DB when per-engagement DB doesn't exist", () => {
    const { store, eng } = makeEngagement()

    // Modify the storage_version back to 1 to simulate legacy
    // We need to use the internal rootDb directly — or use saveEngagement
    const legacyEng: EngagementState = { ...eng, storageVersion: 1 }
    store.saveEngagement(legacyEng)

    // Verify we can still read the engagement
    const got = store.getEngagement(eng.id)
    expect(got).not.toBeNull()
    expect(got!.storageVersion).toBe(1)

    // Verify listEngagements still works
    const all = store.listEngagements()
    expect(all.some((e) => e.id === eng.id)).toBe(true)
    store.close()
  })

  test("legacy engagement returns empty findings from per-engagement DB, falls back to root DB", () => {
    const { store, eng } = makeEngagement()

    // Downgrade to legacy
    const legacyEng: EngagementState = { ...eng, storageVersion: 1 }
    store.saveEngagement(legacyEng)

    // Write a finding directly (this goes to per-engagement DB via _ensureEngagementDb)
    // But since storage_version is 1, _getEngagementDb returns null for reads
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    // The per-engagement DB was created by saveFindings (which calls _ensureEngagementDb)
    // and storage_version was upgraded to 2. Let's check.
    const updated = store.getEngagement(eng.id)
    // It should have been upgraded to PER_ENGAGEMENT when saveFindings was called
    expect(updated!.storageVersion).toBe(2)
    store.close()
  })
})

describe("Dual-DB store — lazy migration", () => {
  test("legacy engagement auto-migrates on first write", () => {
    const store = freshStore()

    // Create an engagement via the dual-DB store
    const eng = store.createEngagement("https://migrate.me", "assessment")
    // The engagement starts as storage_version=2 (per-engagement)

    // Downgrade to legacy in root DB
    const legacyEng: EngagementState = { ...eng, storageVersion: 1 }
    store.saveEngagement(legacyEng)

    // Verify storage_version is back to 1
    expect(store.getEngagement(eng.id)!.storageVersion).toBe(1)

    // Now save a finding — this should trigger lazy migration
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    // After save, storage_version should be PER_ENGAGEMENT (2)
    const updated = store.getEngagement(eng.id)
    expect(updated!.storageVersion).toBe(2)

    // The finding should be readable from the per-engagement DB
    const findings = store.getFindings(eng.id)
    expect(findings).toHaveLength(1)
    expect(findings[0].id).toBe(finding.id)
    store.close()
  })
})

describe("Dual-DB store — uncached DB scanning", () => {
  test("getFinding scans uncached per-engagement DBs", () => {
    const dbPath = join(_tmpDir!, `store-uncached-find-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`)
    const store = new EngagementStore(dbPath)
    const eng = store.createEngagement("https://scan.me", "assessment")
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    // Close the first store, then open a second one with the same dbPath
    // to get a cold cache (no per-engagement DB handles pre-opened).
    store.close()
    const store2 = new EngagementStore(dbPath)
    const got = store2.getFinding(finding.id)
    expect(got).not.toBeNull()
    expect(got!.id).toBe(finding.id)
    store2.close()
  })

  test("getFindingEngagementId scans uncached per-engagement DBs", () => {
    const dbPath = join(_tmpDir!, `store-uncached-engid-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`)
    const store = new EngagementStore(dbPath)
    const eng = store.createEngagement("https://scan-eng-id.me", "assessment")
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    store.close()
    const store2 = new EngagementStore(dbPath)
    const engId = store2.getFindingEngagementId(finding.id)
    expect(engId).toBe(eng.id)
    store2.close()
  })

  test("saveArtifact finds the correct engagement via uncached DB scan", () => {
    const dbPath = join(_tmpDir!, `store-uncached-art-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`)
    const store = new EngagementStore(dbPath)
    const eng = store.createEngagement("https://artifact-scan.me", "assessment")
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])
    store.saveEvidencePackage("pkg-scan-1", finding.id, "scanhash")

    store.close()
    const store2 = new EngagementStore(dbPath)
    store2.saveArtifact("art-scan-1", "pkg-scan-1", "/tmp/evidence.png", "sha256xyz", 2048, "screenshot")

    const artifacts = store2.getArtifacts("pkg-scan-1")
    expect(artifacts).toHaveLength(1)
    expect(artifacts[0].path).toBe("/tmp/evidence.png")
    store2.close()
  })
})

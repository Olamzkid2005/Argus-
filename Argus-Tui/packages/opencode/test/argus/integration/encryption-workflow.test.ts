/**
 * Encryption Workflow — integration tests
 *
 * Tests the full integration between EncryptionManager, EncryptedDbHandle,
 * and EngagementStore. These tests require macOS Keychain (Bun FFI) and
 * are skipped on non-macOS platforms.
 *
 * IMPORTANT: EngagementStore.encryptionEnabled must be set AFTER the store
 * constructor, because the constructor calls syncEncryptionFromConfig() which
 * may override the flag based on config files on disk.
 *
 * Behavior notes:
 * - createEngagement always creates with storage_version=2
 * - storage_version is bumped to 3 lazily on first WRITE via _ensureEngagementDb
 * - READING alone does NOT trigger migration
 *
 * Coverage:
 *   1. Encrypted engagement lifecycle (create → write → close → reopen)
 *   2. Plaintext → encrypted migration (2→3 on first write)
 *   3. Missing master key error
 *   4. Wrong master key rejection
 *   5. Phases, status, and workflow snapshots in encrypted engagements
 *   6. Concurrent encrypted + plaintext engagements
 *   7. Encryption flag toggling across sessions
 */
import { beforeAll, afterAll, afterEach, expect } from "bun:test"
import { existsSync, readFileSync } from "node:fs"
import { EngagementStore } from "../../../src/argus/engagement/store"
import { EncryptionManager } from "../../../src/argus/storage/encryption"
import {
  IS_MACOS,
  itOnMac,
  makeTempDir,
  cleanupTempDir,
  makeStorePath,
  initEncryptionManager,
  destroyEncryptionManager,
  withEncryption,
  withoutEncryption,
} from "../../argus/helpers/encryption-test-utils"

let tempDir: string

beforeAll(async () => {
  if (!IS_MACOS) return
  tempDir = makeTempDir("argus-encryption-integration-")
  await initEncryptionManager()
  withoutEncryption()
})

afterAll(async () => {
  withoutEncryption()
  await destroyEncryptionManager()
  cleanupTempDir(tempDir)
})

afterEach(() => {
  withoutEncryption()
  EncryptionManager.clearCache()
})

// ═══════════════════════════════════════════════
// 1. Encrypted engagement lifecycle
// ═══════════════════════════════════════════════

itOnMac(
  "creates engagement, enables encryption, writes data, closes, reopens, and verifies",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // ── Session 1: Create + encrypt ──
    await EncryptionManager.requireMasterKey()
    const store = new EngagementStore(dbPath)
    withEncryption() // AFTER constructor — don't let syncEncryptionFromConfig override

    const eng = store.createEngagement("https://encrypted-lifecycle.com", "assessment")
    expect(eng).toBeDefined()
    expect(eng.id).toMatch(/^ENG-/)

    // Write findings — triggers _ensureEngagementDb which bumps to version 3
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [
      { id: "find-lifecycle-1", title: "SQL Injection", severity: 4,
        confidence: 3, status: "CONFIRMED", description: "SQLi in login",
        tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now },
      { id: "find-lifecycle-2", title: "XSS", severity: 3,
        confidence: 2, status: "PENDING", description: "XSS in search",
        tool: "nuclei", phase: "phase-2", created_at: now, updated_at: now },
    ])
    store.appendAuditLog(eng.id, "PHASE_START", "Phase 1 started")
    store.appendAuditLog(eng.id, "PHASE_END", "Phase 1 completed", { duration: 5000 })

    expect(store.getEngagement(eng.id)!.storageVersion).toBe(3)
    store.close()

    // Verify encrypted on disk
    const { StoragePaths } = await import("../../../src/argus/storage/paths")
    const engDbPath = StoragePaths.engagementDbPath(eng.id)
    expect(existsSync(engDbPath)).toBe(true)

    const rawBytes = readFileSync(engDbPath)
    const sqliteHeader = "53514c69746520666f726d6174203300"
    expect(rawBytes.subarray(0, 16).toString("hex")).not.toBe(sqliteHeader)
    expect(rawBytes[0]).toBe(0x01)
    expect(existsSync(engDbPath + ".decrypted")).toBe(false)

    // ── Session 2: Reopen and verify ──
    EncryptionManager.clearCache()
    await EncryptionManager.requireMasterKey()
    const store2 = new EngagementStore(dbPath)
    withEncryption()

    const reloadedEng = store2.getEngagement(eng.id)
    expect(reloadedEng!.storageVersion).toBe(3)
    expect(reloadedEng!.target).toBe("https://encrypted-lifecycle.com")

    const findings = store2.getFindings(eng.id)
    expect(findings).toHaveLength(2)
    expect(findings.map((f) => f.title)).toContain("SQL Injection")
    expect(findings.map((f) => f.title)).toContain("XSS")

    const auditLog = store2.getAuditLog(eng.id)
    expect(auditLog.length).toBeGreaterThanOrEqual(2)
    const phaseEnd = auditLog.find((e) => e.eventType === "PHASE_END")
    expect((phaseEnd!.metadata as any).duration).toBe(5000)

    store2.close()
  },
  30_000,
)

// ═══════════════════════════════════════════════
// 2. Plaintext → encrypted migration (2→3)
// ═══════════════════════════════════════════════

itOnMac(
  "migrates plaintext engagement to encrypted — preserves all pre-existing data",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // Phase 1: Create + write data without encryption
    const store1 = new EngagementStore(dbPath)
    withoutEncryption()

    const eng = store1.createEngagement("https://migrate-me.com", "full_scan")
    expect(eng.storageVersion).toBe(2)

    const now = new Date().toISOString()
    // Write 3 findings before encryption
    store1.saveFindings(eng.id, [
      { id: "find-mig-1", title: "SQL Injection", severity: 4,
        confidence: 3, status: "CONFIRMED", description: "pre-encrypt",
        tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now },
      { id: "find-mig-2", title: "XSS", severity: 3,
        confidence: 2, status: "PENDING", description: "pre-encrypt",
        tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now },
      { id: "find-mig-3", title: "CSRF", severity: 2,
        confidence: 2, status: "PENDING", description: "pre-encrypt",
        tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now },
    ])
    store1.appendAuditLog(eng.id, "BEFORE_MIGRATE", "This was logged before encryption")
    store1.close()

    // Phase 2: Enable encryption, trigger migration by writing a new finding
    await EncryptionManager.requireMasterKey()
    const store2 = new EngagementStore(dbPath)
    withEncryption()

    // Still at version 2 before any write
    expect(store2.getEngagement(eng.id)!.storageVersion).toBe(2)

    // First write triggers _ensureEngagementDb which migrates 2→3
    store2.saveFindings(eng.id, [{
      id: "find-mig-4", title: "Post-migration finding", severity: 3,
      confidence: 2, status: "CONFIRMED", description: "added after encryption",
      tool: "nuclei", phase: "phase-2", created_at: now, updated_at: now,
    }])

    expect(store2.getEngagement(eng.id)!.storageVersion).toBe(3)

    // Close and reopen to verify persistence
    store2.close()

    EncryptionManager.clearCache()
    await EncryptionManager.requireMasterKey()
    const store3 = new EngagementStore(dbPath)
    withEncryption()

    const findings = store3.getFindings(eng.id)
    expect(findings).toHaveLength(4)
    expect(findings.map((f) => f.title)).toContain("SQL Injection")
    expect(findings.map((f) => f.title)).toContain("XSS")
    expect(findings.map((f) => f.title)).toContain("CSRF")
    expect(findings.map((f) => f.title)).toContain("Post-migration finding")

    const auditLog = store3.getAuditLog(eng.id)
    expect(auditLog.find((e) => e.eventType === "BEFORE_MIGRATE")).toBeDefined()
    store3.close()

    // Phase 3: Verify encrypted on disk
    const { StoragePaths } = await import("../../../src/argus/storage/paths")
    const engDbPath = StoragePaths.engagementDbPath(eng.id)
    const rawBytes = readFileSync(engDbPath)
    const sqliteHeader = "53514c69746520666f726d6174203300"
    expect(rawBytes.subarray(0, 16).toString("hex")).not.toBe(sqliteHeader)
    expect(rawBytes[0]).toBe(0x01)
  },
  30_000,
)

// ═══════════════════════════════════════════════
// 3. Missing master key error
// ═══════════════════════════════════════════════

itOnMac(
  "throws clear error when encrypted engagement is opened without a cached master key",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // Create encrypted engagement
    await EncryptionManager.requireMasterKey()
    const store = new EngagementStore(dbPath)
    withEncryption()

    const eng = store.createEngagement("https://no-key-test.com", "assessment")
    store.saveFindings(eng.id, [{
      id: "find-nk-1", title: "Test", severity: 1, confidence: 1,
      status: "PENDING", description: "test", tool: "nuclei", phase: "p1",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }])
    store.close()

    // Clear cache — key is gone
    EncryptionManager.clearCache()
    const store2 = new EngagementStore(dbPath)
    withEncryption()

    // getEngagement works (root DB is plaintext)
    expect(store2.getEngagement(eng.id)).not.toBeNull()

    // getFindings throws because key is not cached
    expect(() => {
      store2.getFindings(eng.id)
    }).toThrow("master key not loaded")

    store2.close()
  },
  30_000,
)

// ═══════════════════════════════════════════════
// 4. Wrong master key rejection
// ═══════════════════════════════════════════════

itOnMac(
  "rejects access to encrypted engagement with the wrong master key",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // Create encrypted engagement
    await EncryptionManager.requireMasterKey()
    const store = new EngagementStore(dbPath)
    withEncryption()

    const eng = store.createEngagement("https://wrong-key-test.com", "assessment")
    const now = new Date().toISOString()
    store.saveFindings(eng.id, [{
      id: "find-wk-1", title: "Secret Finding", severity: 4,
      confidence: 3, status: "CONFIRMED", description: "highly sensitive",
      tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now,
    }])
    store.close()

    // Direct decrypt with wrong key
    const { StoragePaths } = await import("../../../src/argus/storage/paths")
    const engDbPath = StoragePaths.engagementDbPath(eng.id)
    const encryptedBuf = readFileSync(engDbPath)
    const wrongKey = Buffer.alloc(32, 0xAA)

    expect(() => {
      EncryptionManager.decryptEngagementDb(encryptedBuf, wrongKey, eng.id)
    }).toThrow()

    // Correct key still works
    const correctKey = await EncryptionManager.requireMasterKey()
    const decrypted = EncryptionManager.decryptEngagementDb(encryptedBuf, correctKey, eng.id)
    expect(decrypted.length).toBeGreaterThan(0)
  },
  30_000,
)

// ═══════════════════════════════════════════════
// 5. Phases, status, and workflow snapshots
// ═══════════════════════════════════════════════

itOnMac(
  "preserves phases, status transitions, and workflow snapshots in encrypted engagements",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // ── Session 1: Create encrypted + write data ──
    await EncryptionManager.requireMasterKey()
    const store = new EngagementStore(dbPath)
    withEncryption()

    const eng = store.createEngagement("https://phases-test.com", "full_assessment")

    store.savePhases(eng.id, [
      { id: "phase-recon", engagementId: eng.id, name: "Reconnaissance",
        status: "COMPLETED", capabilities: ["web_recon"], executionMode: "sequential",
        replanCycle: false, startedAt: new Date().toISOString() },
      { id: "phase-scan", engagementId: eng.id, name: "Scanning",
        status: "RUNNING", capabilities: ["vuln_scan"], executionMode: "parallel",
        replanCycle: false, startedAt: new Date().toISOString() },
    ])
    store.updateStatus(eng.id, "RUNNING")
    store.saveWorkflowSnapshot("snap-phases-1", eng.id, "full_assessment", 1,
      "name: full_assessment\nphases:\n  - Reconnaissance\n  - Scanning")

    expect(store.getEngagement(eng.id)!.storageVersion).toBe(3)
    store.close()

    // ── Session 2: Reopen and verify ──
    EncryptionManager.clearCache()
    await EncryptionManager.requireMasterKey()
    const store2 = new EngagementStore(dbPath)
    withEncryption()

    expect(store2.getEngagement(eng.id)!.status).toBe("RUNNING")

    const phases = store2.getPhases(eng.id)
    expect(phases).toHaveLength(2)
    expect(phases[0].name).toBe("Reconnaissance")
    expect(phases[1].name).toBe("Scanning")

    const snapshots = store2.getWorkflowSnapshots(eng.id)
    expect(snapshots.length).toBeGreaterThanOrEqual(1)
    expect(snapshots[0].workflowName).toBe("full_assessment")

    store2.close()
  },
  30_000,
)

// ═══════════════════════════════════════════════
// 6. Concurrent encrypted + plaintext engagements
// ═══════════════════════════════════════════════

itOnMac(
  "allows concurrent access to encrypted and plaintext engagements",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // ── Create plaintext engagement ──
    const store = new EngagementStore(dbPath)
    withoutEncryption()

    const plainEng = store.createEngagement("https://plaintext.com", "quick_scan")
    const now = new Date().toISOString()
    store.saveFindings(plainEng.id, [{
      id: "find-plain-1", title: "Plaintext finding", severity: 1,
      confidence: 1, status: "PENDING", description: "not secret",
      tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now,
    }])
    store.close()

    // ── Create encrypted engagement in same store ──
    await EncryptionManager.requireMasterKey()
    const store2 = new EngagementStore(dbPath)
    withEncryption()

    const encEng = store2.createEngagement("https://encrypted-concurrent.com", "full_assessment")
    store2.saveFindings(encEng.id, [{
      id: "find-enc-1", title: "Encrypted finding", severity: 4,
      confidence: 3, status: "CONFIRMED", description: "secret vuln",
      tool: "nuclei", phase: "phase-1", created_at: now, updated_at: now,
    }])
    store2.close()

    // ── Reopen and access both ──
    EncryptionManager.clearCache()
    await EncryptionManager.requireMasterKey()
    const store3 = new EngagementStore(dbPath)
    withEncryption()

    // Both engagements visible
    const engagements = store3.listEngagements()
    expect(engagements.length).toBeGreaterThanOrEqual(2)
    const engIds = engagements.map((e) => e.id)
    expect(engIds).toContain(plainEng.id)
    expect(engIds).toContain(encEng.id)

    // Plaintext works
    expect(store3.getFindings(plainEng.id)).toHaveLength(1)
    expect(store3.getFindings(plainEng.id)[0].title).toBe("Plaintext finding")

    // Encrypted works
    const encryptedFindings = store3.getFindings(encEng.id)
    expect(encryptedFindings).toHaveLength(1)
    expect(encryptedFindings[0].title).toBe("Encrypted finding")
    expect(encryptedFindings[0].severity).toBe(4)

    // Storage versions
    expect(store3.getEngagement(plainEng.id)!.storageVersion).toBe(2)
    expect(store3.getEngagement(encEng.id)!.storageVersion).toBe(3)

    store3.close()
  },
  30_000,
)

// ═══════════════════════════════════════════════
// 7. Encryption flag toggling
// ═══════════════════════════════════════════════

itOnMac(
  "handles encryption flag being toggled on/off across store instances",
  async () => {
    const dbPath = makeStorePath(tempDir)

    // Session 1: Encryption OFF
    const store1 = new EngagementStore(dbPath)
    withoutEncryption()

    const eng1 = store1.createEngagement("https://no-encrypt.com", "assessment")
    expect(eng1.storageVersion).toBe(2)
    store1.close()

    // Session 2: Encryption ON
    await EncryptionManager.requireMasterKey()
    const store2 = new EngagementStore(dbPath)
    withEncryption()

    // New engagement — version bumps on first write
    const eng2 = store2.createEngagement("https://encrypt-enabled.com", "assessment")
    store2.saveFindings(eng2.id, [{
      id: "find-eng2-1", title: "Encrypted finding", severity: 3,
      confidence: 2, status: "PENDING", description: "encrypted",
      tool: "nuclei", phase: "p1",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }])
    expect(store2.getEngagement(eng2.id)!.storageVersion).toBe(3)

    // Migrate eng1 (plaintext → encrypted)
    store2.saveFindings(eng1.id, [{
      id: "find-mig-1", title: "Migrated", severity: 2, confidence: 2,
      status: "PENDING", description: "migrated to encrypted",
      tool: "nuclei", phase: "p1",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }])
    expect(store2.getEngagement(eng1.id)!.storageVersion).toBe(3)
    store2.close()

    // Session 3: Encryption OFF — encrypted engagement throws on access
    EncryptionManager.clearCache()
    const store3 = new EngagementStore(dbPath)
    withoutEncryption()

    expect(store3.getEngagement(eng2.id)).not.toBeNull()

    // getFindings on encrypted engagement without key should throw
    expect(() => {
      store3.getFindings(eng2.id)
    }).toThrow()

    store3.close()
  },
  30_000,
)

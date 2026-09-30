/**
 * EncryptedDbHandle — unit tests
 *
 * Tests the full lifecycle: open, save, close, and encrypt/decrypt roundtrip.
 * Requires macOS Keychain (via EncryptionManager) — skipped on non-macOS.
 */
import { beforeAll, afterAll, describe, expect, test } from "bun:test"
import { platform } from "node:os"
import { mkdtempSync, existsSync, readFileSync, rmSync, writeFileSync, mkdirSync, utimesSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"

const { EncryptionManager } = await import("../../../src/argus/storage/encryption")
const {
  EncryptedDbHandle,
  EncryptedDbError,
  sweepEngagementScratchFiles,
  sweepEngagementsDir,
} = await import("../../../src/argus/storage/encrypted-db")

const isMacOS = platform() === "darwin"
const macDescriptor = isMacOS ? describe : describe.skip

// ── Helpers ──

function makeEngDir(parent: string, name: string): string {
  const dir = join(parent, name)
  mkdirSync(dir, { recursive: true })
  return dir
}

function cleanupDir(dir: string): void {
  try { rmSync(dir, { recursive: true, force: true }) } catch { /* best-effort */ }
}

// ── Tests ──

macDescriptor("EncryptedDbHandle — lifecycle (macOS only)", () => {
  let tempDir: string
  let masterKey: Buffer
  const engagementId = "ENG-enc-db-test-001"

  beforeAll(async () => {
    tempDir = mkdtempSync(join(tmpdir(), "argus-enc-db-test-"))
    await EncryptionManager.initialize()
    masterKey = (await EncryptionManager.getMasterKey())!
  })

  afterAll(() => {
    cleanupDir(tempDir)
  })

  // ── Open / Save / Close lifecycle ──

  test("open creates a new encrypted DB from scratch", async () => {
    const engDir = makeEngDir(tempDir, "fresh")
    const dbPath = join(engDir, "engagement.db")

    expect(existsSync(dbPath)).toBe(false)

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    expect(handle.isOpen).toBe(true)
    expect(handle.path).toBe(dbPath)

    const db = handle.getDatabase()
    expect(db).toBeDefined()

    // Create a table and insert data
    db.exec("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    db.exec("INSERT INTO test VALUES (1, 'hello encrypted world')")

    const rows = db.query("SELECT value FROM test WHERE id = 1").all() as Array<{ value: string }>
    expect(rows[0].value).toBe("hello encrypted world")

    // Close — this triggers save + encrypt
    handle.close()
    expect(handle.isOpen).toBe(false)

    // The encrypted .db file should now exist
    expect(existsSync(dbPath)).toBe(true)

    // The temp file should NOT exist (cleaned up by close)
    expect(existsSync(dbPath + ".decrypted")).toBe(false)
  })

  test("open reads an existing encrypted DB and decrypts it correctly", async () => {
    const engDir = makeEngDir(tempDir, "reopen")
    const dbPath = join(engDir, "engagement.db")

    // First pass: create + populate + close
    const handle1 = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db1 = handle1.getDatabase()
    db1.exec("CREATE TABLE data (k TEXT PRIMARY KEY, v TEXT)")
    db1.exec("INSERT INTO data VALUES ('name', 'argus')")
    db1.exec("INSERT INTO data VALUES ('version', '3.0')")
    await handle1.close()

    // Second pass: reopen from encrypted file
    const handle2 = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db2 = handle2.getDatabase()

    const rows = db2.query("SELECT k, v FROM data ORDER BY k").all() as Array<{ k: string; v: string }>
    expect(rows).toEqual([
      { k: "name", v: "argus" },
      { k: "version", v: "3.0" },
    ])

    // Temp file should exist during the session (cleaned up on close)
    expect(existsSync(dbPath + ".decrypted")).toBe(true)

    // But the encrypted .db should also exist
    expect(existsSync(dbPath)).toBe(true)

    handle2.close()
  })

  test("open rejects corrupt encrypted file", async () => {
    const engDir = makeEngDir(tempDir, "corrupt")
    const dbPath = join(engDir, "engagement.db")

    // Write garbage as the "encrypted" file
    writeFileSync(dbPath, Buffer.from("this is not valid encrypted data"))

    await expect(
      EncryptedDbHandle.open(dbPath, masterKey, engagementId),
    ).rejects.toThrow() // GCM auth tag failure or format error
  })

  test("open rejects non-existent engagement directory", async () => {
    const dbPath = join("/nonexistent", "engagement.db")
    await expect(
      EncryptedDbHandle.open(dbPath, masterKey, engagementId),
    ).rejects.toThrow("Engagement directory does not exist")
  })

  test("save can be called multiple times independently", async () => {
    const engDir = makeEngDir(tempDir, "multi-save")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, label TEXT)")
    db.exec("INSERT INTO items VALUES (1, 'first')")

    // First save
    handle.save()
    expect(existsSync(dbPath)).toBe(true)

    // Add more data and second save
    db.exec("INSERT INTO items VALUES (2, 'second')")
    handle.save()

    // Reopen and verify both rows
    handle.close()

    const handle2 = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db2 = handle2.getDatabase()
    const rows = db2.query("SELECT label FROM items ORDER BY id").all() as Array<{ label: string }>
    expect(rows.map((r) => r.label)).toEqual(["first", "second"])
    handle2.close()
  })

  test("close is idempotent (safe to call multiple times)", async () => {
    const engDir = makeEngDir(tempDir, "double-close")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS foo (id INT)")
    db.exec("INSERT INTO foo VALUES (42)")

    handle.close()  // first close
    handle.close()  // second close — should be no-op
    expect(handle.isOpen).toBe(false)
  })

  test("getDatabase throws after close", async () => {
    const engDir = makeEngDir(tempDir, "post-close")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS bar (id INT)")
    handle.close()

    expect(() => handle.getDatabase()).toThrow("not open")
  })

  test("handles large dataset (10K rows)", async () => {
    const engDir = makeEngDir(tempDir, "large")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS large (id INTEGER PRIMARY KEY, data TEXT)")

    // Insert 10K rows in a transaction
    db.exec("BEGIN")
    for (let i = 0; i < 10000; i++) {
      db.exec(`INSERT INTO large VALUES (${i}, 'row-${i}')`)
    }
    db.exec("COMMIT")

    // Verify count
    const count = (db.query("SELECT count(*) as cnt FROM large").get() as { cnt: number }).cnt
    expect(count).toBe(10000)

    handle.close()

    // Reopen and verify persistence
    const handle2 = await EncryptedDbHandle.openSync(dbPath, masterKey, engagementId)
    const db2 = handle2.getDatabase()
    const count2 = (db2.query("SELECT count(*) as cnt FROM large").get() as { cnt: number }).cnt
    expect(count2).toBe(10000)
    handle2.close()
  })

  // ── Encryption at rest verification ──

  test("the encrypted file on disk is NOT a valid SQLite database", async () => {
    const engDir = makeEngDir(tempDir, "encrypted-format")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS secret (value TEXT)")
    db.exec("INSERT INTO secret VALUES ('sensitive-data')")
    handle.close()

    // Read the raw encrypted file
    const encryptedBytes = readFileSync(dbPath)
    const firstBytes = encryptedBytes.subarray(0, 16).toString("hex")

    // SQLite header is: 53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33 00
    // ("SQLite format 3\0"). Encrypted data should NOT start with this.
    expect(firstBytes).not.toBe("53514c69746520666f726d6174203300")
    // Version byte should be 0x01
    expect(encryptedBytes[0]).toBe(0x01)
  })

  test("different master keys produce different encrypted output", async () => {
    const engDir = makeEngDir(tempDir, "different-key")
    const dbPath = join(engDir, "engagement.db")

    const otherKey = Buffer.alloc(32, 0xFF) // different from real masterKey

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    db.exec("INSERT INTO t VALUES ('same-data')")
    handle.close()

    // The encrypted file decrypted with the wrong engagementId should fail
    // But since we're using a different masterKey outright, we can't even
    // decrypt the file. Let's verify the encrypted file is valid under the
    // correct key (already verified above), and that a wrong key fails.
    // Actually let's try to decrypt the file with a different key manually:
    const encryptedBuf = readFileSync(dbPath)

    expect(() => {
      EncryptionManager.decryptEngagementDb(encryptedBuf, otherKey, engagementId)
    }).toThrow()
  })

  // ── Error handling ──

  test("open with wrong engagement ID fails to decrypt", async () => {
    const engDir = makeEngDir(tempDir, "wrong-id")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    db.exec("INSERT INTO t VALUES ('secret')")
    handle.close()

    // Try opening with a different engagement ID
    await expect(
      EncryptedDbHandle.open(dbPath, masterKey, "ENG-wrong-id"),
    ).rejects.toThrow()
  })

  test("save after close is a no-op (does not throw)", async () => {
    const engDir = makeEngDir(tempDir, "save-after-close")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    db.exec("INSERT INTO t VALUES ('before-close')")
    handle.close()

    // This should be a no-op
    handle.save()
  })

  test("temp file is cleaned up after close", async () => {
    const engDir = makeEngDir(tempDir, "temp-cleanup")
    const dbPath = join(engDir, "engagement.db")

    const handle = await EncryptedDbHandle.open(dbPath, masterKey, engagementId)
    const db = handle.getDatabase()
    db.exec("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    db.exec("INSERT INTO t VALUES ('cleanup-test')")
    handle.close()

    // Verify no residual files
    expect(existsSync(dbPath + ".decrypted")).toBe(false)
    expect(existsSync(dbPath + ".decrypted-wal")).toBe(false)
    expect(existsSync(dbPath + ".decrypted-shm")).toBe(false)
    expect(existsSync(dbPath + ".encrypting")).toBe(false)
  })
})

describe("EncryptedDbHandle — plaintext scratch sweep", () => {
  /**
   * `open()` writes the decrypted database next to the encrypted one and only
   * `close()` removes it. Every crash, SIGKILL, or killed run therefore left a
   * plaintext copy of an engagement database on disk with nothing to clean it
   * up — 950+ had accumulated in one data directory.
   */
  test("removes every scratch file this module writes, and nothing else", () => {
    const dir = mkdtempSync(join(tmpdir(), "argus-sweep-"))
    try {
      const dbPath = join(dir, "engagement.db")
      const scratch = [
        dbPath + ".decrypted",
        dbPath + ".decrypted-wal",
        dbPath + ".decrypted-shm",
        dbPath + ".encrypting",
      ]
      const precious = [dbPath, dbPath + ".backup", join(dir, "report.md")]
      for (const f of [...scratch, ...precious]) writeFileSync(f, "x")

      const removed = sweepEngagementScratchFiles(dbPath)

      expect(removed.sort()).toEqual([...scratch].sort())
      for (const f of scratch) expect(existsSync(f)).toBe(false)
      for (const f of precious) expect(existsSync(f)).toBe(true)
    } finally {
      cleanupDir(dir)
    }
  })

  test("is a no-op when there is nothing to sweep", () => {
    const dir = mkdtempSync(join(tmpdir(), "argus-sweep-empty-"))
    try {
      expect(sweepEngagementScratchFiles(join(dir, "engagement.db"))).toEqual([])
    } finally {
      cleanupDir(dir)
    }
  })

  test("sweeps every engagement directory, skipping non-directories", () => {
    const engagements = mkdtempSync(join(tmpdir(), "argus-sweep-all-"))
    try {
      for (const id of ["ENG-a", "ENG-b", "ENG-c"]) {
        const d = makeEngDir(engagements, id)
        writeFileSync(join(d, "engagement.db"), "encrypted")
        writeFileSync(join(d, "engagement.db.decrypted"), "plaintext")
      }
      // A stray file at the top level must not be treated as an engagement.
      writeFileSync(join(engagements, "notes.txt"), "x")

      const removed = sweepEngagementsDir(engagements, 0)

      expect(removed).toHaveLength(3)
      expect(existsSync(join(engagements, "notes.txt"))).toBe(true)
      for (const id of ["ENG-a", "ENG-b", "ENG-c"]) {
        expect(existsSync(join(engagements, id, "engagement.db"))).toBe(true)
        expect(existsSync(join(engagements, id, "engagement.db.decrypted"))).toBe(false)
      }
    } finally {
      cleanupDir(engagements)
    }
  })

  test("directory sweep leaves a just-written scratch file alone (a live session may own it)", () => {
    const engagements = mkdtempSync(join(tmpdir(), "argus-sweep-fresh-"))
    try {
      const dir = makeEngDir(engagements, "ENG-live")
      writeFileSync(join(dir, "engagement.db"), "encrypted")
      writeFileSync(join(dir, "engagement.db.decrypted"), "a session that is still running")

      // Default age threshold: the file is seconds old, so it is preserved.
      expect(sweepEngagementsDir(engagements)).toEqual([])
      expect(existsSync(join(dir, "engagement.db.decrypted"))).toBe(true)
    } finally {
      cleanupDir(engagements)
    }
  })

  test("a stale scratch file is swept by default, whatever its exact age", () => {
    const engagements = mkdtempSync(join(tmpdir(), "argus-sweep-stale-"))
    try {
      const dir = makeEngDir(engagements, "ENG-crashed")
      const scratch = join(dir, "engagement.db.decrypted")
      writeFileSync(scratch, "left by a crashed run")
      // Backdate well past the default threshold.
      const old = new Date(Date.now() - 60 * 60_000)
      utimesSync(scratch, old, old)

      const removed = sweepEngagementsDir(engagements)
      expect(removed).toEqual([scratch])
      expect(existsSync(scratch)).toBe(false)
    } finally {
      cleanupDir(engagements)
    }
  })

  test("sweepEngagementsDir is quiet when the directory does not exist", () => {
    expect(sweepEngagementsDir(join(tmpdir(), "argus-sweep-missing-" + Date.now()))).toEqual([])
  })

  test("open() clears a stale plaintext copy before writing this session's", async () => {
    const dir = mkdtempSync(join(tmpdir(), "argus-sweep-open-"))
    try {
      const dbPath = join(dir, "engagement.db")
      // A stale copy left by a previous crashed session, with content that
      // must not survive into the new session.
      writeFileSync(dbPath + ".decrypted", "stale plaintext from a crashed run")

      const handle = await EncryptedDbHandle.open(dbPath, Buffer.alloc(32, 5), "ENG-stale")
      const db = handle.getDatabase()
      db.exec("CREATE TABLE IF NOT EXISTS t (v TEXT)")
      db.exec("INSERT INTO t VALUES ('fresh')")
      const rows = db.query("SELECT v FROM t").all() as Array<{ v: string }>
      expect(rows.map((r) => r.v)).toEqual(["fresh"])
      handle.close()
    } finally {
      cleanupDir(dir)
    }
  })
})

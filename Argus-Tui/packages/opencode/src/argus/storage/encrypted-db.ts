/**
 * EncryptedDbHandle — Layer 2: Per-Engagement Database Encryption (Item 14c)
 *
 * Manages the lifecycle of an encrypted per-engagement SQLite database:
 *
 *   1. OPEN:   Read encrypted .db file → decrypt → write to temp file in the
 *              engagement directory → open with bun:sqlite.
 *   2. USE:    Returns the live Database instance for use via drizzle-orm.
 *   3. SAVE:   Database.serialize() → encrypt → atomic write to .db file
 *              (write to .tmp, then rename).
 *   4. CLOSE:  Saves, closes the Database handle, cleans up temp + WAL files.
 *
 * ── Threat model ──
 *   The decrypted temp file exists on disk for the duration of the engagement
 *   session (while the handle is open). It is created with 0o600 permissions
 *   in the engagement directory, alongside the encrypted .db. On close(), the
 *   temp file and any SQLite companion files (-wal, -shm) are deleted.
 *
 *   This is a major improvement over the current state (plaintext .db on disk
 *   permanently). An attacker with filesystem access during an active session
 *   could read the temp file — but the same attacker could also read the
 *   encrypted .db (which requires the master key to decrypt). The plaintext
 *   window is limited to active sessions only.
 *
 * ── Integration with EngagementStore ──
 *   In EngagementStore._getEngagementDb / _ensureEngagementDb, when
 *   storage_version >= 3 (encrypted), instead of:
 *     const sqlite = new BunSqliteDatabase(engPath)
 *   use:
 *     const handle = await EncryptedDbHandle.open(engPath, masterKey, engagementId)
 *     const sqlite = handle.getDatabase()
 *   And in close(), before calling sqlite.close(), call handle.close().
 *
 *   The engagementDbs map stores the handle alongside the drizzle wrapper:
 *     { db, drizzle, lastAccessed, encryptedHandle }
 */

import { existsSync, readFileSync, writeFileSync, renameSync, rmSync } from "node:fs"
import { dirname } from "node:path"
import { createRequire } from "node:module"
import { EncryptionManager, EncryptionError } from "./encryption"

const _require = createRequire(import.meta.url)
type BunSqliteDatabase = ReturnType<typeof _loadBunSqlite>

/**
 * Lazy-load bun:sqlite with clear error if not running under Bun.
 * Same pattern as engagement/store.ts.
 */
function _loadBunSqlite(): typeof import("bun:sqlite").Database {
  try {
    return _require("bun:sqlite").Database as typeof import("bun:sqlite").Database
  } catch {
    throw new Error(
      "EncryptedDbHandle requires Bun's built-in bun:sqlite module.\n" +
      "Run this under `bun` — Node.js is not supported.\n" +
      "See https://bun.sh/docs/api/sqlite for details.",
    )
  }
}

/** Extension for the decrypted temp file (placed alongside the encrypted .db). */
const TEMP_SUFFIX = ".decrypted"

/** Extension for the atomic-write temp file (during save). */
const ENC_TMP_SUFFIX = ".encrypting"

/**
 * Error thrown when the encrypted DB file is missing or corrupted.
 */
export class EncryptedDbError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message)
    this.name = "EncryptedDbError"
  }
}

/**
 * Handle for an encrypted per-engagement SQLite database.
 *
 * Lifecycle:
 *   const handle = await EncryptedDbHandle.open(path, masterKey, engId)
 *   const db = handle.getDatabase()
 *   // ... use db via drizzle ...
 *   await handle.save()   // optional periodic save
 *   await handle.close()  // save + close + cleanup
 */
export class EncryptedDbHandle {
  /** Underlying bun:sqlite Database instance (null until open). */
  private db: import("bun:sqlite").Database | null = null

  /** Path to the decrypted temp file (companion to encrypted .db). */
  private readonly tempPath: string

  /** Path to the atomic-write intermediate file. */
  private readonly encTmpPath: string

  /** Whether the handle is open. */
  private _isOpen = false

  /** Whether close() has been called. Prevents double-close. */
  private _isClosed = false

  private constructor(
    /** Path to the encrypted .db file on disk. */
    private readonly encryptedDbPath: string,
    /** The master key (from EncryptionManager). */
    private readonly masterKey: Buffer,
    /** The engagement ID (for HKDF domain separation). */
    private readonly engagementId: string,
  ) {
    this.tempPath = encryptedDbPath + TEMP_SUFFIX
    this.encTmpPath = encryptedDbPath + ENC_TMP_SUFFIX
  }

  /**
   * Factory: open (or create) an encrypted per-engagement database.
   *
   * If the encrypted .db file exists, it is decrypted and loaded into a
   * temp file backed by bun:sqlite. If it does not exist, a fresh empty
   * database is created at the temp path.
   *
   * @returns A ready-to-use EncryptedDbHandle
   */
  static async open(
    encryptedDbPath: string,
    masterKey: Buffer,
    engagementId: string,
  ): Promise<EncryptedDbHandle> {
    const handle = new EncryptedDbHandle(encryptedDbPath, masterKey, engagementId)
    handle._open()
    return handle
  }

  /**
   * Synchronous factory — same as open() but without async wrapper.
   * All internal operations are synchronous (readFileSync, writeFileSync,
   * new BunSqliteDatabase). Use this when calling from sync contexts like
   * EngagementStore methods.
   */
  static openSync(
    encryptedDbPath: string,
    masterKey: Buffer,
    engagementId: string,
  ): EncryptedDbHandle {
    const handle = new EncryptedDbHandle(encryptedDbPath, masterKey, engagementId)
    handle._open()
    return handle
  }

  /**
   * Internal: open the database.
   * Synchronous — all operations are sync (readFileSync, writeFileSync, etc.).
   */
  private _open(): void {
    if (this._isOpen) return
    const BunSqliteDatabase = _loadBunSqlite()

    if (existsSync(this.encryptedDbPath)) {
      // ── Existing encrypted DB — decrypt and load ──
      const encrypted = readFileSync(this.encryptedDbPath)
      let decrypted: Buffer
      try {
        decrypted = EncryptionManager.decryptEngagementDb(
          encrypted,
          this.masterKey,
          this.engagementId,
        )
      } catch (err) {
        if (err instanceof EncryptionError) throw err
        throw new EncryptedDbError(
          `Failed to decrypt engagement database: ${(err as Error).message}`,
          "DECRYPT_FAILED",
        )
      }

      const dir = dirname(this.encryptedDbPath)
      if (!existsSync(dir)) {
        throw new EncryptedDbError(
          `Engagement directory does not exist: ${dir}`,
          "DIR_NOT_FOUND",
        )
      }
      writeFileSync(this.tempPath, decrypted, { mode: 0o600 })
      this.db = new BunSqliteDatabase(this.tempPath)
    } else {
      // ── No encrypted DB yet — create fresh database at temp path ──
      const dir = dirname(this.encryptedDbPath)
      if (!existsSync(dir)) {
        throw new EncryptedDbError(
          `Engagement directory does not exist: ${dir}`,
          "DIR_NOT_FOUND",
        )
      }
      this.db = new BunSqliteDatabase(this.tempPath)
    }

    // Apply PRAGMAs — we use WAL mode to match the existing store.ts pattern.
    // The companion files (-wal, -shm) are cleaned up on close().
    this.db.exec("PRAGMA journal_mode = WAL")
    this.db.exec("PRAGMA foreign_keys = OFF")
    this.db.exec("PRAGMA busy_timeout = 5000")

    this._isOpen = true
  }

  /**
   * Get the underlying bun:sqlite Database instance.
   * Throws if not open.
   */
  getDatabase(): import("bun:sqlite").Database {
    if (!this.db || !this._isOpen) {
      throw new EncryptedDbError(
        "EncryptedDbHandle is not open. Call open() first.",
        "NOT_OPEN",
      )
    }
    return this.db
  }

  /**
   * Check if the handle is open.
   */
  get isOpen(): boolean {
    return this._isOpen
  }

  /**
   * Serialize the in-memory database, encrypt it, and atomically write to disk.
   *
   * This is safe to call multiple times during a session (e.g., periodic saves).
   * The write is atomic: data is first written to a .encrypting temp file, then
   * renamed to the target encrypted .db path. If the process crashes during the
   * write, the original encrypted .db is left intact (no corruption).
   *
   * Synchronous — all operations are sync (writeFileSync, renameSync).
   */
  save(): void {
    if (!this.db || !this._isOpen) return

    // Serialize the database to a binary buffer
    const serialized = this.db.serialize()
    if (!serialized) {
      throw new EncryptedDbError(
        "Database.serialize() returned null — unable to persist database state.",
        "SERIALIZE_FAILED",
      )
    }

    let serializedBuf: Buffer
    if (Buffer.isBuffer(serialized)) {
      serializedBuf = serialized
    } else {
      // Bun's serialize() returns Buffer in most versions, but handle
      // the case where it returns Uint8Array
      serializedBuf = Buffer.from(serialized)
    }

    // Encrypt
    const encrypted = EncryptionManager.encryptEngagementDb(
      serializedBuf,
      this.masterKey,
      this.engagementId,
    )

    // Atomic write: write to temp → rename
    writeFileSync(this.encTmpPath, encrypted, { mode: 0o600 })
    renameSync(this.encTmpPath, this.encryptedDbPath)
  }

  /**
   * Save, close the database, and clean up temp files.
   *
   * Safe to call multiple times (idempotent after first close).
   * After this, getDatabase() will throw.
   *
   * Synchronous — all operations are sync (save, close, rmSync).
   */
  close(): void {
    if (this._isClosed) return
    this._isClosed = true

    if (this.db) {
      try {
        this.save()
      } finally {
        this._isOpen = false
        try { this.db.close() } catch { /* already closed */ }
        this.db = null
      }
    }

    // Clean up any residual files:
    for (const suffix of [TEMP_SUFFIX, TEMP_SUFFIX + "-wal", TEMP_SUFFIX + "-shm", ENC_TMP_SUFFIX]) {
      try { rmSync(this.encryptedDbPath + suffix, { force: true }) } catch { /* best-effort */ }
    }
  }

  /**
   * Get the encrypted DB file path.
   */
  get path(): string {
    return this.encryptedDbPath
  }
}

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

import { existsSync, readFileSync, writeFileSync, renameSync, rmSync, readdirSync, statSync } from "node:fs"
import { dirname, join } from "node:path"
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
 * Unencrypted scratch files this module can leave on disk.
 *
 * `.decrypted` holds the whole engagement database in the clear, so it is the
 * one that matters: it is written on every `open()` and removed only by a clean
 * `close()`. Any crash, SIGKILL, or killed run leaves it behind, and nothing
 * ever cleaned it up — 950+ of them had accumulated in one data directory.
 */
const SCRATCH_SUFFIXES = [
  TEMP_SUFFIX,
  `${TEMP_SUFFIX}-wal`,
  `${TEMP_SUFFIX}-shm`,
  ENC_TMP_SUFFIX,
] as const

/**
 * Directory-wide sweeps skip scratch files younger than this.
 *
 * `_open()` and `close()` sweep the single file they own and are always
 * immediate — the caller holds that engagement open, so any scratch copy of it
 * is stale by definition. A sweep of the whole engagements directory is
 * different: another process (an open TUI session, a parallel run) may
 * legitimately be holding an engagement whose plaintext file was just written.
 * Skipping recent files keeps the startup cleanup from deleting the working
 * files of a live session; anything older is treated as a leftover.
 */
const MIN_DIRECTORY_SWEEP_AGE_MS = 60_000

/**
 * Remove the scratch files for one encrypted DB path.
 *
 * @param encryptedDbPath path to the encrypted `.db` (not the scratch file)
 * @param olderThanMs only remove scratch files at least this old (0 = all)
 * @returns the paths removed
 */
export function sweepEngagementScratchFiles(encryptedDbPath: string, olderThanMs = 0): string[] {
  const removed: string[] = []
  for (const suffix of SCRATCH_SUFFIXES) {
    const candidate = encryptedDbPath + suffix
    try {
      if (!existsSync(candidate)) continue
      if (olderThanMs > 0 && Date.now() - statSync(candidate).mtimeMs < olderThanMs) continue
      rmSync(candidate, { force: true })
      removed.push(candidate)
    } catch {
      /* best-effort: a locked file is retried on the next open */
    }
  }
  return removed
}

/**
 * Sweep every engagement directory for leftover plaintext scratch files.
 *
 * Called once at startup so a crashed session's plaintext copy of an
 * engagement database does not outlive the crash. Only files this module
 * created are removed (`engagement.db.decrypted` and its SQLite companions,
 * plus the `.encrypting` atomic-write intermediate); the encrypted `.db` and
 * anything else in the directory is left alone.
 *
 * @param engagementsDir `<basePath>/engagements`
 * @param olderThanMs only remove scratch files at least this old
 *   (default: {@link MIN_DIRECTORY_SWEEP_AGE_MS}, so a live session's file is safe)
 * @returns the paths removed
 */
export function sweepEngagementsDir(
  engagementsDir: string,
  olderThanMs = MIN_DIRECTORY_SWEEP_AGE_MS,
): string[] {
  const removed: string[] = []
  let entries: string[]
  try {
    entries = readdirSync(engagementsDir)
  } catch {
    return removed // no engagements directory yet
  }
  for (const entry of entries) {
    const dir = join(engagementsDir, entry)
    try {
      if (!statSync(dir).isDirectory()) continue
    } catch {
      continue
    }
    removed.push(...sweepEngagementScratchFiles(join(dir, "engagement.db"), olderThanMs))
  }
  return removed
}

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

    const dir = dirname(this.encryptedDbPath)
    if (!existsSync(dir)) {
      throw new EncryptedDbError(
        `Engagement directory does not exist: ${dir}`,
        "DIR_NOT_FOUND",
      )
    }

    // A crash or SIGKILL during a previous session leaves the plaintext copy
    // behind. Clear it before either branch touches the temp path: the decrypt
    // branch overwrites it, but the create-fresh branch *opens* it — and a
    // stale file would then be read as if it were a database (SQLITE_NOTADB).
    sweepEngagementScratchFiles(this.encryptedDbPath)

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

      writeFileSync(this.tempPath, decrypted, { mode: 0o600 })
      this.db = new BunSqliteDatabase(this.tempPath)
    } else {
      // ── No encrypted DB yet — create fresh database at temp path ──
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
    sweepEngagementScratchFiles(this.encryptedDbPath)
  }

  /**
   * Get the encrypted DB file path.
   */
  get path(): string {
    return this.encryptedDbPath
  }
}

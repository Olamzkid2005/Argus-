// bun:sqlite is only available in Bun. We use createRequire for a lazy
// dynamic import so that under Node the error is a clear "Bun required"
// message at construction time rather than a cryptic module-not-found
// at import time (which would prevent the entire module from loading).
// NOTE: drizzle-orm/bun-sqlite must also be dynamically imported because it
// eagerly requires bun:sqlite at module level in its driver.cjs.
import { createRequire } from "node:module"

const _require = createRequire(import.meta.url)
type BunSqliteDatabaseConstructor = typeof import("bun:sqlite").Database

/**
 * Load the bun:sqlite Database class with a clear error if not running under Bun.
 * This avoids a module-level crash — the error only happens at construction time.
 */
function _loadBunSqlite(): BunSqliteDatabaseConstructor {
  try {
    return _require("bun:sqlite").Database as BunSqliteDatabaseConstructor
  } catch {
    throw new Error(
      "EngagementStore requires Bun's built-in bun:sqlite module.\n" +
      "Run this under `bun` — Node.js is not supported by the engagement store.\n" +
      "See https://bun.sh/docs/api/sqlite for details."
    )
  }
}

// Lazy drizzle loader — drizzle-orm/bun-sqlite eagerly requires bun:sqlite
// at module level in its driver.cjs, so we must load it dynamically via createRequire
// to keep the module importable under Node.js (it will only throw on construction).
type DrizzleFunction = (opts: { client: import("bun:sqlite").Database }) => ReturnType<typeof import("drizzle-orm/bun-sqlite")["drizzle"]>
let _drizzle: DrizzleFunction | null = null
function _loadDrizzle(): DrizzleFunction {
  if (!_drizzle) {
    _drizzle = _require("drizzle-orm/bun-sqlite").drizzle as DrizzleFunction
  }
  return _drizzle
}
import { eq, desc, asc, sql, SQL, type AnyColumn, type SQLWrapper, inArray } from "drizzle-orm"
import { join, dirname } from "path"
import { homedir } from "os"
import { mkdirSync, existsSync, readFileSync, writeFileSync, renameSync, rmSync } from "fs"
import { StoragePaths } from "../storage/paths"
import { ConfigLoader } from "../config/loader"
// Monotonic counter for engagement ID generation. Ensures deterministic
// sort-order tiebreaking when multiple engagements share the same
// millisecond-precision `created_at` timestamp. The secondary sort by
// `id DESC` is deterministic because higher counter values correspond to
// later-created engagements.
let _engagementSeq = 0

// Monotonic counter for audit log entries. Ensures entries with the same
// millisecond-precision `created_at` timestamp sort deterministically
// when ordered by `id DESC`.
let _auditSeq = 0
import {
  engagements,
  findings as findingsTable,
  phases as phasesTable,
  audit_log,
  evidence_packages,
  artifacts,
  workflow_snapshots,
  finding_analysis,
  STORAGE_VERSION_LEGACY,
  STORAGE_VERSION_PER_ENGAGEMENT,
  STORAGE_VERSION_ENCRYPTED,
} from "./schema.sql"
import { EncryptedDbHandle } from "../storage/encrypted-db"
import { EncryptionManager } from "../storage/encryption"
import type { EngagementState, PhaseRecord, EngagementStatus, PhaseStatus, IEngagementStore } from "./types"
import type { ExecutionMode } from "../shared/types"
import type { FindingAnalysis, NormalizedFinding } from "../shared/types"

function defaultDbPath(): string {
  return StoragePaths.db
}

/** Root DB schema — only the engagements table (metadata + index). */
const ROOT_TABLE_SQL = `CREATE TABLE IF NOT EXISTS engagements (
    id TEXT PRIMARY KEY, target TEXT NOT NULL, workflow TEXT NOT NULL,
    workflow_version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'CREATED',
    schema_version INTEGER NOT NULL DEFAULT 1, storage_version INTEGER NOT NULL DEFAULT ${STORAGE_VERSION_LEGACY},
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
  )`

/**
 * Per-engagement DB schema — all tables except engagements.
 * These are plain SQL strings passed directly to bun:sqlite's exec()
 * because drizzle's parameterized `sql` tag creates ? placeholders
 * that SQLite rejects in CREATE TABLE DEFAULT clauses.
 */
const PER_ENGAGEMENT_TABLE_SQL = [
  `CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL,
    title TEXT NOT NULL, severity INTEGER NOT NULL, confidence INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', description TEXT, subtype TEXT, cve TEXT, cwe TEXT,
    owasp TEXT, remediation TEXT, tool TEXT, phase TEXT, created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL, finalized_at INTEGER, negative INTEGER NOT NULL DEFAULT 0
  )`,
  `CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id)`,
  `CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status)`,
  `CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)`,
  `CREATE TABLE IF NOT EXISTS phases (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL,
    name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', capabilities TEXT DEFAULT '[]',
    execution_mode TEXT, started_at INTEGER, completed_at INTEGER, error TEXT,
    replan_cycle INTEGER NOT NULL DEFAULT 0
  )`,
  `CREATE INDEX IF NOT EXISTS idx_phases_engagement ON phases(engagement_id)`,
  `CREATE INDEX IF NOT EXISTS idx_phases_engagement_replan ON phases(engagement_id, replan_cycle)`,
  `CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL,
    event_type TEXT NOT NULL, message TEXT NOT NULL, metadata TEXT DEFAULT '{}',
    created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS idx_audit_log_engagement ON audit_log(engagement_id)`,
  `CREATE TABLE IF NOT EXISTS tool_execution_log (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL,
    tool_name TEXT NOT NULL, target_type TEXT NOT NULL, capability TEXT NOT NULL,
    succeeded INTEGER NOT NULL, duration_ms INTEGER NOT NULL, created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS idx_tool_exec_engagement ON tool_execution_log(engagement_id)`,
  `CREATE INDEX IF NOT EXISTS idx_tool_exec_tool ON tool_execution_log(tool_name)`,
  `CREATE INDEX IF NOT EXISTS idx_tool_exec_capability ON tool_execution_log(capability)`,
  `CREATE TABLE IF NOT EXISTS evidence_packages (
    id TEXT PRIMARY KEY, finding_id TEXT NOT NULL,
    package_hash TEXT NOT NULL, created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS idx_evidence_packages_finding ON evidence_packages(finding_id)`,
  `CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, package_id TEXT NOT NULL,
    path TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, type TEXT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS idx_artifacts_package ON artifacts(package_id)`,
  `CREATE TABLE IF NOT EXISTS workflow_snapshots (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL, workflow_version INTEGER NOT NULL,
    workflow_yaml TEXT NOT NULL, created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS idx_workflow_snapshots_engagement ON workflow_snapshots(engagement_id)`,
  `CREATE TABLE IF NOT EXISTS finding_analysis (
    finding_id TEXT PRIMARY KEY,
    explanation TEXT NOT NULL, impact TEXT NOT NULL, remediation TEXT NOT NULL,
    refs TEXT, model TEXT NOT NULL,
    generated_at INTEGER NOT NULL, finding_updated_at INTEGER NOT NULL
  )`,
]

function toEngagementState(row: typeof engagements.$inferSelect): EngagementState {
  return {
    id: row.id,
    target: row.target,
    workflow: row.workflow,
    workflowVersion: row.workflow_version,
    status: row.status as EngagementStatus,
    schemaVersion: row.schema_version,
    storageVersion: row.storage_version ?? STORAGE_VERSION_LEGACY,
    createdAt: new Date(row.created_at).toISOString(),
    updatedAt: new Date(row.updated_at).toISOString(),
  }
}

function toPhaseRecord(row: typeof phasesTable.$inferSelect): PhaseRecord {
  return {
    id: row.id,
    engagementId: row.engagement_id,
    name: row.name,
    status: row.status as PhaseStatus,
    capabilities: row.capabilities ?? [],
    executionMode: (row.execution_mode ?? "sequential") as ExecutionMode,
    startedAt: row.started_at ? new Date(row.started_at).toISOString() : undefined,
    completedAt: row.completed_at ? new Date(row.completed_at).toISOString() : undefined,
    error: row.error ?? undefined,
    replanCycle: row.replan_cycle > 0,
  }
}

function toFindingRow(finding: NormalizedFinding, engagementId: string): typeof findingsTable.$inferInsert {
  return {
    id: finding.id,
    engagement_id: engagementId,
    title: finding.title,
    severity: finding.severity,
    confidence: finding.confidence,
    status: finding.status,
    description: finding.description,
    subtype: finding.subtype,
    cve: finding.cve,
    cwe: finding.cwe,
    owasp: finding.owasp,
    remediation: finding.remediation,
    tool: finding.tool,
    phase: finding.phase,
    negative: finding.negative ?? false,
    created_at: finding.created_at ? new Date(finding.created_at).getTime() : Date.now(),
    updated_at: finding.updated_at ? new Date(finding.updated_at).getTime() : Date.now(),
    finalized_at: finding.finalized_at ? new Date(finding.finalized_at).getTime() : null,
  }
}

function toNormalizedFinding(row: typeof findingsTable.$inferSelect): NormalizedFinding {
  return {
    id: row.id,
    title: row.title,
    severity: row.severity,
    confidence: row.confidence,
    status: row.status as NormalizedFinding["status"],
    description: row.description ?? "",
    subtype: row.subtype ?? undefined,
    cve: row.cve ?? undefined,
    cwe: row.cwe ?? undefined,
    owasp: row.owasp ?? undefined,
    remediation: row.remediation ?? undefined,
    tool: row.tool ?? "unknown",
    phase: row.phase ?? "unknown",
    negative: row.negative ? true : undefined,
    created_at: new Date(row.created_at).toISOString(),
    updated_at: new Date(row.updated_at).toISOString(),
    finalized_at: row.finalized_at ? new Date(row.finalized_at).toISOString() : undefined,
  }
}

export class EngagementStore implements IEngagementStore {
  private rootDb: ReturnType<DrizzleFunction>
  private _rootSqlite: InstanceType<BunSqliteDatabaseConstructor>
  readonly dbPath: string

  /** Cached per-engagement DB handles (engagementId → { db, lastAccessed, encryptedHandle? }). */
  private engagementDbs = new Map<string, { db: InstanceType<BunSqliteDatabaseConstructor>; drizzle: ReturnType<DrizzleFunction>; lastAccessed: number; encryptedHandle?: EncryptedDbHandle }>()
  /** Auto-close idle engagement DB handles after 5 minutes. */
  private static readonly ENGAGEMENT_DB_TIMEOUT_MS = 5 * 60 * 1000
  /** Interval handle for periodic cleanup of stale engagement handles. */
  private _cleanupTimer: ReturnType<typeof setInterval> | null = null

  /**
   * When set to true, all per-engagement databases will be encrypted at rest
   * using AES-256-GCM. Existing plaintext DBs are migrated on first access.
   *
   * Set this from the CLI handler after checking `storage.encryption.enabled`
   * in config and confirming the master key is loaded.
   *
   * This is automatically synced from config on construction (project + user
   * config). You can also call syncEncryptionFromConfig() manually.
   */
  static encryptionEnabled = false

  /**
   * Sync the encryptionEnabled flag from user and project config files.
   *
   * Checks both `~/.argus/config.yaml` (user config) and `./argus.config.yaml`
   * (project config) for `storage.encryption.enabled: true`. Project config
   * takes precedence over user config.
   *
   * Can be called at any time, including before any EngagementStore is created.
   * The constructor calls this automatically.
   */
  static syncEncryptionFromConfig(): void {
    // Check user config first
    const userConfig = ConfigLoader.loadUserConfig()
    const userEnabled = userConfig.storage?.encryption?.enabled

    // Check project config (takes precedence)
    const projectConfig = ConfigLoader.loadProjectConfig()
    const projectEnabled = projectConfig.storage?.encryption?.enabled

    // Project config overrides user config
    if (projectEnabled !== undefined) {
      EngagementStore.encryptionEnabled = projectEnabled
    } else if (userEnabled !== undefined) {
      EngagementStore.encryptionEnabled = userEnabled
    }
    // If neither is set, remains at default (false)
  }

  private static finalizer = new FinalizationRegistry((sqlite: { close(): void }) => {
    try { sqlite.close() } catch { /* finalizer best-effort */ }
  })

  constructor(dbPath?: string) {
    this.dbPath = dbPath ?? defaultDbPath()
    const dir = dirname(this.dbPath)
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }
    // Lazy-load bun:sqlite — gives a clear "Bun required" error under Node
    const BunSqliteDatabase = _loadBunSqlite()
    this._rootSqlite = new BunSqliteDatabase(this.dbPath)
    this._rootSqlite.exec("PRAGMA journal_mode = WAL")
    this._rootSqlite.exec("PRAGMA foreign_keys = ON")
    this._rootSqlite.exec("PRAGMA busy_timeout = 5000")
    // Lazy-load drizzle-orm/bun-sqlite — same reason as bun:sqlite, its
    // driver.cjs eagerly requires bun:sqlite at module level
    const drizzle = _loadDrizzle()
    this.rootDb = drizzle({ client: this._rootSqlite })
    this._ensureRootTables()
    // Seed sequence counters from existing data so they persist across restarts
    this._seedCounters()
    // Sync the encryption-enabled flag from config
    EngagementStore.syncEncryptionFromConfig()

    EngagementStore.finalizer.register(this, this._rootSqlite)

    // Periodic cleanup of stale per-engagement DB handles (every 2 minutes).
    // Use unref() so the timer doesn't keep the process alive.
    this._cleanupTimer = setInterval(() => this._closeStaleEngagementDbs(), 120_000)
    this._cleanupTimer.unref()
  }

  close(): void {
    EngagementStore.finalizer.unregister(this)
    this._closeAllEngagementDbs()
    if (this._cleanupTimer) {
      clearInterval(this._cleanupTimer)
      this._cleanupTimer = null
    }
    try { this._rootSqlite.close() } catch { /* already closed */ }
  }

  // ── Per-engagement DB handle management ──

  /**
   * Determine whether an engagement is already encrypted.
   * Only checks storage_version >= 3. The 2→3 migration is handled
   * in _ensureEngagementDb before any DB handle is opened.
   */
  private static _isEncrypted(eng: EngagementState): boolean {
    return eng.storageVersion >= STORAGE_VERSION_ENCRYPTED
  }

  /**
   * Get or create a drizzle-wrapped per-engagement DB handle.
   * Opens the per-engagement DB file on first access, creating it
   * with the full schema (foreign keys disabled — the engagements
   * table lives in the root DB).
   *
   * For storage_version >= 3 (encrypted), uses EncryptedDbHandle to
   * transparently decrypt the database on open and encrypt on close.
   * The master key must be preloaded via EncryptionManager.getMasterKey();
   * if not cached, a clear error is thrown.
   *
   * **Hybrid lazy migration:** If the per-engagement DB file doesn't
   * exist but the engagement exists in the root DB with
   * `storage_version = 1` (legacy), the engagement's data is still
   * readable from the root DB. On first WRITE to a legacy engagement,
   * the per-engagement DB is created and data is migrated.
   */
  private _getEngagementDb(engagementId: string): { db: InstanceType<BunSqliteDatabaseConstructor>; drizzle: ReturnType<DrizzleFunction> } | null {
    const cached = this.engagementDbs.get(engagementId)
    if (cached) {
      cached.lastAccessed = Date.now()
      return cached
    }

    const engPath = StoragePaths.engagementDbPath(engagementId)
    const eng = this.getEngagement(engagementId)
    if (!eng) return null

    // If per-engagement DB doesn't exist yet, don't auto-create for reads
    // from legacy engagements — the caller will fall back to root DB reads.
    if (!existsSync(engPath) && !EngagementStore._isEncrypted(eng)) {
      return null
    }

    // ── Encrypted DB path (storage_version >= 3) ──
    if (EngagementStore._isEncrypted(eng)) {
      const masterKey = EncryptionManager.getCachedMasterKey()
      if (!masterKey) {
        throw new Error(
          `Cannot open encrypted engagement ${engagementId}: master key not loaded. ` +
          "Call EncryptionManager.getMasterKey() before using encrypted engagements. " +
          "Run `argus encryption init` if no key exists."
        )
      }

      const handle = EncryptedDbHandle.openSync(engPath, masterKey, engagementId)
      const sqlite = handle.getDatabase()

      const drizzle = _loadDrizzle()
      const wrapped = drizzle({ client: sqlite })
      this._ensurePerEngagementTables(sqlite)

      const entry = { db: sqlite, drizzle: wrapped, lastAccessed: Date.now(), encryptedHandle: handle }
      this.engagementDbs.set(engagementId, entry)
      return entry
    }

    // ── Plaintext DB path (storage_version === 2) ──
    if (!existsSync(engPath)) return null

    const BunSqliteDatabase = _loadBunSqlite()
    const sqlite = new BunSqliteDatabase(engPath)
    sqlite.exec("PRAGMA journal_mode = WAL")
    sqlite.exec("PRAGMA foreign_keys = OFF")  // FK targets are in the root DB
    sqlite.exec("PRAGMA busy_timeout = 5000")

    const drizzle = _loadDrizzle()
    const wrapped = drizzle({ client: sqlite })
    this._ensurePerEngagementTables(sqlite)

    const entry = { db: sqlite, drizzle: wrapped, lastAccessed: Date.now() }
    this.engagementDbs.set(engagementId, entry)
    return entry
  }

  /**
   * Ensure a per-engagement DB exists for the given engagement.
   * Creates the file and tables if missing. Marks the engagement
   * as `storage_version = 2` (or 3 if encrypted) in the root DB.
   *
   * For encrypted engagements (storage_version >= 3), uses
   * EncryptedDbHandle which manages transparent encrypt/decrypt
   * and temp file lifecycle.
   *
   * Plaintext → encrypted migration (2 → 3):
   * When encryptionEnabled is true and the engagement's storage_version
   * is 2, the existing plaintext DB file is encrypted in-place on first
   * access. The migration happens BEFORE _getEngagementDb is called,
   * so that _getEngagementDb sees the updated storage_version=3 and
   * opens via the encrypted path.
   */
  private _ensureEngagementDb(engagementId: string): { db: InstanceType<BunSqliteDatabaseConstructor>; drizzle: ReturnType<DrizzleFunction> } {
    const engPath = StoragePaths.engagementDbPath(engagementId)
    const engDir = dirname(engPath)
    if (!existsSync(engDir)) {
      mkdirSync(engDir, { recursive: true })
    }

    // Read the engagement's current storage_version BEFORE _getEngagementDb
    // caches any handle, so we can perform 2→3 migration first.
    const eng = this.getEngagement(engagementId)
    const wasLegacy = eng?.storageVersion === STORAGE_VERSION_LEGACY

    // ── Encryption migration: 2 → 3 (must happen before _getEngagementDb) ──
    // When encryption is enabled and the engagement is at version 2, encrypt
    // the existing plaintext DB in-place and bump storage_version to 3.
    // Then _getEngagementDb will correctly open via the encrypted path.
    if (EngagementStore.encryptionEnabled && eng?.storageVersion === STORAGE_VERSION_PER_ENGAGEMENT) {
      const masterKey = EncryptionManager.getCachedMasterKey()
      if (!masterKey) {
        throw new Error(
          `Cannot encrypt engagement ${engagementId}: master key not loaded. ` +
          "Call EncryptionManager.getMasterKey() before opening encrypted engagements."
        )
      }

      if (existsSync(engPath)) {
        this._migratePlaintextToEncrypted(engPath, masterKey, engagementId)
      }

      // Bump storage_version to 3 before calling _getEngagementDb
      this.rootDb.update(engagements)
        .set({ storage_version: STORAGE_VERSION_ENCRYPTED, updated_at: Date.now() })
        .where(eq(engagements.id, engagementId))
        .run()

      // Now _getEngagementDb will see version 3 → encrypted path
      const pe = this._getEngagementDb(engagementId)
      if (pe) return pe
    }

    // Try cached or existing plaintext DB
    const cached = this._getEngagementDb(engagementId)
    if (cached) return cached

    // ── Create new per-engagement DB ──
    const BunSqliteDatabase = _loadBunSqlite()
    const sqlite = new BunSqliteDatabase(engPath)
    sqlite.exec("PRAGMA journal_mode = WAL")
    sqlite.exec("PRAGMA foreign_keys = OFF")
    sqlite.exec("PRAGMA busy_timeout = 5000")

    const drizzle = _loadDrizzle()
    const wrapped = drizzle({ client: sqlite })
    this._ensurePerEngagementTables(sqlite)

    const entry = { db: sqlite, drizzle: wrapped, lastAccessed: Date.now() }
    this.engagementDbs.set(engagementId, entry)

    // Mark the engagement as migrated to per-engagement storage
    this.rootDb.update(engagements)
      .set({ storage_version: STORAGE_VERSION_PER_ENGAGEMENT, updated_at: Date.now() })
      .where(eq(engagements.id, engagementId))
      .run()

    // If this was a legacy engagement, migrate existing data from the root DB
    if (wasLegacy) {
      this._migrateLegacyEngagement(engagementId)
    }

    return entry
  }

  /**
   * Convert a plaintext per-engagement database (storage_version=2) to
   * encrypted format (storage_version=3) by encrypting the raw file
   * in-place with AES-256-GCM using the engagement's derived key.
   *
   * Called automatically on first access to a version-2 engagement
   * when EngageStore.encryptionEnabled is true. The original plaintext
   * file is read, encrypted, and atomically replaced.
   */
  private _migratePlaintextToEncrypted(engPath: string, masterKey: Buffer, engagementId: string): void {
    // First, checkpoint any WAL data into the main DB file so we capture ALL data
    // (not just what happens to be checkpointed). We open, checkpoint, then close.
    const BunSqliteDatabase = _loadBunSqlite()
    let tmpDb: InstanceType<BunSqliteDatabaseConstructor> | null = null
    try {
      tmpDb = new BunSqliteDatabase(engPath)
      tmpDb.exec("PRAGMA wal_checkpoint(TRUNCATE)")
    } catch { /* best-effort — file may be in use; proceed with readFileSync */ }
    if (tmpDb) {
      try { tmpDb.close() } catch { /* best-effort */ }
    }

    // Read the full plaintext SQLite file (now with WAL checkpointed)
    const plaintext = readFileSync(engPath)

    // Encrypt the raw file bytes using the engagement's derived key.
    // This produces the standard encrypted format:
    // [version:1][salt:16][iv:12][ciphertext...][authTag:16]
    const encrypted = EncryptionManager.encryptEngagementDb(plaintext, masterKey, engagementId)

    // Atomic write: write to temp, then rename over the original
    const tmpPath = engPath + ".encrypt-migrate"
    writeFileSync(tmpPath, encrypted, { mode: 0o600 })
    renameSync(tmpPath, engPath)

    // Clean up any SQLite WAL/SHM companion files left by the plaintext DB
    for (const suffix of ["-wal", "-shm"]) {
      try { rmSync(engPath + suffix, { force: true }) } catch { /* best-effort */ }
    }
  }

  /**
   * Migrate a legacy engagement's data from the root DB to its per-engagement DB.
   * Called automatically on the first write to a legacy engagement.
   */
  private _migrateLegacyEngagement(engagementId: string): void {
    const eng = this.getEngagement(engagementId)
    if (!eng || eng.storageVersion !== STORAGE_VERSION_LEGACY) return

    const pe = this._ensureEngagementDb(engagementId)

    // Migrate phases — use raw SQL to avoid type issues with cross-DB drizzle instances
    const phaseRows = this.rootDb.select().from(phasesTable)
      .where(eq(phasesTable.engagement_id, engagementId))
      .all()
    for (const row of phaseRows) {
      try {
        pe.drizzle.insert(phasesTable).values(row as any).onConflictDoNothing().run()
      } catch (err) {
        console.warn(`[store] Migration: failed to insert phase ${row.id}:`, (err as Error).message)
      }
    }

    // Migrate findings
    const findingRows = this.rootDb.select().from(findingsTable)
      .where(eq(findingsTable.engagement_id, engagementId))
      .all()
    for (const row of findingRows) {
      try {
        pe.drizzle.insert(findingsTable).values(row as any).onConflictDoNothing().run()
      } catch (err) {
        console.warn(`[store] Migration: failed to insert finding ${row.id}:`, (err as Error).message)
      }
    }

    // Migrate audit_log
    const auditRows = this.rootDb.select().from(audit_log)
      .where(eq(audit_log.engagement_id, engagementId))
      .all()
    for (const row of auditRows) {
      try {
        pe.drizzle.insert(audit_log).values(row as any).onConflictDoNothing().run()
      } catch (err) {
        console.warn(`[store] Migration: failed to insert audit_log ${row.id}:`, (err as Error).message)
      }
    }

    // Migrate evidence_packages → artifacts
    for (const f of findingRows) {
      const pkgRows = this.rootDb.select().from(evidence_packages)
        .where(eq(evidence_packages.finding_id, f.id))
        .all()
      for (const pkg of pkgRows) {
        try {
          pe.drizzle.insert(evidence_packages).values(pkg as any).onConflictDoNothing().run()
        } catch (err) {
          console.warn(`[store] Migration: failed to insert evidence_package ${pkg.id}:`, (err as Error).message)
        }
        const artRows = this.rootDb.select().from(artifacts)
          .where(eq(artifacts.package_id, pkg.id))
          .all()
        for (const art of artRows) {
          try {
            pe.drizzle.insert(artifacts).values(art as any).onConflictDoNothing().run()
          } catch (err) {
            console.warn(`[store] Migration: failed to insert artifact ${art.id}:`, (err as Error).message)
          }
        }
      }
    }

    // Migrate workflow_snapshots
    const snapRows = this.rootDb.select().from(workflow_snapshots)
      .where(eq(workflow_snapshots.engagement_id, engagementId))
      .all()
    for (const row of snapRows) {
      try {
        pe.drizzle.insert(workflow_snapshots).values(row as any).onConflictDoNothing().run()
      } catch (err) {
        console.warn(`[store] Migration: failed to insert workflow_snapshot ${row.id}:`, (err as Error).message)
      }
    }
  }

  /**
   * Close per-engagement DB handles that haven't been accessed recently.
   * For encrypted handles, calls handle.close() which saves + encrypts
   * the database before closing.
   */
  private _closeStaleEngagementDbs(): void {
    const now = Date.now()
    for (const [id, entry] of this.engagementDbs) {
      if (now - entry.lastAccessed > EngagementStore.ENGAGEMENT_DB_TIMEOUT_MS) {      if (entry.encryptedHandle) {
        try { entry.encryptedHandle.close() } catch { /* best-effort */ }
      } else {
        try { entry.db.close() } catch { /* already closed */ }
      }
        this.engagementDbs.delete(id)
      }
    }
  }

  private _closeAllEngagementDbs(): void {
    for (const [, entry] of this.engagementDbs) {
      if (entry.encryptedHandle) {
        try { entry.encryptedHandle.close() } catch { /* best-effort */ }
      } else {
        try { entry.db.close() } catch { /* already closed */ }
      }
    }
    this.engagementDbs.clear()
  }

  // ── Table creation ──

  private  _ensureRootTables(): void {
    this._rootSqlite.exec(ROOT_TABLE_SQL)
  }

  private _ensurePerEngagementTables(sqlite: InstanceType<BunSqliteDatabaseConstructor>): void {
    for (const stmt of PER_ENGAGEMENT_TABLE_SQL) {
      sqlite.exec(stmt)
    }
  }

  private _seedCounters(): void {
    try {
      const engRows = this.rootDb.select({ id: engagements.id }).from(engagements).orderBy(desc(engagements.id)).limit(1).all()
      if (engRows.length > 0) {
        const parts = engRows[0].id.split("-")
        _engagementSeq = parseInt(parts[parts.length - 1], 36) + 1
      }
      // Seed counters from legacy audit_log (root DB)
      const audRows = this.rootDb.select({ id: audit_log.id }).from(audit_log).orderBy(desc(audit_log.id)).limit(1).all()
      if (audRows.length > 0) {
        const parts = audRows[0].id.split("-")
        _auditSeq = parseInt(parts[parts.length - 1], 36) + 1
      }
    } catch {
      // If tables don't exist yet, counters stay at 0 — harmless
    }
  }

  // ── Engagement CRUD (all root DB) ──

  createEngagement(target: string, workflow: string): EngagementState {
    const id = `ENG-${Date.now().toString(36)}-${(_engagementSeq++).toString(36)}`
    const now = Date.now()

    this.rootDb.insert(engagements).values({
      id, target, workflow,
      workflow_version: 1, status: "CREATED", schema_version: 1,
      storage_version: STORAGE_VERSION_PER_ENGAGEMENT,
      created_at: now, updated_at: now,
    }).run()

    const result = this.getEngagement(id)
    if (!result) throw new Error(`Failed to create engagement ${id}: insert succeeded but read-back failed`)
    return result
  }

  getEngagement(id: string): EngagementState | null {
    const rows = this.rootDb.select().from(engagements).where(eq(engagements.id, id)).all()
    if (rows.length === 0) return null
    return toEngagementState(rows[0])
  }

  saveEngagement(engagement: EngagementState): void {
    this.rootDb.update(engagements)
      .set({
        target: engagement.target,
        workflow: engagement.workflow,
        workflow_version: engagement.workflowVersion,
        status: engagement.status,
        schema_version: engagement.schemaVersion,
        storage_version: engagement.storageVersion,
        updated_at: Date.now(),
      })
      .where(eq(engagements.id, engagement.id))
      .run()
  }

  updateStatus(id: string, status: EngagementStatus): void {
    this.rootDb.update(engagements)
      .set({ status, updated_at: Date.now() })
      .where(eq(engagements.id, id))
      .run()
  }

  listEngagements(): EngagementState[] {
    const rows = this.rootDb.select().from(engagements).orderBy(desc(engagements.created_at), desc(engagements.id)).all()
    return rows.map(toEngagementState)
  }

  // ── Phases (per-engagement DB with fallback) ──

  savePhases(id: string, records: PhaseRecord[]): void {
    const pe = this._ensureEngagementDb(id)
    pe.drizzle.transaction((tx) => {
      for (const record of records) {
        tx.insert(phasesTable).values({
          id: record.id, engagement_id: id, name: record.name, status: record.status,
          capabilities: record.capabilities, execution_mode: record.executionMode,
          started_at: record.startedAt ? new Date(record.startedAt).getTime() : null,
          completed_at: record.completedAt ? new Date(record.completedAt).getTime() : null,
          error: record.error ?? null, replan_cycle: record.replanCycle ? 1 : 0,
        }).onConflictDoUpdate({
          target: phasesTable.id,
          set: {
            name: record.name,
            status: record.status,
            capabilities: record.capabilities,
            execution_mode: record.executionMode,
            started_at: record.startedAt ? new Date(record.startedAt).getTime() : null,
            completed_at: record.completedAt ? new Date(record.completedAt).getTime() : null,
            error: record.error ?? null,
            replan_cycle: record.replanCycle ? 1 : 0,
          },
        }).run()
      }
    })
  }

  savePhase(engagementId: string, record: PhaseRecord): void {
    const pe = this._ensureEngagementDb(engagementId)
    pe.drizzle.insert(phasesTable).values({
      id: record.id, engagement_id: engagementId, name: record.name, status: record.status,
      capabilities: record.capabilities, execution_mode: record.executionMode,
      started_at: record.startedAt ? new Date(record.startedAt).getTime() : null,
      completed_at: record.completedAt ? new Date(record.completedAt).getTime() : null,
      error: record.error ?? null, replan_cycle: record.replanCycle ? 1 : 0,
    }).onConflictDoUpdate({
      target: phasesTable.id,
      set: {
        name: record.name,
        status: record.status,
        capabilities: record.capabilities,
        execution_mode: record.executionMode,
        started_at: record.startedAt ? new Date(record.startedAt).getTime() : null,
        completed_at: record.completedAt ? new Date(record.completedAt).getTime() : null,
        error: record.error ?? null,
        replan_cycle: record.replanCycle ? 1 : 0,
      },
    }).run()
  }

  getPhases(id: string): PhaseRecord[] {
    // Try per-engagement DB first
    const pe = this._getEngagementDb(id)
    if (pe) {
      const rows = pe.drizzle.select().from(phasesTable)
        .where(eq(phasesTable.engagement_id, id))
        .orderBy(asc(phasesTable.id))
        .all()
      return rows.map(toPhaseRecord)
    }

    // Fallback to root DB (legacy data). May not have phases table.
    try {
      const rows = this.rootDb.select().from(phasesTable)
        .where(eq(phasesTable.engagement_id, id))
        .orderBy(asc(phasesTable.id))
        .all()
      return rows.map(toPhaseRecord)
    } catch { return [] }
  }

  // ── Findings (per-engagement DB with fallback) ──

  saveFindings(engagementId: string, records: NormalizedFinding[]): void {
    const pe = this._ensureEngagementDb(engagementId)
    pe.drizzle.transaction((tx) => {
      for (const record of records) {
        const row = toFindingRow(record, engagementId)
        const { id, engagement_id, ...updateFields } = row
        tx.insert(findingsTable).values(row).onConflictDoUpdate({
          target: findingsTable.id,
          set: updateFields,
        }).run()
      }
    })
  }

  getFinding(id: string): NormalizedFinding | null {
    // 1. Search cached per-engagement DBs (fast path)
    for (const [, entry] of this.engagementDbs) {
      const rows = entry.drizzle.select().from(findingsTable).where(eq(findingsTable.id, id)).all()
      if (rows.length > 0) return toNormalizedFinding(rows[0])
    }

    // 2. Fallback to root DB (legacy data). Wrap in try-catch because the
    //    root DB may not have a findings table (per-engagement storage only).
    try {
      const rootRows = this.rootDb.select().from(findingsTable).where(eq(findingsTable.id, id)).all()
      if (rootRows.length > 0) return toNormalizedFinding(rootRows[0])
    } catch { /* table may not exist — not a legacy engagement */ }

    // 3. Scan uncached per-engagement DBs (storage_version >= 2)
    const allEngs = this.listEngagements()
    for (const eng of allEngs) {
      if (eng.storageVersion >= STORAGE_VERSION_PER_ENGAGEMENT) {
        const pe = this._getEngagementDb(eng.id)
        if (pe) {
          const rows = pe.drizzle.select().from(findingsTable).where(eq(findingsTable.id, id)).all()
          if (rows.length > 0) return toNormalizedFinding(rows[0])
        }
      }
    }

    return null
  }

  getFindingEngagementId(findingId: string): string | null {
    // 1. Search cached per-engagement DBs first (fast path)
    for (const [, entry] of this.engagementDbs) {
      const rows = entry.drizzle
        .select({ engagement_id: findingsTable.engagement_id })
        .from(findingsTable)
        .where(eq(findingsTable.id, findingId))
        .all()
      if (rows.length > 0) return rows[0].engagement_id
    }

    // 2. Search root DB (legacy data). Wrap in try-catch because the
    //    root DB may not have a findings table (per-engagement storage only).
    try {
      const rootRows = this.rootDb
        .select({ engagement_id: findingsTable.engagement_id })
        .from(findingsTable)
        .where(eq(findingsTable.id, findingId))
        .all()
      if (rootRows.length > 0) return rootRows[0].engagement_id
    } catch { /* table may not exist — not a legacy engagement */ }

    // 3. Scan all per-engagement DBs for uncached findings
    //    (engagement has storage_version >= 2 but DB not yet opened)
    const allEngs = this.listEngagements()
    for (const eng of allEngs) {
      if (eng.storageVersion >= STORAGE_VERSION_PER_ENGAGEMENT) {
        const pe = this._getEngagementDb(eng.id)
        if (pe) {
          const rows = pe.drizzle
            .select({ engagement_id: findingsTable.engagement_id })
            .from(findingsTable)
            .where(eq(findingsTable.id, findingId))
            .all()
          if (rows.length > 0) return rows[0].engagement_id
        }
      }
    }

    return null
  }

  getFindings(engagementId: string): NormalizedFinding[] {
    // Try per-engagement DB first
    const pe = this._getEngagementDb(engagementId)
    if (pe) {
      const rows = pe.drizzle.select().from(findingsTable)
        .where(eq(findingsTable.engagement_id, engagementId))
        .orderBy(desc(findingsTable.severity))
        .all()
      return rows.map(toNormalizedFinding)
    }

    // Fallback to root DB (legacy data). May not have findings table.
    try {
      const rows = this.rootDb.select().from(findingsTable)
        .where(eq(findingsTable.engagement_id, engagementId))
        .orderBy(desc(findingsTable.severity))
        .all()
      return rows.map(toNormalizedFinding)
    } catch { return [] }
  }

  getFindingCountsByEngagementIds(ids: string[]): Map<string, { total: number; critical: number; confirmed: number }> {
    if (ids.length === 0) return new Map()

    const result = new Map<string, { total: number; critical: number; confirmed: number }>()

    // For each engagement, try per-engagement DB first, then root DB
    for (const id of ids) {
      let rows: Array<{ engagementId: string; total: number; critical: number; confirmed: number }> = []

      // Try per-engagement DB
      const pe = this._getEngagementDb(id)
      if (pe) {
        rows = pe.drizzle
          .select({
            engagementId: sql<string>`${id}`.as("engagementId"),
            total: sql<number>`count(*)`.as("total"),
            critical: sql<number>`sum(case when ${findingsTable.severity} >= 4 then 1 else 0 end)`.as("critical"),
            confirmed: sql<number>`sum(case when ${findingsTable.status} in ('CONFIRMED', 'FINALIZED') then 1 else 0 end)`.as("confirmed"),
          })
          .from(findingsTable)
          .where(eq(findingsTable.engagement_id, id))
          .groupBy(findingsTable.engagement_id)
          .all()
      } else {
        // Root DB fallback — may not have findings table
        try {
          rows = this.rootDb
            .select({
              engagementId: findingsTable.engagement_id,
              total: sql<number>`count(*)`.as("total"),
              critical: sql<number>`sum(case when ${findingsTable.severity} >= 4 then 1 else 0 end)`.as("critical"),
              confirmed: sql<number>`sum(case when ${findingsTable.status} in ('CONFIRMED', 'FINALIZED') then 1 else 0 end)`.as("confirmed"),
            })
            .from(findingsTable)
            .where(eq(findingsTable.engagement_id, id))
            .groupBy(findingsTable.engagement_id)
            .all()
        } catch { /* root DB may not have findings table */ }
      }

      if (rows.length > 0) {
        result.set(id, { total: rows[0].total, critical: rows[0].critical, confirmed: rows[0].confirmed })
      }
    }

    return result
  }

  // ── Audit log (per-engagement DB with fallback) ──

  appendAuditLog(engagementId: string, eventType: string, message: string, metadata?: Record<string, unknown>): void {
    const pe = this._ensureEngagementDb(engagementId)
    const now = Date.now()
    pe.drizzle.insert(audit_log).values({
      id: `aud-${now.toString(36)}-${(_auditSeq++).toString(36)}`,
      engagement_id: engagementId,
      event_type: eventType,
      message,
      metadata: metadata ?? {},
      created_at: now,
    }).run()
  }

  getAuditLog(engagementId: string): Array<{ id: string; eventType: string; message: string; metadata: Record<string, unknown>; createdAt: number }> {
    const pe = this._getEngagementDb(engagementId)
    if (pe) {
      const rows = pe.drizzle.select().from(audit_log)
        .where(eq(audit_log.engagement_id, engagementId))
        .orderBy(desc(audit_log.created_at), desc(audit_log.id))
        .all()
      return rows.map((r) => ({
        id: r.id,
        eventType: r.event_type,
        message: r.message,
        metadata: (r.metadata ?? {}) as Record<string, unknown>,
        createdAt: r.created_at,
      }))
    }

    // Fallback to root DB (legacy data). May not have audit_log table.
    try {
      const rows = this.rootDb.select().from(audit_log)
        .where(eq(audit_log.engagement_id, engagementId))
        .orderBy(desc(audit_log.created_at), desc(audit_log.id))
        .all()
      return rows.map((r) => ({
        id: r.id,
        eventType: r.event_type,
        message: r.message,
        metadata: (r.metadata ?? {}) as Record<string, unknown>,
        createdAt: r.created_at,
      }))
    } catch { return [] }
  }

  // ── Evidence (per-engagement DB with fallback) ──

  saveEvidencePackage(id: string, findingId: string, packageHash: string): void {
    // Find which engagement this finding belongs to
    const engId = this.getFindingEngagementId(findingId)
    if (!engId) throw new Error(`Cannot save evidence: finding ${findingId} not found`)
    const pe = this._ensureEngagementDb(engId)
    pe.drizzle.insert(evidence_packages).values({
      id,
      finding_id: findingId,
      package_hash: packageHash,
      created_at: Date.now(),
    }).onConflictDoUpdate({
      target: evidence_packages.id,
      set: {
        finding_id: findingId,
        package_hash: packageHash,
        created_at: Date.now(),
      },
    }).run()
  }

  getEvidencePackages(findingId: string): Array<{ id: string; packageHash: string; createdAt: number }> {
    // Search per-engagement DBs first
    for (const [, entry] of this.engagementDbs) {
      const rows = entry.drizzle.select().from(evidence_packages)
        .where(eq(evidence_packages.finding_id, findingId))
        .all()
      if (rows.length > 0) {
        return rows.map((r) => ({ id: r.id, packageHash: r.package_hash, createdAt: r.created_at }))
      }
    }

    // Fallback to root DB. May not have evidence_packages table.
    try {
      const rows = this.rootDb.select().from(evidence_packages)
        .where(eq(evidence_packages.finding_id, findingId))
        .all()
      return rows.map((r) => ({ id: r.id, packageHash: r.package_hash, createdAt: r.created_at }))
    } catch { return [] }
  }

  getEvidenceByEngagement(engagementId: string): Array<{
    findingId: string
    findingTitle: string
    packages: Array<{
      id: string
      packageHash: string
      createdAt: number
      artifacts: Array<{ id: string; path: string; type: string; sizeBytes: number }>
    }>
  }> {
    const pe = this._getEngagementDb(engagementId)
    const db = pe?.drizzle ?? this.rootDb

    // Wrap in try-catch — root DB may not have these tables
    try {
      const findings = db.select({
        id: findingsTable.id,
        title: findingsTable.title,
      }).from(findingsTable)
        .where(eq(findingsTable.engagement_id, engagementId))
        .all()

      if (findings.length === 0) return []

      const findingIds = findings.map((f) => f.id)
      const allPackages = db.select()
        .from(evidence_packages)
        .where(EngagementStore._inClause(evidence_packages.finding_id, findingIds))
        .all()

      const packageIds = allPackages.map((p) => p.id)
      const allArtifacts = packageIds.length > 0
        ? db.select()
          .from(artifacts)
          .where(EngagementStore._inClause(artifacts.package_id, packageIds))
          .all()
        : []

      const artifactsByPackageId = new Map<string, Array<{ id: string; path: string; type: string; sizeBytes: number }>>()
      for (const art of allArtifacts) {
        const list = artifactsByPackageId.get(art.package_id) ?? []
        list.push({ id: art.id, path: art.path, type: art.type, sizeBytes: art.size_bytes })
        artifactsByPackageId.set(art.package_id, list)
      }

      const packagesByFindingId = new Map<string, Array<{
        id: string; packageHash: string; createdAt: number
        artifacts: Array<{ id: string; path: string; type: string; sizeBytes: number }>
      }>>()
      for (const pkg of allPackages) {
        const list = packagesByFindingId.get(pkg.finding_id) ?? []
        list.push({
          id: pkg.id,
          packageHash: pkg.package_hash,
          createdAt: pkg.created_at,
          artifacts: artifactsByPackageId.get(pkg.id) ?? [],
        })
        packagesByFindingId.set(pkg.finding_id, list)
      }

      return findings.map((f) => ({
        findingId: f.id,
        findingTitle: f.title,
        packages: packagesByFindingId.get(f.id) ?? [],
      }))
    } catch { return [] }
  }

  private static _inClause(column: SQL | AnyColumn, values: string[]): SQL {
    if (values.length === 0) return sql`1 = 0`
    return inArray(column as SQLWrapper, values)
  }

  // ── Artifacts (per-engagement DB) ──

  saveArtifact(id: string, packageId: string, path: string, sha256: string, sizeBytes: number, type: string): void {
    // Find which engagement via the evidence package by checking all DBs
    const engId = this._findEngagementByPackage(packageId)
    if (engId) {
      // Ensure we write to the per-engagement DB (creates it if needed)
      const pe = this._ensureEngagementDb(engId)
      pe.drizzle.insert(artifacts).values({
        id, package_id: packageId, path, sha256,
        size_bytes: sizeBytes, type,
      }).onConflictDoUpdate({
        target: artifacts.id,
        set: { package_id: packageId, path, sha256, size_bytes: sizeBytes, type },
      }).run()
      return
    }

    // Fallback to root DB (legacy data). May not have artifacts table.
    try {
      this.rootDb.insert(artifacts).values({
        id, package_id: packageId, path, sha256,
        size_bytes: sizeBytes, type,
      }).onConflictDoUpdate({
        target: artifacts.id,
        set: { package_id: packageId, path, sha256, size_bytes: sizeBytes, type },
      }).run()
    } catch { /* root DB may not have artifacts table */ }
  }

  /**
   * Find which engagement a package belongs to by searching all DBs.
   * Checks cached per-engagement DBs first, then root DB, then uncached
   * per-engagement DBs.
   */
  private  _findEngagementByPackage(packageId: string): string | null {
    // 1. Check cached per-engagement DBs
    for (const [engId, entry] of this.engagementDbs) {
      const pkgRows = entry.drizzle
        .select({ finding_id: evidence_packages.finding_id })
        .from(evidence_packages)
        .where(eq(evidence_packages.id, packageId))
        .all()
      if (pkgRows.length > 0) return engId
    }

    // 2. Check root DB (legacy data). Wrap in try-catch because the
    //    root DB may not have evidence_packages/findings tables.
    try {
      const rootPkgRows = this.rootDb
        .select({ finding_id: evidence_packages.finding_id })
        .from(evidence_packages)
        .where(eq(evidence_packages.id, packageId))
        .all()
      if (rootPkgRows.length > 0) {
        const finding = this.rootDb
          .select({ engagement_id: findingsTable.engagement_id })
          .from(findingsTable)
          .where(eq(findingsTable.id, rootPkgRows[0].finding_id))
          .all()
        if (finding.length > 0) return finding[0].engagement_id
      }
    } catch { /* tables may not exist — not a legacy engagement */ }

    // 3. Check uncached per-engagement DBs
    const allEngs = this.listEngagements()
    for (const eng of allEngs) {
      if (eng.storageVersion >= STORAGE_VERSION_PER_ENGAGEMENT) {
        const pe = this._getEngagementDb(eng.id)
        if (pe) {
          const pkgRows = pe.drizzle
            .select({ finding_id: evidence_packages.finding_id })
            .from(evidence_packages)
            .where(eq(evidence_packages.id, packageId))
            .all()
          if (pkgRows.length > 0) {
            this.engagementDbs.get(eng.id)!.lastAccessed = Date.now()
            return eng.id
          }
        }
      }
    }

    return null
  }

  getArtifacts(packageId: string): Array<{ id: string; path: string; sha256: string; sizeBytes: number; type: string }> {
    for (const [, entry] of this.engagementDbs) {
      const rows = entry.drizzle.select().from(artifacts)
        .where(eq(artifacts.package_id, packageId))
        .all()
      if (rows.length > 0) {
        return rows.map((r) => ({ id: r.id, path: r.path, sha256: r.sha256, sizeBytes: r.size_bytes, type: r.type }))
      }
    }

    // Fallback to root DB. May not have artifacts table.
    try {
      const rows = this.rootDb.select().from(artifacts)
        .where(eq(artifacts.package_id, packageId))
        .all()
      return rows.map((r) => ({ id: r.id, path: r.path, sha256: r.sha256, sizeBytes: r.size_bytes, type: r.type }))
    } catch { return [] }
  }

  getEvidenceCountsByEngagement(engagementId: string): Record<string, number> {
    const pe = this._getEngagementDb(engagementId)
    const db = pe?.drizzle ?? this.rootDb

    let rows: Array<{ findingId: string; count: number }>
    try {
      rows = db
        .select({
          findingId: findingsTable.id,
          count: sql<number>`count(${artifacts.id})`.as("artifact_count"),
        })
        .from(findingsTable)
        .leftJoin(evidence_packages, eq(evidence_packages.finding_id, findingsTable.id))
        .leftJoin(artifacts, eq(artifacts.package_id, evidence_packages.id))
        .where(eq(findingsTable.engagement_id, engagementId))
        .groupBy(findingsTable.id)
        .all()
    } catch { return {} }
    const result: Record<string, number> = {}
    for (const row of rows) {
      result[row.findingId] = row.count
    }
    return result
  }

  // ── Engagement detail ──

  getEngagementDetail(engagementId: string): {
    engagement: EngagementState
    findings: NormalizedFinding[]
    evidence: ReturnType<IEngagementStore["getEvidenceByEngagement"]>
    auditLog: ReturnType<IEngagementStore["getAuditLog"]>
  } | null {
    const eng = this.getEngagement(engagementId)
    if (!eng) return null
    return {
      engagement: eng,
      findings: this.getFindings(engagementId),
      evidence: this.getEvidenceByEngagement(engagementId),
      auditLog: this.getAuditLog(engagementId),
    }
  }

  // ── Workflow snapshots (per-engagement DB with fallback) ──

  saveWorkflowSnapshot(id: string, engagementId: string, workflowName: string, workflowVersion: number, workflowYaml: string): void {
    const pe = this._ensureEngagementDb(engagementId)
    pe.drizzle.insert(workflow_snapshots).values({
      id,
      engagement_id: engagementId,
      workflow_name: workflowName,
      workflow_version: workflowVersion,
      workflow_yaml: workflowYaml,
      created_at: Date.now(),
    }).run()
  }

  getWorkflowSnapshots(engagementId: string): Array<{ id: string; workflowName: string; workflowVersion: number; workflowYaml: string; createdAt: number }> {
    const pe = this._getEngagementDb(engagementId)
    const db = pe?.drizzle ?? this.rootDb
    try {
      const rows = db.select().from(workflow_snapshots)
        .where(eq(workflow_snapshots.engagement_id, engagementId))
        .all()
      return rows.map((r) => ({
        id: r.id,
        workflowName: r.workflow_name,
        workflowVersion: r.workflow_version,
        workflowYaml: r.workflow_yaml,
        createdAt: r.created_at,
      }))
    } catch { return [] }
  }

  // ── Finding analysis (per-engagement DB with fallback) ──

  saveFindingAnalysis(analysis: FindingAnalysis): void {
    const finding = this.getFinding(analysis.findingId)
    if (!finding) throw new Error(`Cannot save analysis: finding ${analysis.findingId} not found`)
    const engId = this.getFindingEngagementId(analysis.findingId)
    if (!engId) throw new Error(`Cannot save analysis: finding ${analysis.findingId} has no engagement`)
    const pe = this._ensureEngagementDb(engId)
    pe.drizzle.insert(finding_analysis).values({
      finding_id: analysis.findingId,
      explanation: analysis.explanation,
      impact: JSON.stringify(analysis.impact),
      remediation: JSON.stringify(analysis.remediation),
      refs: analysis.references ? JSON.stringify(analysis.references) : null,
      model: analysis.model,
      generated_at: analysis.generatedAt,
      finding_updated_at: analysis.findingUpdatedAt,
    }).onConflictDoUpdate({
      target: finding_analysis.finding_id,
      set: {
        explanation: analysis.explanation,
        impact: JSON.stringify(analysis.impact),
        remediation: JSON.stringify(analysis.remediation),
        refs: analysis.references ? JSON.stringify(analysis.references) : null,
        model: analysis.model,
        generated_at: analysis.generatedAt,
        finding_updated_at: analysis.findingUpdatedAt,
      },
    }).run()
  }

  getFindingAnalysis(findingId: string): FindingAnalysis | null {
    for (const [, entry] of this.engagementDbs) {
      const rows = entry.drizzle.select().from(finding_analysis)
        .where(eq(finding_analysis.finding_id, findingId))
        .all()
      if (rows.length > 0) return this._parseAnalysisRow(rows[0])
    }

    // Fallback to root DB (legacy data). May not have finding_analysis table.
    try {
      const rows = this.rootDb.select().from(finding_analysis)
        .where(eq(finding_analysis.finding_id, findingId))
        .all()
      if (rows.length === 0) return null
      return this._parseAnalysisRow(rows[0])
    } catch { return null }
  }

  private _parseAnalysisRow(row: typeof finding_analysis.$inferSelect): FindingAnalysis | null {
    try {
      return {
        findingId: row.finding_id,
        explanation: row.explanation,
        impact: JSON.parse(row.impact),
        remediation: JSON.parse(row.remediation),
        references: row.refs ? JSON.parse(row.refs) : undefined,
        model: row.model,
        generatedAt: row.generated_at,
        findingUpdatedAt: row.finding_updated_at,
      }
    } catch {
      return null
    }
  }

  deleteFindingAnalysis(findingId: string): void {
    // Try per-engagement DBs first
    for (const [, entry] of this.engagementDbs) {
      try {
        entry.drizzle.delete(finding_analysis)
          .where(eq(finding_analysis.finding_id, findingId))
          .run()
        return
      } catch { /* not in this DB */ }
    }

    // Fallback to root DB. May not have finding_analysis table.
    try {
      this.rootDb.delete(finding_analysis)
        .where(eq(finding_analysis.finding_id, findingId))
        .run()
    } catch { /* root DB may not have finding_analysis table */ }
  }

  getValidAnalysis(findingId: string): FindingAnalysis | null {
    const cached = this.getFindingAnalysis(findingId)
    if (!cached) return null
    const finding = this.getFinding(findingId)
    if (!finding) return null
    if (new Date(finding.updated_at).getTime() > cached.findingUpdatedAt) {
      return null
    }
    return cached
  }
}

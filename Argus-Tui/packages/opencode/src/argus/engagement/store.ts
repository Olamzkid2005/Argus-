import { Database } from "bun:sqlite"
import { drizzle } from "drizzle-orm/bun-sqlite"
import { eq, desc, sql } from "drizzle-orm"
import { join } from "path"
import { homedir } from "os"
import { mkdirSync, existsSync } from "fs"
import {
  engagements,
  findings as findingsTable,
  phases as phasesTable,
  audit_log,
} from "./schema.sql"
import type { EngagementState, PhaseRecord, EngagementStatus, PhaseStatus } from "./types"
import type { NormalizedFinding } from "../planner/types"

const DEFAULT_DB_PATH = join(homedir(), ".argus", "argus.db")

function toEngagementState(row: typeof engagements.$inferSelect): EngagementState {
  return {
    id: row.id,
    target: row.target,
    workflow: row.workflow,
    workflowVersion: row.workflow_version,
    status: row.status as EngagementStatus,
    schemaVersion: row.schema_version,
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
    executionMode: row.execution_mode ?? "",
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
    created_at: new Date(row.created_at).toISOString(),
    updated_at: new Date(row.updated_at).toISOString(),
    finalized_at: row.finalized_at ? new Date(row.finalized_at).toISOString() : undefined,
  }
}

export class EngagementStore {
  private db: ReturnType<typeof drizzle>

  constructor(dbPath?: string) {
    const path = dbPath ?? DEFAULT_DB_PATH
    const dir = join(path, "..")
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }
    const sqlite = new Database(path)
    sqlite.exec("PRAGMA journal_mode = WAL")
    sqlite.exec("PRAGMA foreign_keys = ON")
    this.db = drizzle({ client: sqlite })
    this.ensureTables()
  }

  private ensureTables(): void {
    this.db.run(sql`
      CREATE TABLE IF NOT EXISTS engagements (
        id TEXT PRIMARY KEY,
        target TEXT NOT NULL,
        workflow TEXT NOT NULL,
        workflow_version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'CREATED',
        schema_version INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
      )
    `)
    this.db.run(sql`
      CREATE TABLE IF NOT EXISTS findings (
        id TEXT PRIMARY KEY,
        engagement_id TEXT NOT NULL REFERENCES engagements(id),
        title TEXT NOT NULL,
        severity INTEGER NOT NULL,
        confidence INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        description TEXT,
        subtype TEXT,
        cve TEXT,
        cwe TEXT,
        owasp TEXT,
        remediation TEXT,
        tool TEXT,
        phase TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        finalized_at INTEGER
      )
    `)
    this.db.run(sql`
      CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id)
    `)
    this.db.run(sql`
      CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status)
    `)
    this.db.run(sql`
      CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)
    `)
    this.db.run(sql`
      CREATE TABLE IF NOT EXISTS phases (
        id TEXT PRIMARY KEY,
        engagement_id TEXT NOT NULL REFERENCES engagements(id),
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        capabilities TEXT DEFAULT '[]',
        execution_mode TEXT,
        started_at INTEGER,
        completed_at INTEGER,
        error TEXT,
        replan_cycle INTEGER NOT NULL DEFAULT 0
      )
    `)
    this.db.run(sql`
      CREATE INDEX IF NOT EXISTS idx_phases_engagement ON phases(engagement_id)
    `)
    this.db.run(sql`
      CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        engagement_id TEXT NOT NULL REFERENCES engagements(id),
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        metadata TEXT DEFAULT '{}',
        created_at INTEGER NOT NULL
      )
    `)
    this.db.run(sql`
      CREATE INDEX IF NOT EXISTS idx_audit_log_engagement ON audit_log(engagement_id)
    `)
  }

  createEngagement(target: string, workflow: string): EngagementState {
    const id = `ENG-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
    const now = Date.now()

    this.db.insert(engagements).values({
      id,
      target,
      workflow,
      workflow_version: 1,
      status: "CREATED",
      schema_version: 1,
      created_at: now,
      updated_at: now,
    }).run()

    return this.getEngagement(id)!
  }

  getEngagement(id: string): EngagementState | null {
    const rows = this.db.select().from(engagements).where(eq(engagements.id, id)).all()
    if (rows.length === 0) return null
    return toEngagementState(rows[0])
  }

  saveEngagement(engagement: EngagementState): void {
    this.db.update(engagements)
      .set({
        target: engagement.target,
        workflow: engagement.workflow,
        workflow_version: engagement.workflowVersion,
        status: engagement.status,
        schema_version: engagement.schemaVersion,
        updated_at: Date.now(),
      })
      .where(eq(engagements.id, engagement.id))
      .run()
  }

  updateStatus(id: string, status: EngagementStatus): void {
    this.db.update(engagements)
      .set({ status, updated_at: Date.now() })
      .where(eq(engagements.id, id))
      .run()
  }

  listEngagements(): EngagementState[] {
    const rows = this.db.select().from(engagements).orderBy(desc(engagements.created_at)).all()
    return rows.map(toEngagementState)
  }

  savePhases(id: string, records: PhaseRecord[]): void {
    this.db.delete(phasesTable).where(eq(phasesTable.engagement_id, id)).run()
    for (const record of records) {
      this.db.insert(phasesTable).values({
        id: record.id,
        engagement_id: id,
        name: record.name,
        status: record.status,
        capabilities: record.capabilities,
        execution_mode: record.executionMode,
        started_at: record.startedAt ? new Date(record.startedAt).getTime() : null,
        completed_at: record.completedAt ? new Date(record.completedAt).getTime() : null,
        error: record.error ?? null,
        replan_cycle: record.replanCycle ? 1 : 0,
      }).run()
    }
  }

  getPhases(id: string): PhaseRecord[] {
    const rows = this.db.select().from(phasesTable).where(eq(phasesTable.engagement_id, id)).all()
    return rows.map(toPhaseRecord)
  }

  saveFindings(engagementId: string, records: NormalizedFinding[]): void {
    this.db.delete(findingsTable).where(eq(findingsTable.engagement_id, engagementId)).run()
    for (const record of records) {
      this.db.insert(findingsTable).values(toFindingRow(record, engagementId)).run()
    }
  }

  getFindings(engagementId: string): NormalizedFinding[] {
    const rows = this.db.select().from(findingsTable)
      .where(eq(findingsTable.engagement_id, engagementId))
      .orderBy(desc(findingsTable.severity))
      .all()
    return rows.map(toNormalizedFinding)
  }

  appendAuditLog(engagementId: string, eventType: string, message: string, metadata?: Record<string, unknown>): void {
    this.db.insert(audit_log).values({
      id: `aud-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      engagement_id: engagementId,
      event_type: eventType,
      message,
      metadata: metadata ?? {},
      created_at: Date.now(),
    }).run()
  }

  getDbPath(): string {
    return DEFAULT_DB_PATH
  }
}

import { Database } from "bun:sqlite"
import { drizzle } from "drizzle-orm/bun-sqlite"
import { eq, desc, asc, sql } from "drizzle-orm"
import { join, dirname } from "path"
import { homedir } from "os"
import { mkdirSync, existsSync, readFileSync } from "fs"
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
} from "./schema.sql"
import type { EngagementState, PhaseRecord, EngagementStatus, PhaseStatus } from "./types"
import type { ExecutionMode } from "../shared/types"
import type { FindingAnalysis, NormalizedFinding } from "../shared/types"

function defaultDbPath(): string {
  return join(homedir(), ".argus", "argus.db")
}

const TABLE_SQL = [
  sql`CREATE TABLE IF NOT EXISTS engagements (
    id TEXT PRIMARY KEY, target TEXT NOT NULL, workflow TEXT NOT NULL,
    workflow_version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'CREATED',
    schema_version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
  )`,
  sql`CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL REFERENCES engagements(id),
    title TEXT NOT NULL, severity INTEGER NOT NULL, confidence INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', description TEXT, subtype TEXT, cve TEXT, cwe TEXT,
    owasp TEXT, remediation TEXT, tool TEXT, phase TEXT, created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL, finalized_at INTEGER, negative INTEGER NOT NULL DEFAULT 0
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id)`,
  sql`CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status)`,
  sql`CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)`,
  sql`CREATE TABLE IF NOT EXISTS phases (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL REFERENCES engagements(id),
    name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', capabilities TEXT DEFAULT '[]',
    execution_mode TEXT, started_at INTEGER, completed_at INTEGER, error TEXT,
    replan_cycle INTEGER NOT NULL DEFAULT 0
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_phases_engagement ON phases(engagement_id)`,
  sql`CREATE INDEX IF NOT EXISTS idx_phases_engagement_replan ON phases(engagement_id, replan_cycle)`,
  sql`CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL REFERENCES engagements(id),
    event_type TEXT NOT NULL, message TEXT NOT NULL, metadata TEXT DEFAULT '{}',
    created_at INTEGER NOT NULL
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_audit_log_engagement ON audit_log(engagement_id)`,
  sql`CREATE TABLE IF NOT EXISTS tool_execution_log (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL REFERENCES engagements(id),
    tool_name TEXT NOT NULL, target_type TEXT NOT NULL, capability TEXT NOT NULL,
    succeeded INTEGER NOT NULL, duration_ms INTEGER NOT NULL, created_at INTEGER NOT NULL
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_tool_exec_engagement ON tool_execution_log(engagement_id)`,
  sql`CREATE INDEX IF NOT EXISTS idx_tool_exec_tool ON tool_execution_log(tool_name)`,
  sql`CREATE INDEX IF NOT EXISTS idx_tool_exec_capability ON tool_execution_log(capability)`,
  sql`CREATE TABLE IF NOT EXISTS evidence_packages (
    id TEXT PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(id),
    package_hash TEXT NOT NULL, created_at INTEGER NOT NULL
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_evidence_packages_finding ON evidence_packages(finding_id)`,
  sql`CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES evidence_packages(id),
    path TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, type TEXT NOT NULL
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_artifacts_package ON artifacts(package_id)`,
  sql`CREATE TABLE IF NOT EXISTS workflow_snapshots (
    id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL REFERENCES engagements(id),
    workflow_name TEXT NOT NULL, workflow_version INTEGER NOT NULL,
    workflow_yaml TEXT NOT NULL, created_at INTEGER NOT NULL
  )`,
  sql`CREATE INDEX IF NOT EXISTS idx_workflow_snapshots_engagement ON workflow_snapshots(engagement_id)`,
  sql`CREATE TABLE IF NOT EXISTS finding_analysis (
    finding_id TEXT PRIMARY KEY,
    explanation TEXT NOT NULL, impact TEXT NOT NULL, remediation TEXT NOT NULL,
    refs TEXT, model TEXT NOT NULL,
    generated_at INTEGER NOT NULL, finding_updated_at INTEGER NOT NULL,
    FOREIGN KEY (finding_id) REFERENCES findings(id) ON DELETE CASCADE
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
    // NOTE: null coalesces to [] — original null vs empty distinction is lost
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

export class EngagementStore {
  private db: ReturnType<typeof drizzle>
  readonly dbPath: string

  constructor(dbPath?: string) {
    this.dbPath = dbPath ?? defaultDbPath()
    const dir = join(this.dbPath, "..")
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }
    const sqlite = new Database(this.dbPath)
    sqlite.exec("PRAGMA journal_mode = WAL")
    sqlite.exec("PRAGMA foreign_keys = ON")
    this.db = drizzle({ client: sqlite })
    this.ensureTables()
  }

  private ensureTables(): void {
    for (const stmt of TABLE_SQL) {
      this.db.run(stmt)
    }
    // Migration: add negative column to findings for existing databases
    try {
      this.db.run(sql`ALTER TABLE findings ADD COLUMN negative INTEGER NOT NULL DEFAULT 0`)
    } catch { /* column already exists — ignore */ }
  }

  createEngagement(target: string, workflow: string): EngagementState {
    const id = `ENG-${Date.now().toString(36)}-${(_engagementSeq++).toString(36)}`
    const now = Date.now()

    this.db.insert(engagements).values({
      id, target, workflow,
      workflow_version: 1, status: "CREATED", schema_version: 1,
      created_at: now, updated_at: now,
    }).run()

    const result = this.getEngagement(id)
    if (!result) throw new Error(`Failed to create engagement ${id}: insert succeeded but read-back failed`)
    return result
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
    const rows = this.db.select().from(engagements).orderBy(desc(engagements.created_at), desc(engagements.id)).all()
    return rows.map(toEngagementState)
  }

  savePhases(id: string, records: PhaseRecord[]): void {
    this.db.transaction((tx) => {
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
    this.db.insert(phasesTable).values({
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
    const rows = this.db.select().from(phasesTable)
      .where(eq(phasesTable.engagement_id, id))
      .orderBy(asc(phasesTable.id))
      .all()
    return rows.map(toPhaseRecord)
  }

  saveFindings(engagementId: string, records: NormalizedFinding[]): void {
    this.db.transaction((tx) => {
      for (const record of records) {
        const row = toFindingRow(record, engagementId)
        // Destructure out PK and FK — no need to SET them on conflict update
        const { id, engagement_id, ...updateFields } = row
        tx.insert(findingsTable).values(row).onConflictDoUpdate({
          target: findingsTable.id,
          set: updateFields,
        }).run()
      }
    })
  }

  getFinding(id: string): NormalizedFinding | null {
    const rows = this.db.select().from(findingsTable).where(eq(findingsTable.id, id)).all()
    if (rows.length === 0) return null
    return toNormalizedFinding(rows[0])
  }

  getFindings(engagementId: string): NormalizedFinding[] {
    const rows = this.db.select().from(findingsTable)
      .where(eq(findingsTable.engagement_id, engagementId))
      .orderBy(desc(findingsTable.severity))
      .all()
    return rows.map(toNormalizedFinding)
  }

  appendAuditLog(engagementId: string, eventType: string, message: string, metadata?: Record<string, unknown>): void {
    const now = Date.now()
    this.db.insert(audit_log).values({
      id: `aud-${now.toString(36)}-${(_auditSeq++).toString(36)}`,
      engagement_id: engagementId,
      event_type: eventType,
      message,
      metadata: metadata ?? {},
      created_at: now,
    }).run()
  }

  getAuditLog(engagementId: string): Array<{ id: string; eventType: string; message: string; metadata: Record<string, unknown>; createdAt: number }> {
    const rows = this.db.select().from(audit_log)
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

  saveEvidencePackage(id: string, findingId: string, packageHash: string): void {
    this.db.insert(evidence_packages).values({
      id,
      finding_id: findingId,
      package_hash: packageHash,
      created_at: Date.now(),
    }).run()
  }

  getEvidencePackages(findingId: string): Array<{ id: string; packageHash: string; createdAt: number }> {
    const rows = this.db.select().from(evidence_packages)
      .where(eq(evidence_packages.finding_id, findingId))
      .all()
    return rows.map((r) => ({ id: r.id, packageHash: r.package_hash, createdAt: r.created_at }))
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
    const findings = this.db.select().from(findingsTable)
      .where(eq(findingsTable.engagement_id, engagementId))
      .all()
    const result: Array<{
      findingId: string
      findingTitle: string
      packages: Array<{
        id: string
        packageHash: string
        createdAt: number
        artifacts: Array<{ id: string; path: string; type: string; sizeBytes: number }>
      }>
    }> = []
    for (const f of findings) {
      const packages = this.db.select().from(evidence_packages)
        .where(eq(evidence_packages.finding_id, f.id))
        .all()
      const pkgList = packages.map((p) => {
        const arts = this.db.select().from(artifacts)
          .where(eq(artifacts.package_id, p.id))
          .all()
        return {
          id: p.id,
          packageHash: p.package_hash,
          createdAt: p.created_at,
          artifacts: arts.map((a) => ({
            id: a.id,
            path: a.path,
            type: a.type,
            sizeBytes: a.size_bytes,
          })),
        }
      })
      result.push({ findingId: f.id, findingTitle: f.title, packages: pkgList })
    }
    return result
  }

  saveArtifact(id: string, packageId: string, path: string, sha256: string, sizeBytes: number, type: string): void {
    this.db.insert(artifacts).values({
      id,
      package_id: packageId,
      path,
      sha256,
      size_bytes: sizeBytes,
      type,
    }).run()
  }

  getArtifacts(packageId: string): Array<{ id: string; path: string; sha256: string; sizeBytes: number; type: string }> {
    const rows = this.db.select().from(artifacts)
      .where(eq(artifacts.package_id, packageId))
      .all()
    return rows.map((r) => ({ id: r.id, path: r.path, sha256: r.sha256, sizeBytes: r.size_bytes, type: r.type }))
  }

  getEvidenceCountsByEngagement(engagementId: string): Record<string, number> {
    const rows = this.db
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
    const result: Record<string, number> = {}
    for (const row of rows) {
      result[row.findingId] = row.count
    }
    return result
  }

  saveWorkflowSnapshot(id: string, engagementId: string, workflowName: string, workflowVersion: number, workflowYaml: string): void {
    this.db.insert(workflow_snapshots).values({
      id,
      engagement_id: engagementId,
      workflow_name: workflowName,
      workflow_version: workflowVersion,
      workflow_yaml: workflowYaml,
      created_at: Date.now(),
    }).run()
  }

  getWorkflowSnapshots(engagementId: string): Array<{ id: string; workflowName: string; workflowVersion: number; workflowYaml: string; createdAt: number }> {
    const rows = this.db.select().from(workflow_snapshots)
      .where(eq(workflow_snapshots.engagement_id, engagementId))
      .all()
    return rows.map((r) => ({
      id: r.id,
      workflowName: r.workflow_name,
      workflowVersion: r.workflow_version,
      workflowYaml: r.workflow_yaml,
      createdAt: r.created_at,
    }))
  }

  saveFindingAnalysis(analysis: FindingAnalysis): void {
    this.db.insert(finding_analysis).values({
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
    const rows = this.db.select().from(finding_analysis)
      .where(eq(finding_analysis.finding_id, findingId))
      .all()
    if (rows.length === 0) return null
    const row = rows[0]
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
    this.db.delete(finding_analysis)
      .where(eq(finding_analysis.finding_id, findingId))
      .run()
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

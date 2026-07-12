import { sqliteTable, text, integer, real, index, foreignKey } from "drizzle-orm/sqlite-core"

/** Storage version flags for per-engagement DB migration (Item 14b).
 *  1 = legacy single-DB mode (all tables in argus.db)
 *  2 = per-engagement DB exists (ENG-xxx/engagement.db)
 *  3 = per-engagement DB, encrypted (future — Item 14c)
 */
export const STORAGE_VERSION_LEGACY = 1
/** Per-engagement DB exists (ENG-xxx/engagement.db) */
export const STORAGE_VERSION_PER_ENGAGEMENT = 2
/** Per-engagement DB, encrypted (future — Item 14c) */
export const STORAGE_VERSION_ENCRYPTED = 3

export const engagements = sqliteTable("engagements", {
  id: text().primaryKey(),
  target: text().notNull(),
  workflow: text().notNull(),
  workflow_version: integer().notNull().default(1),
  status: text().notNull().default("CREATED"),
  schema_version: integer().notNull().default(1),
  /**
   * Storage version for the engagement data.
   * 1 = legacy single-DB (all tables in argus.db)
   * 2 = per-engagement DB exists at StoragePaths.engagementDbPath(id)
   * 3 = per-engagement DB, encrypted
   */
  storage_version: integer().notNull().default(STORAGE_VERSION_LEGACY),
  /**
   * Optimistic concurrency version. Incremented on every update.
   * Added via ALTER TABLE migration (ADD_VERSION_COLUMN_SQL in store.ts).
   * Defined here so Drizzle's type system recognizes the column.
   */
  version: integer().notNull().default(1),
  created_at: integer().notNull().$default(() => Date.now()),
  updated_at: integer().notNull().$onUpdate(() => Date.now()),
})

export const findings = sqliteTable("findings", {
  id: text().primaryKey(),
  engagement_id: text().notNull().references(() => engagements.id, { onDelete: "cascade" }),
  title: text().notNull(),
  severity: integer().notNull(),
  confidence: integer().notNull(),
  status: text().notNull().default("PENDING"),
  description: text(),
  subtype: text(),
  cve: text(),
  cwe: text(),
  owasp: text(),
  remediation: text(),
  tool: text(),
  phase: text(),
  created_at: integer().notNull().$default(() => Date.now()),
  updated_at: integer().notNull().$onUpdate(() => Date.now()),
  finalized_at: integer(),
  negative: integer({ mode: "boolean" }).notNull().default(false),
}, (table) => [
  index("idx_findings_engagement").on(table.engagement_id),
  index("idx_findings_status").on(table.status),
  index("idx_findings_severity").on(table.severity),
  index("idx_findings_engagement_status_severity").on(table.engagement_id, table.status, table.severity),
])

export const evidence_packages = sqliteTable("evidence_packages", {
  id: text().primaryKey(),
  finding_id: text().notNull().references(() => findings.id, { onDelete: "cascade" }),
  package_hash: text().notNull(),
  created_at: integer().notNull().$default(() => Date.now()),
}, (table) => [
  index("idx_evidence_packages_finding").on(table.finding_id),
])

export const artifacts = sqliteTable("artifacts", {
  id: text().primaryKey(),
  package_id: text().notNull().references(() => evidence_packages.id, { onDelete: "cascade" }),
  path: text().notNull(),
  sha256: text().notNull(),
  size_bytes: integer().notNull(),
  type: text().notNull(),
}, (table) => [
  index("idx_artifacts_package").on(table.package_id),
])

export const workflow_snapshots = sqliteTable("workflow_snapshots", {
  id: text().primaryKey(),
  engagement_id: text().notNull().references(() => engagements.id, { onDelete: "cascade" }),
  workflow_name: text().notNull(),
  workflow_version: integer().notNull(),
  workflow_yaml: text().notNull(),
  created_at: integer().notNull().$default(() => Date.now()),
}, (table) => [
  index("idx_workflow_snapshots_engagement").on(table.engagement_id),
])

export const phases = sqliteTable("phases", {
  id: text().primaryKey(),
  engagement_id: text().notNull().references(() => engagements.id, { onDelete: "cascade" }),
  name: text().notNull(),
  status: text().notNull().default("PENDING"),
  capabilities: text({ mode: "json" }).$type<string[]>(),
  execution_mode: text(),
  started_at: integer(),
  completed_at: integer(),
  error: text(),
  replan_cycle: integer().notNull().default(0),
}, (table) => [
  index("idx_phases_engagement").on(table.engagement_id),
  index("idx_phases_engagement_replan").on(table.engagement_id, table.replan_cycle),
])

/**
 * Tool execution log — records outcomes for adaptive scoring (Task 11).
 * Writing to this table is optional; the adaptive scoring feedback loop
 * is deferred to v6. The table exists now so the schema is ready when
 * execution data needs to be collected.
 * Fields: tool_name, target_type, capability, succeeded, duration_ms, engagement_id, created_at
 */
export const tool_execution_log = sqliteTable("tool_execution_log", {
  id: text().primaryKey(),
  engagement_id: text().notNull().references(() => engagements.id, { onDelete: "cascade" }),
  tool_name: text().notNull(),
  target_type: text().notNull(),
  capability: text().notNull(),
  succeeded: integer({ mode: "boolean" }).notNull(),
  duration_ms: integer().notNull(),
  created_at: integer().notNull().$default(() => Date.now()),
}, (table) => [
  index("idx_tool_exec_engagement").on(table.engagement_id),
  index("idx_tool_exec_tool").on(table.tool_name),
  index("idx_tool_exec_capability").on(table.capability),
])

export const finding_analysis = sqliteTable("finding_analysis", {
  finding_id: text().primaryKey(),
  explanation: text().notNull(),
  impact: text().notNull(),
  remediation: text().notNull(),
  refs: text(),
  model: text().notNull(),
  generated_at: integer().notNull(),
  finding_updated_at: integer().notNull(),
}, (table) => [
  foreignKey({ columns: [table.finding_id], foreignColumns: [findings.id], onDelete: "cascade" } as any),
])

export const extracted_credentials = sqliteTable("extracted_credentials", {
  id: text().primaryKey(),
  engagement_id: text().notNull().references(() => engagements.id, { onDelete: "cascade" }),
  credential_type: text().notNull(),
  value: text().notNull(),
  source_finding_type: text().notNull(),
  source_endpoint: text().notNull(),
  confidence: real().notNull(),
  replayed: integer({ mode: "boolean" }).notNull().default(false),
  replay_target: text(),
  replay_success: integer({ mode: "boolean" }),
  created_at: integer().notNull().$default(() => Date.now()),
}, (table) => [
  index("idx_extracted_creds_engagement").on(table.engagement_id),
  index("idx_extracted_creds_type").on(table.credential_type),
])

export const audit_log = sqliteTable("audit_log", {
  id: text().primaryKey(),
  engagement_id: text().notNull().references(() => engagements.id, { onDelete: "cascade" }),
  event_type: text().notNull(),
  message: text().notNull(),
  metadata: text({ mode: "json" }).$type<Record<string, unknown>>().default({}),
  created_at: integer().notNull().$default(() => Date.now()),
}, (table) => [
  index("idx_audit_log_engagement").on(table.engagement_id),
])

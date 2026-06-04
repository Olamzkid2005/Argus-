import { sqliteTable, text, integer, index } from "drizzle-orm/sqlite-core"

export const engagements = sqliteTable("engagements", {
  id: text().primaryKey(),
  target: text().notNull(),
  workflow: text().notNull(),
  workflow_version: integer().notNull().default(1),
  status: text().notNull().default("CREATED"),
  schema_version: integer().notNull().default(1),
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

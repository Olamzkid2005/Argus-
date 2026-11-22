import { mkdirSync, readFileSync, writeFileSync } from "fs"
import { join, dirname } from "path"
import { fileURLToPath } from "url"
import type { FindingAnalysis, NormalizedFinding } from "../shared/types"
import { Severity, Confidence } from "../shared/types"
import { redactSecrets } from "../shared/redaction"
import type {
  ProofEvidencePackage,
  ProofLedger,
  ProofLedgerEntry,
  Report,
  ReportContentOptions,
  ReportExecutionSnapshot,
  ReportFormat,
  ReportSummary,
} from "./types"
import { EngagementStore } from "../engagement/store"
import type { IEngagementStore } from "../engagement/types"
import { reconcileCheckpointBudget } from "../engagement/checkpoint"
import { StoragePaths } from "../storage/paths"

/** Resolve the current file's directory, compatible with both Bun and Node ESM. */
const _dirname = dirname(fileURLToPath(import.meta.url))

function escapeMarkdown(text: string): string {
  // Only escape characters that are meaningful markdown syntax.
  // Avoids mangling CVE IDs (CVE-2024-1234), IPs (192.168.1.1),
  // version numbers, file paths, and other technical content.
  return text.replace(/[_*`\[\]#~]/g, "\\$&")
}

function enumValue<T extends Record<string, number | string>>(e: T, v: unknown, fallback: T[keyof T]): T[keyof T] {
  const num = Number(v)
  if (!Number.isNaN(num) && (Object.values(e) as unknown[]).includes(num)) {
    return num as T[keyof T]
  }
  if (typeof v === "string") {
    const val = (e as Record<string, unknown>)[v]
    if (typeof val === "number") return val as T[keyof T]
  }
  return fallback
}

const KNOWN_PROOF_STATUSES = new Set([
  "reproduced",
  "suspected",
  "inconclusive",
  "not_reproduced",
  "unsupported",
  "unverified",
])

/** Normalize legacy or shorthand proof outcomes to the ledger vocabulary. */
export function normalizeProofStatus(status: string | undefined | null): string {
  const normalized = (status ?? "unverified").toLowerCase()
  if (normalized === "pass" || normalized === "passed") return "reproduced"
  if (normalized === "fail" || normalized === "failed") return "not_reproduced"
  if (KNOWN_PROOF_STATUSES.has(normalized)) return normalized
  return normalized
}

export interface PhaseCoverageInput {
  id?: string
  name?: string
  status: string
  error?: string
}

export interface EngagementEvidenceInput {
  findingId: string
  packages: Array<{
    packageId?: string
    id?: string
    packageHash: string
    createdAt: number
    artifacts: ProofEvidencePackage["artifacts"]
  }>
}

/**
 * Convert persisted engagement evidence into the report's finding-keyed map.
 *
 * Keeping the conversion in one place means every report format links the same
 * package hashes and artifact references for a finding.
 */
export function evidenceMapFromEngagementEvidence(
  rows: EngagementEvidenceInput[],
): Record<string, ProofEvidencePackage[]> {
  const byFinding: Record<string, ProofEvidencePackage[]> = {}
  for (const row of rows) {
    byFinding[row.findingId] = (row.packages ?? []).map((pkg) => ({
      packageId: pkg.packageId ?? pkg.id ?? "",
      packageHash: pkg.packageHash,
      createdAt: pkg.createdAt,
      artifacts: (pkg.artifacts ?? []).map((artifact) => ({
        id: artifact.id,
        path: artifact.path,
        type: artifact.type,
        sizeBytes: artifact.sizeBytes,
      })),
    }))
  }
  return byFinding
}

/**
 * Build report content from the same persisted engagement state.
 *
 * Coverage, evidence links, and the latest execution snapshot travel together
 * so CLI, TUI, and direct generator calls cannot silently diverge.
 */
export function persistedReportOptions(
  store: IEngagementStore,
  engagementId: string,
): ReportContentOptions {
  const options: ReportContentOptions = {
    coverageGaps: coverageGapsFromPhases(store.getPhases(engagementId)),
    evidenceByFinding: evidenceMapFromEngagementEvidence(store.getEvidenceByEngagement(engagementId)),
  }
  const checkpoint = store.getLatestCheckpoint(engagementId)
  if (checkpoint) {
    const reconciled = reconcileCheckpointBudget(checkpoint.budgetUsage, checkpoint.workerBudget)
    options.execution = {
      scope: [...checkpoint.scope],
      model: checkpoint.model,
      limits: checkpoint.limits ? { ...checkpoint.limits } : undefined,
      actions: checkpoint.actions.map((action) => ({
        ...action,
        provenanceActions: action.provenance?.actions?.map((provenanceAction) => ({ ...provenanceAction })),
        provenance: undefined,
      })),
      observations: [...checkpoint.observations],
      secretRefs: [...checkpoint.secretRefs],
      authIdentities: [...(checkpoint.authIdentities ?? [])],
      budgetUsage: {
        ...checkpoint.budgetUsage,
        toolCalls: reconciled.toolCalls,
        source: reconciled.source,
        workerToolCalls: checkpoint.workerBudget?.toolCalls,
        discrepancies: reconciled.discrepancies,
      },
      startedAt: checkpoint.startedAt,
      checkpointAt: checkpoint.checkpointAt,
      completedAt: checkpoint.completedAt,
    }
  }
  return options
}

/**
 * Derive explicit incomplete-coverage items from stored phase state.
 *
 * A clean report with zero findings is only trustworthy when every required
 * phase actually completed. Non-terminal, skipped, partial, or failed phases
 * are therefore reported as gaps instead of being silently omitted.
 */
export function coverageGapsFromPhases(phases: PhaseCoverageInput[]): string[] {
  return phases.flatMap((phase) => {
    const label = phase.name || phase.id || "unnamed phase"
    const error = phase.error?.trim()
    if (phase.status === "COMPLETED") {
      if (error && /coverage gap/i.test(error)) return [`${label}: ${error}`]
      return []
    }
    if (phase.status === "SKIPPED") {
      return [`${label} was skipped${error ? `: ${error}` : ""}`]
    }
    if (phase.status === "PARTIAL" || phase.status === "FAILED") {
      return [`${label} is ${phase.status.toLowerCase()}${error ? `: ${error}` : ""}`]
    }
    return [`${label} did not complete (status: ${phase.status})${error ? `: ${error}` : ""}`]
  })
}

export class ReportGenerator {
  private analyses: FindingAnalysis[] = []
  private analysesMap: Map<string, FindingAnalysis> = new Map()

  setAnalyses(analyses: FindingAnalysis[]): void {
    // Analyses may quote scanned evidence, so sanitize them at the reporting
    // boundary as well. Callers retain their own unmodified objects.
    this.analyses = analyses.map((analysis) => this.redactAnalysis(analysis))
    this.analysesMap = new Map(this.analyses.map((a) => [a.findingId, a]))
  }

  private getAnalysisForFinding(findingId: string): FindingAnalysis | undefined {
    return this.analysesMap.get(findingId)
  }

  private redactText(value: string | undefined): string | undefined {
    return value === undefined ? undefined : redactSecrets(value)
  }

  /**
   * Remove scanned secrets from exported report content. Stored findings keep
   * their raw values for local investigation; every emitted format uses the
   * redacted copy so credential canaries cannot leak through a shared report.
   */
  private redactFinding(finding: NormalizedFinding): NormalizedFinding {
    const verificationResult = finding.verificationResult ? {
      ...finding.verificationResult,
      summary: redactSecrets(finding.verificationResult.summary),
      controls: finding.verificationResult.controls.map((control) => {
        const redactedControl = { ...control }
        if (control.description !== undefined) redactedControl.description = redactSecrets(control.description)
        if (control.reference !== undefined) redactedControl.reference = redactSecrets(control.reference)
        if (control.outcome !== undefined) redactedControl.outcome = redactSecrets(control.outcome)
        return redactedControl
      }),
      error: finding.verificationResult.error ? {
        ...finding.verificationResult.error,
        message: redactSecrets(finding.verificationResult.error.message),
      } : undefined,
      cleanup: finding.verificationResult.cleanup ? {
        ...finding.verificationResult.cleanup,
        detail: redactSecrets(finding.verificationResult.cleanup.detail),
      } : undefined,
    } : undefined
    return {
      ...finding,
      title: redactSecrets(finding.title),
      description: redactSecrets(finding.description),
      subtype: this.redactText(finding.subtype),
      cve: this.redactText(finding.cve),
      cwe: this.redactText(finding.cwe),
      owasp: this.redactText(finding.owasp),
      remediation: this.redactText(finding.remediation),
      url: this.redactText(finding.url),
      source: this.redactText(finding.source),
      verificationResult,
    }
  }

  private sanitizeExecution(execution: ReportExecutionSnapshot): ReportExecutionSnapshot {
    return {
      ...execution,
      scope: execution.scope.map((entry) => redactSecrets(entry)),
      limits: execution.limits ? { ...execution.limits } : undefined,
      actions: execution.actions.map((action) => ({
        ...action,
        error: action.error === undefined ? undefined : redactSecrets(action.error),
        reason: action.reason === undefined ? undefined : redactSecrets(action.reason),
        provenanceActions: action.provenanceActions?.map((provenanceAction) => ({
          ...provenanceAction,
          reasoning: provenanceAction.reasoning === undefined ? undefined : redactSecrets(provenanceAction.reasoning),
          detail: provenanceAction.detail === undefined ? undefined : redactSecrets(provenanceAction.detail),
        })),
      })),
      observations: execution.observations.map((observation) => redactSecrets(observation)),
      secretRefs: [...execution.secretRefs],
      authIdentities: [...execution.authIdentities],
      budgetUsage: { ...execution.budgetUsage, discrepancies: [...execution.budgetUsage.discrepancies] },
    }
  }

  private redactAnalysis(analysis: FindingAnalysis): FindingAnalysis {
    return {
      ...analysis,
      explanation: redactSecrets(analysis.explanation),
      impact: analysis.impact.map((item) => redactSecrets(item)),
      remediation: analysis.remediation.map((item) => redactSecrets(item)),
      references: analysis.references?.map((reference) => redactSecrets(reference)),
    }
  }

  private evidenceFor(options: ReportContentOptions, findingId: string): ProofEvidencePackage[] {
    return options.evidenceByFinding?.[findingId] ?? []
  }

  private evidenceDisplay(packages: ProofEvidencePackage[]): string {
    if (packages.length === 0) return "no evidence packages recorded"
    const artifactCount = packages.reduce((count, pkg) => count + pkg.artifacts.length, 0)
    const hashes = packages.map((pkg) => pkg.packageHash).join(", ")
    return `${packages.length} package${packages.length === 1 ? "" : "s"}, ${artifactCount} artifact${artifactCount === 1 ? "" : "s"} (${hashes})`
  }

  private executionBudgetDisplay(execution: ReportExecutionSnapshot): string {
    const budget = execution.budgetUsage
    const cost = budget.costKnown ? `$${budget.costUsd}` : "unknown (worker ledger authoritative)"
    return `${budget.source}: tool calls ${budget.toolCalls}, requests ${budget.requestCount}, LLM calls ${budget.llmCalls} ` +
      `(${budget.llmFailures} failures), tokens ${budget.inputTokens + budget.outputTokens}, cost ${cost}`
  }

  private executionContextMarkdown(execution: ReportExecutionSnapshot): string[] {
    const lines = ["## Execution context"]
    lines.push(`- Scope: ${execution.scope.length > 0 ? execution.scope.map((entry) => escapeMarkdown(entry)).join(", ") : "none recorded"}`)
    lines.push(`- Model: ${execution.model ? escapeMarkdown(execution.model) : "not recorded"}`)
    lines.push(`- Credentials: ${execution.secretRefs.length > 0 ? execution.secretRefs.map((ref) => escapeMarkdown(ref)).join(", ") : "none configured"}`)
    lines.push(`- Auth identities: ${execution.authIdentities.length > 0 ? execution.authIdentities.map((entry) => escapeMarkdown(entry)).join(", ") : "none recorded"}`)
    lines.push(`- Budget: ${escapeMarkdown(this.executionBudgetDisplay(execution))}`)
    if (execution.budgetUsage.workerToolCalls !== undefined) {
      lines.push(`- Worker tool calls: ${execution.budgetUsage.workerToolCalls}`)
    }
    if (execution.budgetUsage.discrepancies.length > 0) {
      lines.push(`- Budget reconciliation:`)
      for (const discrepancy of execution.budgetUsage.discrepancies) {
        lines.push(`  - ${escapeMarkdown(discrepancy)}`)
      }
    }
    if (execution.limits) {
      const limits = Object.entries(execution.limits).map(([key, value]) => `${key}=${value ?? "unknown"}`).join(", ")
      lines.push(`- Limits: ${escapeMarkdown(limits || "none")}`)
    }
    const succeeded = execution.actions.filter((action) => action.status === "succeeded").length
    const failed = execution.actions.filter((action) => action.status === "failed").length
    const inFlight = execution.actions.filter((action) => action.status === "in_flight").length
    lines.push(`- Actions: ${succeeded} succeeded, ${failed} failed, ${inFlight} in flight (${execution.actions.length} recorded)`)
    for (const action of execution.actions.slice(-5)) {
      const provenance = [
        action.source ? `source ${action.source}` : undefined,
        action.by ? `by ${action.by}` : undefined,
      ].filter((value): value is string => value !== undefined).join(", ")
      lines.push(`  - ${escapeMarkdown(action.tool)}: ${escapeMarkdown(action.status)}${provenance ? ` (${escapeMarkdown(provenance)})` : ""}${action.error ? ` — ${escapeMarkdown(action.error)}` : ""}`)
      if (action.reason) lines.push(`    - reason: ${escapeMarkdown(action.reason)}`)
      for (const provenanceAction of action.provenanceActions?.slice(-3) ?? []) {
        lines.push(`    - ${escapeMarkdown(provenanceAction.tool)}: ${escapeMarkdown(provenanceAction.outcome)} (${escapeMarkdown(provenanceAction.source)}${provenanceAction.identity ? `, ${escapeMarkdown(provenanceAction.identity)}` : ""})`)
        if (provenanceAction.reasoning) lines.push(`      - reasoning: ${escapeMarkdown(provenanceAction.reasoning)}`)
        if (provenanceAction.detail) lines.push(`      - detail: ${escapeMarkdown(provenanceAction.detail)}`)
      }
    }
    lines.push(`- Checkpoint: ${escapeMarkdown(execution.checkpointAt)}`)
    return lines
  }

  private executionContextHtml(execution: ReportExecutionSnapshot): string {
    const scope = execution.scope.length > 0
      ? `<ul>${execution.scope.map((entry) => `<li>${this.escapeHtml(entry)}</li>`).join("")}</ul>`
      : "<p>None recorded</p>"
    const credentials = execution.secretRefs.length > 0
      ? `<ul>${execution.secretRefs.map((ref) => `<li>${this.escapeHtml(ref)}</li>`).join("")}</ul>`
      : "<p>None configured</p>"
    const identities = execution.authIdentities.length > 0
      ? `<ul>${execution.authIdentities.map((identity) => `<li>${this.escapeHtml(identity)}</li>`).join("")}</ul>`
      : "<p>None recorded</p>"
    const discrepancies = execution.budgetUsage.discrepancies.map((discrepancy) => `<li>${this.escapeHtml(discrepancy)}</li>`).join("")
    const actions = execution.actions.slice(-5).map((action) => {
      const provenanceActions = (action.provenanceActions?.slice(-3) ?? []).map((provenanceAction) => (
        `<li>${this.escapeHtml(provenanceAction.tool)}: ${this.escapeHtml(provenanceAction.outcome)} (${this.escapeHtml(provenanceAction.source)}${provenanceAction.identity ? `, ${this.escapeHtml(provenanceAction.identity)}` : ""})` +
        `${provenanceAction.reasoning ? ` — ${this.escapeHtml(provenanceAction.reasoning)}` : ""}${provenanceAction.detail ? ` — ${this.escapeHtml(provenanceAction.detail)}` : ""}</li>`
      )).join("")
      return `<li>${this.escapeHtml(action.tool)}: ${this.escapeHtml(action.status)}` +
        `${action.source ? ` (${this.escapeHtml(action.source)}${action.by ? `, ${this.escapeHtml(action.by)}` : ""})` : ""}` +
        `${action.error ? ` — ${this.escapeHtml(action.error)}` : ""}${action.reason ? ` — ${this.escapeHtml(action.reason)}` : ""}` +
        `${provenanceActions ? `<ul>${provenanceActions}</ul>` : ""}</li>`
    }).join("")
    return `
      <h2>Execution context</h2>
      <p>Scope: ${execution.scope.length > 0 ? this.escapeHtml(execution.scope.join(", ")) : "none recorded"}</p>
      <p>Model: ${execution.model ? this.escapeHtml(execution.model) : "not recorded"}</p>
      <p>Budget: ${this.escapeHtml(this.executionBudgetDisplay(execution))}</p>
      ${execution.budgetUsage.workerToolCalls !== undefined ? `<p>Worker tool calls: ${execution.budgetUsage.workerToolCalls}</p>` : ""}
      ${discrepancies ? `<h3>Budget reconciliation</h3><ul>${discrepancies}</ul>` : ""}
      ${credentials}
      <h3>Auth identities</h3>
      ${identities}
      <h3>Recent actions</h3>
      ${actions ? `<ul>${actions}</ul>` : "<p>None recorded</p>"}
      ${scope}`
  }

  private controlsDisplay(result: NonNullable<NormalizedFinding["verificationResult"]>): string {
    if (result.controls.length === 0) return "no controls"
    const shown = result.controls.slice(0, 3).map((control) => {
      const comparison = control.outcome ?? control.description ?? control.reference
      return comparison ? `${control.kind}: ${comparison}` : control.kind
    })
    if (result.controls.length > 3) {
      shown.push(`and ${result.controls.length - 3} more control${result.controls.length - 3 === 1 ? "" : "s"}`)
    }
    return shown.join("; ")
  }

  private proofDisplay(finding: NormalizedFinding): string {
    const result = finding.verificationResult
    if (!result) return "unverified"
    const label = normalizeProofStatus(result.proofStatus).replace(/_/g, " ")
    const details: string[] = []
    if (result.verifier) details.push(`verifier ${result.verifier}`)
    if (typeof result.confidence === "number") details.push(`confidence ${Math.round(result.confidence * 100)}%`)
    if (result.verifiedAt) details.push(`verified at ${result.verifiedAt}`)
    details.push(`controls: ${this.controlsDisplay(result)}`)
    return `${label} (${details.join(", ")})`
  }

  /**
   * Build the proof ledger for a finding set: which findings were reproduced,
   * which need attention, and which capabilities/phases left coverage gaps.
   */
  proofLedger(
    findings: NormalizedFinding[],
    coverageGaps: string[] = [],
    evidenceByFinding: Record<string, ProofEvidencePackage[]> = {},
  ): ProofLedger {
    const entries: ProofLedgerEntry[] = findings.map((finding) => {
      const packages = evidenceByFinding[finding.id] ?? []
      const evidenceArtifacts = packages.reduce((count, pkg) => count + pkg.artifacts.length, 0)
      return {
        findingId: finding.id,
        title: finding.title,
        proofStatus: finding.verificationResult
          ? normalizeProofStatus(finding.verificationResult.proofStatus)
          : "unverified",
        verifier: finding.verificationResult?.verifier,
        confidence: finding.verificationResult?.confidence,
        verifiedAt: finding.verificationResult?.verifiedAt,
        controls: finding.verificationResult?.controls.length ?? 0,
        controlComparisons: finding.verificationResult?.controls.map((control) => ({
          kind: control.kind,
          description: control.description,
          outcome: control.outcome,
          reference: control.reference,
        })) ?? [],
        evidencePackages: packages.length,
        evidenceArtifacts,
        evidencePackageHashes: packages.map((pkg) => pkg.packageHash),
      }
    })
    const byProofStatus: Record<string, number> = {}
    const reproducedFindingIds: string[] = []
    const attentionFindingIds: string[] = []
    for (const entry of entries) {
      byProofStatus[entry.proofStatus] = (byProofStatus[entry.proofStatus] ?? 0) + 1
      if (entry.proofStatus === "reproduced") reproducedFindingIds.push(entry.findingId)
      else attentionFindingIds.push(entry.findingId)
    }
    const verifiedOutcomes = entries.filter((entry) => entry.proofStatus !== "unverified").length
    return {
      totalFindings: findings.length,
      verifiedOutcomes,
      reproduced: byProofStatus["reproduced"] ?? 0,
      suspected: byProofStatus["suspected"] ?? 0,
      inconclusive: byProofStatus["inconclusive"] ?? 0,
      notReproduced: byProofStatus["not_reproduced"] ?? 0,
      unsupported: byProofStatus["unsupported"] ?? 0,
      unverified: byProofStatus["unverified"] ?? 0,
      byProofStatus,
      reproducedFindingIds,
      attentionFindingIds,
      coverageGaps: coverageGaps.map((gap) => redactSecrets(gap)),
      evidencePackages: entries.reduce((count, entry) => count + entry.evidencePackages, 0),
      evidenceArtifacts: entries.reduce((count, entry) => count + entry.evidenceArtifacts, 0),
      entries,
    }
  }

  /**
   * Generate a report directly from the SQLite store — re-queries findings
   * and evidence on every call so the report always reflects the latest state.
   */
  generateFromEngagement(
    engagementId: string,
    format: ReportFormat = "markdown",
    storeArg?: IEngagementStore,
    options: ReportContentOptions = {},
  ): string {
    const store = storeArg ?? new EngagementStore()
    const engagement = store.getEngagement(engagementId)
    if (!engagement) return `Engagement not found: ${engagementId}`

    const findings = store.getFindings(engagementId)
    const persisted = persistedReportOptions(store, engagementId)
    const contentOptions: ReportContentOptions = {
      coverageGaps: options.coverageGaps ?? persisted.coverageGaps,
      evidenceByFinding: options.evidenceByFinding ?? persisted.evidenceByFinding,
      execution: options.execution ?? persisted.execution,
    }

    switch (format) {
      case "json": return this.generateJSON(findings, engagementId, engagement.target, engagement.workflow, contentOptions)
      case "sarif": return this.generateSARIF(findings, engagementId, engagement.target, engagement.workflow, contentOptions)
      case "html": return this.generateHTML(findings, engagementId, engagement.target, engagement.workflow, contentOptions)
      default: return this.generateMarkdown(findings, engagementId, engagement.target, engagement.workflow, contentOptions)
    }
  }

  /**
   * Write a rendered report next to the engagement's own data.
   *
   * An assessment that only prints the report to stdout leaves nothing behind —
   * an unattended or TUI run ends with no artifact to inspect, and a report with
   * zero findings is the case where that matters most. The file sits beside the
   * engagement database (`<base>/engagements/<id>/report.<ext>`) so a run's
   * output travels with its data.
   *
   * Returns the path written.
   */
  writeArtifact(
    engagementId: string,
    content: string,
    format: ReportFormat = "markdown",
    dirOverride?: string,
  ): string {
    const dir = dirOverride ?? StoragePaths.engagementDir(engagementId)
    mkdirSync(dir, { recursive: true })
    const extension = format === "markdown" ? "md" : format
    const reportPath = join(dir, `report.${extension}`)
    writeFileSync(reportPath, content, "utf-8")
    return reportPath
  }

  generate(
    findings: NormalizedFinding[],
    engagementId: string,
    target: string,
    workflow: string,
    options: ReportContentOptions = {},
  ): Report {
    const safeFindings = findings.map((finding) => this.redactFinding(finding))
    const safeAnalyses = this.analyses.map((analysis) => this.redactAnalysis(analysis))
    return {
      engagementId,
      target,
      workflow,
      createdAt: new Date().toISOString(),
      findings: safeFindings,
      analyses: safeAnalyses.length > 0 ? safeAnalyses : undefined,
      execution: options.execution ? this.sanitizeExecution(options.execution) : undefined,
      summary: this.generateSummary(safeFindings, options),
    }
  }

  private generateSummary(findings: NormalizedFinding[], options: ReportContentOptions = {}): ReportSummary {
    const bySeverity: Record<string, number> = {}
    const byConfidence: Record<string, number> = {}
    const byStatus: Record<string, number> = {}

    for (const f of findings) {
      const sevKey = Severity[enumValue(Severity, f.severity, Severity.INFO)]
      const confKey = Confidence[enumValue(Confidence, f.confidence, Confidence.INFORMATIONAL)]
      if (sevKey) bySeverity[sevKey] = (bySeverity[sevKey] ?? 0) + 1
      if (confKey) byConfidence[confKey] = (byConfidence[confKey] ?? 0) + 1
      byStatus[f.status] = (byStatus[f.status] ?? 0) + 1
    }

    return {
      totalFindings: findings.length,
      analyzedCount: this.analyses.length > 0 ? this.analyses.length : undefined,
      bySeverity,
      byConfidence,
      byStatus,
      proof: this.proofLedger(findings, options.coverageGaps ?? [], options.evidenceByFinding ?? {}),
    }
  }

  generateMarkdown(
    findings: NormalizedFinding[],
    engagementId: string,
    target: string,
    workflow: string,
    options: ReportContentOptions = {},
  ): string {
    const report = this.generate(findings, engagementId, target, workflow, options)
    const lines: string[] = []

    lines.push(`# Security Assessment Report: ${target}`)
    lines.push(`**Engagement:** ${engagementId}`)
    lines.push(`**Workflow:** ${workflow}`)
    lines.push(`**Date:** ${report.createdAt}`)
    lines.push("")
    lines.push("## Summary")
    lines.push(`- Total Findings: ${report.summary.totalFindings}`)
    lines.push(`- Critical: ${report.summary.bySeverity["CRITICAL"] ?? 0}`)
    lines.push(`- High: ${report.summary.bySeverity["HIGH"] ?? 0}`)
    lines.push(`- Medium: ${report.summary.bySeverity["MEDIUM"] ?? 0}`)
    lines.push(`- Low: ${report.summary.bySeverity["LOW"] ?? 0}`)
    if (report.summary.analyzedCount && report.summary.analyzedCount > 0) {
      lines.push(`- AI Analyses: ${report.summary.analyzedCount} findings analyzed`)
    }
    lines.push("")
    if (report.execution) {
      lines.push(...this.executionContextMarkdown(report.execution))
      lines.push("")
    }
    lines.push("## Proof ledger")
    const proof = report.summary.proof
    lines.push(`- Verified outcomes: ${proof.verifiedOutcomes} of ${proof.totalFindings}`)
    lines.push(`- Evidence linked: ${proof.evidencePackages} package${proof.evidencePackages === 1 ? "" : "s"}, ${proof.evidenceArtifacts} artifact${proof.evidenceArtifacts === 1 ? "" : "s"}`)
    lines.push(
      `- Proof outcomes: reproduced ${proof.reproduced}, suspected ${proof.suspected}, ` +
      `inconclusive ${proof.inconclusive}, not reproduced ${proof.notReproduced}, ` +
      `unsupported ${proof.unsupported}, unverified ${proof.unverified}`
    )
    const attention = proof.entries.filter((entry) => entry.proofStatus !== "reproduced")
    if (attention.length === 0) {
      lines.push("- Findings needing attention: none")
    } else {
      lines.push("- Findings needing attention:")
      for (const entry of attention) {
        lines.push(`  - ${escapeMarkdown(entry.findingId)} (${escapeMarkdown(entry.proofStatus.replace(/_/g, " "))})`)
      }
    }
    if (proof.coverageGaps.length === 0) {
      lines.push("- Coverage gaps: none recorded")
    } else {
      lines.push("- Coverage gaps:")
      for (const gap of proof.coverageGaps) {
        lines.push(`  - ${escapeMarkdown(gap)}`)
      }
    }
    lines.push("")
    lines.push("## Findings")
    lines.push("")

    const sorted = [...report.findings].sort((a, b) => b.severity - a.severity)
    for (const f of sorted) {
      const severityStr = Severity[enumValue(Severity, f.severity, Severity.INFO)] ?? "UNKNOWN"
      const confidenceStr = Confidence[enumValue(Confidence, f.confidence, Confidence.INFORMATIONAL)] ?? "UNKNOWN"
      lines.push(`### ${escapeMarkdown(f.title)}`)
      lines.push(`- **Severity:** ${escapeMarkdown(severityStr)}`)
      lines.push(`- **Confidence:** ${escapeMarkdown(confidenceStr)}`)
      lines.push(`- **Status:** ${escapeMarkdown(f.status)}`)
      lines.push(`- **Proof:** ${escapeMarkdown(this.proofDisplay(f))}`)
      const evidencePackages = this.evidenceFor(options, f.id)
      lines.push(`- **Evidence:** ${escapeMarkdown(this.evidenceDisplay(evidencePackages))}`)
      const observed = f.responseEvidence
      if (observed) {
        const status = observed.statusCode === undefined ? "no status" : `HTTP ${observed.statusCode}`
        const bytes = observed.bodyBytes === undefined ? "" : `, ${observed.bodyBytes} bytes`
        const digest = observed.bodySha256 ? `, body sha256 ${observed.bodySha256}` : ""
        const where = observed.url ? ` from ${observed.url}` : ""
        lines.push(`- **Observed response:** ${escapeMarkdown(`${status}${where}${bytes}${digest}`)}`)
        if (observed.preview) {
          lines.push(`  - Body preview: ${escapeMarkdown(observed.preview.slice(0, 200))}`)
        }
      }
      for (const pkg of evidencePackages) {
        lines.push(`  - Package ${escapeMarkdown(pkg.packageHash)}: ${pkg.artifacts.length} artifact${pkg.artifacts.length === 1 ? "" : "s"}`)
        for (const artifact of pkg.artifacts.slice(0, 5)) {
          lines.push(`    - ${escapeMarkdown(artifact.path)} (${escapeMarkdown(artifact.type)}, ${artifact.sizeBytes} bytes)`)
        }
        if (pkg.artifacts.length > 5) {
          lines.push(`    - … and ${pkg.artifacts.length - 5} more artifact${pkg.artifacts.length - 5 === 1 ? "" : "s"}`)
        }
      }
      lines.push(`- **Tool:** ${escapeMarkdown(f.tool)}`)
      lines.push(`- **Phase:** ${escapeMarkdown(f.phase)}`)
      if (f.description) lines.push(`- **Description:** ${escapeMarkdown(f.description)}`)
      if (f.cve) lines.push(`- **CVE:** ${escapeMarkdown(f.cve)}`)
      if (f.cwe) lines.push(`- **CWE:** ${escapeMarkdown(f.cwe)}`)
      if (f.owasp) lines.push(`- **OWASP:** ${escapeMarkdown(f.owasp)}`)
      if (f.remediation) lines.push(`- **Remediation:** ${escapeMarkdown(f.remediation)}`)
      lines.push("")

      // Include AI analysis if available
      const analysis = this.getAnalysisForFinding(f.id)
      if (analysis) {
        lines.push("### 🔍 AI Analysis")
        lines.push("")
        lines.push(`**Explanation:** ${escapeMarkdown(analysis.explanation)}`)
        lines.push("")
        lines.push("**Impact:**")
        for (const item of analysis.impact) {
          lines.push(`- ${escapeMarkdown(item)}`)
        }
        lines.push("")
        lines.push("**Remediation:**")
        for (const item of analysis.remediation) {
          lines.push(`- ${escapeMarkdown(item)}`)
        }
        if (analysis.references && analysis.references.length > 0) {
          lines.push("")
          lines.push("**References:**")
          for (const ref of analysis.references) {
            lines.push(`- ${ref}`)
          }
        }
        lines.push("")
        lines.push(`*Generated by: ${analysis.model}*`)
        lines.push("")
      }
    }

    return lines.join("\n")
  }

  generateJSON(
    findings: NormalizedFinding[],
    engagementId: string,
    target: string,
    workflow: string,
    options: ReportContentOptions = {},
  ): string {
    const report = this.generate(findings, engagementId, target, workflow, options)
    return JSON.stringify(report, null, 2)
  }

  generateHTML(
    findings: NormalizedFinding[],
    engagementId: string,
    target: string,
    workflow: string,
    options: ReportContentOptions = {},
  ): string {
    const report = this.generate(findings, engagementId, target, workflow, options)
    const s = report.summary

    // Count by severity
    const sevCounts = {
      CRITICAL: s.bySeverity["CRITICAL"] ?? 0,
      HIGH: s.bySeverity["HIGH"] ?? 0,
      MEDIUM: s.bySeverity["MEDIUM"] ?? 0,
      LOW: s.bySeverity["LOW"] ?? 0,
      INFO: s.bySeverity["INFO"] ?? 0,
    }

    const proof = report.summary.proof
    const attentionItems = proof.entries
      .filter((entry) => entry.proofStatus !== "reproduced")
      .map((entry) => `<li>${this.escapeHtml(entry.findingId)} (${this.escapeHtml(entry.proofStatus.replace(/_/g, " "))})</li>`)
      .join("")
    const gapItems = proof.coverageGaps.map((gap) => `<li>${this.escapeHtml(gap)}</li>`).join("")
    const proofHtml = `
      <h2>Proof ledger</h2>
      <div class="summary">
        <div class="stat-card"><div class="count">${proof.verifiedOutcomes}/${proof.totalFindings}</div><div class="label">Verified outcomes</div></div>
        <div class="stat-card"><div class="count">${proof.reproduced}</div><div class="label">Reproduced</div></div>
        <div class="stat-card"><div class="count">${proof.inconclusive}</div><div class="label">Inconclusive</div></div>
        <div class="stat-card"><div class="count">${proof.unsupported}</div><div class="label">Unsupported</div></div>
        <div class="stat-card"><div class="count">${proof.unverified}</div><div class="label">Unverified</div></div>
        <div class="stat-card"><div class="count">${proof.evidencePackages}</div><div class="label">Evidence packages</div></div>
        <div class="stat-card"><div class="count">${proof.evidenceArtifacts}</div><div class="label">Evidence artifacts</div></div>
      </div>
      ${report.execution ? this.executionContextHtml(report.execution) : ""}
      <h3>Findings needing attention</h3>
      ${attentionItems ? `<ul>${attentionItems}</ul>` : "<p>None</p>"}
      <h3>Coverage gaps</h3>
      ${gapItems ? `<ul>${gapItems}</ul>` : "<p>None recorded</p>"}`

    // Build findings HTML
    const severityLabels = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    const findingItems = report.findings
      .sort((a, b) => b.severity - a.severity)
      .map((f) => {
        const sevLabel = severityLabels[f.severity] ?? "INFO"
        const badges = [`<span class="badge badge-${sevLabel.toLowerCase()}">${sevLabel}</span>`]
        const refs: string[] = []
        if (f.cve) refs.push(`<a href="https://nvd.nist.gov/vuln/detail/${this.escapeHtml(f.cve)}">${this.escapeHtml(f.cve)}</a>`)
        if (f.cwe) refs.push(`<a href="https://cwe.mitre.org/data/definitions/${this.escapeHtml(f.cwe.replace("CWE-", ""))}.html">${this.escapeHtml(f.cwe)}</a>`)

        // Include AI analysis if available
        const analysis = this.getAnalysisForFinding(f.id)
        let analysisHtml = ""
        if (analysis) {
          const impactList = analysis.impact.map((i) => `<li>${this.escapeHtml(i)}</li>`).join("")
          const remediationList = analysis.remediation.map((r) => `<li>${this.escapeHtml(r)}</li>`).join("")
          const refsList = analysis.references?.map((r) => `<li>${this.escapeHtml(r)}</li>`).join("") ?? ""
          analysisHtml = `
          <details class="ai-analysis">
            <summary>🔍 AI Analysis <small>(by ${analysis.model})</small></summary>
            <div class="analysis-body">
              <p><strong>Explanation:</strong> ${this.escapeHtml(analysis.explanation)}</p>
              <div class="analysis-section">
                <strong>Impact:</strong>
                <ul>${impactList}</ul>
              </div>
              <div class="analysis-section">
                <strong>Remediation:</strong>
                <ul>${remediationList}</ul>
              </div>
              ${refsList ? `<div class="analysis-section"><strong>References:</strong><ul>${refsList}</ul></div>` : ""}
            </div>
          </details>`
        }

        const evidencePackages = options.evidenceByFinding?.[f.id] ?? []
        const evidenceItems = evidencePackages.map((pkg) => {
          const artifactItems = pkg.artifacts.slice(0, 5).map((artifact) => (
            `<li>${this.escapeHtml(artifact.path)} (${this.escapeHtml(artifact.type)}, ${artifact.sizeBytes} bytes)</li>`
          )).join("")
          const remainder = pkg.artifacts.length > 5
            ? `<li>… and ${pkg.artifacts.length - 5} more artifact${pkg.artifacts.length - 5 === 1 ? "" : "s"}</li>`
            : ""
          return `<li>Package ${this.escapeHtml(pkg.packageHash)}<ul>${artifactItems}${remainder}</ul></li>`
        }).join("")
        const evidenceHtml = `<div class="refs">Evidence: ${this.escapeHtml(this.evidenceDisplay(evidencePackages))}` +
          `${evidenceItems ? `<ul>${evidenceItems}</ul>` : ""}</div>`

        return `
        <div class="finding severity-${f.severity}">
          <div class="title">${this.escapeHtml(f.title)}</div>
          <div>${badges.join(" ")} <span class="badge" style="background:#0d6efd;color:white">${this.escapeHtml(f.tool)}</span></div>
          <div class="details">${this.escapeHtml(f.description || "")}</div>
          ${refs.length > 0 ? `<div class="refs">${refs.join(" · ")}</div>` : ""}
          ${evidenceHtml}
          ${analysisHtml}
          <div style="margin-top:0.5rem;font-size:0.8rem;color:#6c757d">Phase: ${this.escapeHtml(f.phase)} · ${this.escapeHtml(f.status)} · Proof: ${this.escapeHtml(this.proofDisplay(f))}</div>
        </div>`
      }).join("\n")

    // Load template and substitute
    const templatePath = join(_dirname, "templates", "report.html")
    let html: string
    try {
      html = readFileSync(templatePath, "utf-8")
    } catch {
      html = "<html><body><h1>Report: {{TARGET}}</h1><p>Template not found</p>{{FINDINGS}}</body></html>"
    }

    html = html.replace(/{{TARGET}}/g, this.escapeHtml(target))
    html = html.replace("{{ENGAGEMENT_ID}}", this.escapeHtml(engagementId))
    html = html.replace("{{WORKFLOW}}", this.escapeHtml(workflow))
    html = html.replace(/{{DATE}}/g, report.createdAt)
    html = html.replace("{{TOTAL_FINDINGS}}", String(s.totalFindings))
    html = html.replace("{{CRITICAL_COUNT}}", String(sevCounts.CRITICAL))
    html = html.replace("{{HIGH_COUNT}}", String(sevCounts.HIGH))
    html = html.replace("{{MEDIUM_COUNT}}", String(sevCounts.MEDIUM))
    html = html.replace("{{LOW_COUNT}}", String(sevCounts.LOW))
    html = html.replace("{{INFO_COUNT}}", String(sevCounts.INFO))
    html = html.replace("{{ANALYZED_COUNT}}", String(this.analyses.length))
    if (html.includes("{{PROOF_LEDGER}}")) {
      html = html.replace("{{PROOF_LEDGER}}", proofHtml)
    } else {
      html = html.replace("<h2>Findings</h2>", `${proofHtml}\n\n  <h2>Findings</h2>`)
    }
    html = html.replaceAll("{{FINDINGS}}", findingItems)

    return html
  }

  private escapeHtml(text: string): string {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;")
  }

  generateSARIF(
    findings: NormalizedFinding[],
    engagementId: string,
    target: string,
    workflow: string,
    options: ReportContentOptions = {},
  ): string {
    const report = this.generate(findings, engagementId, target, workflow, options)
    const proof = report.summary.proof
    // Build rules from findings keyed by a stable category ID (subtype, CWE, or tool name)
    // rather than per-finding unique ID — so SARIF consumers can group related results.
    function ruleKey(f: NormalizedFinding): string {
      return f.subtype ?? f.cwe ?? `argus-${f.tool}`
    }
    const rulesMap = new Map<string, { id: string; shortDescription: { text: string }; fullDescription: { text: string }; helpUri?: string }>()
    for (const f of report.findings) {
      const key = ruleKey(f)
      if (!rulesMap.has(key)) {
        const rule = {
          id: key,
          shortDescription: { text: f.subtype ?? f.tool },
          fullDescription: { text: f.description || f.title },
        } as { id: string; shortDescription: { text: string }; fullDescription: { text: string }; helpUri?: string }
        const helpUri = f.cwe ? `https://cwe.mitre.org/data/definitions/${f.cwe.replace("CWE-", "")}.html`
                     : f.cve ? `https://cve.mitre.org/cgi-bin/cvename.cgi?name=${f.cve}`
                     : undefined
        if (helpUri) rule.helpUri = helpUri
        rulesMap.set(key, rule)
      }
    }

    const sarifResults = report.findings.map((f) => {
      const evidencePackages = options.evidenceByFinding?.[f.id] ?? []
      return {
        ruleId: ruleKey(f),
        level: f.severity >= 3 ? "error" : f.severity >= 1 ? "warning" : "note",
        message: { text: f.title },
        locations: [{
          physicalLocation: {
            artifactLocation: { uri: target },
            region: { snippet: { text: f.description } },
          },
        }],
        properties: {
          findingId: f.id,
          proofStatus: f.verificationResult
            ? normalizeProofStatus(f.verificationResult.proofStatus)
            : "unverified",
          verifier: f.verificationResult?.verifier,
          confidence: f.verificationResult?.confidence,
          verifiedAt: f.verificationResult?.verifiedAt,
          controls: f.verificationResult?.controls.length ?? 0,
          controlComparisons: f.verificationResult?.controls.map((control) => ({
            kind: control.kind,
            description: control.description,
            outcome: control.outcome,
            reference: control.reference,
          })) ?? [],
          evidencePackages: evidencePackages.length,
          evidenceArtifacts: evidencePackages.reduce((count, pkg) => count + pkg.artifacts.length, 0),
          evidencePackageHashes: evidencePackages.map((pkg) => pkg.packageHash),
          evidence: evidencePackages.flatMap((pkg) => pkg.artifacts.map((artifact) => ({
            packageHash: pkg.packageHash,
            path: artifact.path,
            type: artifact.type,
            sizeBytes: artifact.sizeBytes,
          }))),
        },
      }
    })

    return JSON.stringify({
      $schema: "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos01/schemas/sarif-schema-2.1.0.json",
      version: "2.1.0",
      runs: [{
        automationDetails: { id: `${engagementId}/${workflow}` },
        tool: { driver: { name: "Argus", version: "5.0.0", rules: [...rulesMap.values()] } },
        properties: {
          engagementId,
          target,
          workflow,
          proofByStatus: proof.byProofStatus,
          reproducedFindingIds: proof.reproducedFindingIds,
          attentionFindingIds: proof.attentionFindingIds,
          coverageGaps: proof.coverageGaps,
          evidencePackages: proof.evidencePackages,
          evidenceArtifacts: proof.evidenceArtifacts,
          execution: report.execution,
        },
        results: sarifResults,
      }],
    }, null, 2)
  }
}

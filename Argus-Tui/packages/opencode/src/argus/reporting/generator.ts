import type { NormalizedFinding } from "../planner/types"
import { Severity, Confidence } from "../planner/types"
import type { Report, ReportFormat, ReportSummary } from "./types"

export class ReportGenerator {
  generate(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): Report {
    return {
      engagementId,
      target,
      workflow,
      createdAt: new Date().toISOString(),
      findings,
      summary: this.generateSummary(findings),
    }
  }

  private generateSummary(findings: NormalizedFinding[]): ReportSummary {
    const bySeverity: Record<string, number> = {}
    const byConfidence: Record<string, number> = {}
    const byStatus: Record<string, number> = {}

    for (const f of findings) {
      bySeverity[Severity[f.severity]] = (bySeverity[Severity[f.severity]] ?? 0) + 1
      byConfidence[Confidence[f.confidence]] = (byConfidence[Confidence[f.confidence]] ?? 0) + 1
      byStatus[f.status] = (byStatus[f.status] ?? 0) + 1
    }

    return {
      totalFindings: findings.length,
      bySeverity,
      byConfidence,
      byStatus,
    }
  }

  generateMarkdown(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    const report = this.generate(findings, engagementId, target, workflow)
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
    lines.push("")
    lines.push("## Findings")
    lines.push("")

    const sorted = [...findings].sort((a, b) => b.severity - a.severity)
    for (const f of sorted) {
      lines.push(`### ${f.title}`)
      lines.push(`- **Severity:** ${Severity[f.severity]}`)
      lines.push(`- **Confidence:** ${Confidence[f.confidence]}`)
      lines.push(`- **Status:** ${f.status}`)
      lines.push(`- **Tool:** ${f.tool}`)
      lines.push(`- **Phase:** ${f.phase}`)
      if (f.description) lines.push(`- **Description:** ${f.description}`)
      if (f.cve) lines.push(`- **CVE:** ${f.cve}`)
      if (f.cwe) lines.push(`- **CWE:** ${f.cwe}`)
      if (f.owasp) lines.push(`- **OWASP:** ${f.owasp}`)
      if (f.remediation) lines.push(`- **Remediation:** ${f.remediation}`)
      lines.push("")
    }

    return lines.join("\n")
  }

  generateJSON(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    const report = this.generate(findings, engagementId, target, workflow)
    return JSON.stringify(report, null, 2)
  }

  generateSARIF(findings: NormalizedFinding[], engagementId: string, target: string): string {
    const sarifResults = findings.map((f, i) => ({
      ruleId: f.cwe ?? `ARGUS-${i}`,
      level: f.severity >= 3 ? "error" : f.severity >= 1 ? "warning" : "note",
      message: { text: f.title },
      locations: [{
        physicalLocation: {
          artifactLocation: { uri: target },
          region: { snippet: { text: f.description } },
        },
      }],
    }))

    return JSON.stringify({
      $schema: "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
      version: "2.1.0",
      runs: [{
        tool: { driver: { name: "Argus", version: "5.0.0" } },
        results: sarifResults,
      }],
    }, null, 2)
  }
}

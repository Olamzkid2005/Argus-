import type { NormalizedFinding } from "../planner/types"
import { Severity, Confidence } from "../planner/types"
import type { Report, ReportFormat, ReportSummary } from "./types"

function escapeMarkdown(text: string): string {
  return text.replace(/[-_*`\[\]()#+!|{}.~]/g, "\\$&")
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

export class ReportGenerator {
  generate(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): Report {
    return {
      engagementId,
      target,
      workflow,
      createdAt: new Date().toISOString(),
      findings: [...findings],
      summary: this.generateSummary(findings),
    }
  }

  private generateSummary(findings: NormalizedFinding[]): ReportSummary {
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
      const severityStr = Severity[enumValue(Severity, f.severity, Severity.INFO)] ?? "UNKNOWN"
      const confidenceStr = Confidence[enumValue(Confidence, f.confidence, Confidence.INFORMATIONAL)] ?? "UNKNOWN"
      lines.push(`### ${escapeMarkdown(f.title)}`)
      lines.push(`- **Severity:** ${escapeMarkdown(severityStr)}`)
      lines.push(`- **Confidence:** ${escapeMarkdown(confidenceStr)}`)
      lines.push(`- **Status:** ${escapeMarkdown(f.status)}`)
      lines.push(`- **Tool:** ${escapeMarkdown(f.tool)}`)
      lines.push(`- **Phase:** ${escapeMarkdown(f.phase)}`)
      if (f.description) lines.push(`- **Description:** ${escapeMarkdown(f.description)}`)
      if (f.cve) lines.push(`- **CVE:** ${escapeMarkdown(f.cve)}`)
      if (f.cwe) lines.push(`- **CWE:** ${escapeMarkdown(f.cwe)}`)
      if (f.owasp) lines.push(`- **OWASP:** ${escapeMarkdown(f.owasp)}`)
      if (f.remediation) lines.push(`- **Remediation:** ${escapeMarkdown(f.remediation)}`)
      lines.push("")
    }

    return lines.join("\n")
  }

  generateJSON(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    const report = this.generate(findings, engagementId, target, workflow)
    return JSON.stringify(report, null, 2)
  }

  generateSARIF(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    // Build unique rules from findings
    const rulesMap = new Map<string, { id: string; shortDescription: { text: string }; fullDescription: { text: string }; helpUri?: string }>()
    for (const f of findings) {
      if (!rulesMap.has(f.id)) {
        const rule = {
          id: f.id,
          shortDescription: { text: f.title },
          fullDescription: { text: f.description || f.title },
        } as { id: string; shortDescription: { text: string }; fullDescription: { text: string }; helpUri?: string }
        const helpUri = f.cwe ? `https://cwe.mitre.org/data/definitions/${f.cwe.replace("CWE-", "")}.html`
                     : f.cve ? `https://cve.mitre.org/cgi-bin/cvename.cgi?name=${f.cve}`
                     : undefined
        if (helpUri) rule.helpUri = helpUri
        rulesMap.set(f.id, rule)
      }
    }

    const sarifResults = findings.map((f) => ({
      ruleId: f.id,
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
      $schema: "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos01/schemas/sarif-schema-2.1.0.json",
      version: "2.1.0",
      runs: [{
        automationDetails: { id: `${engagementId}/${workflow}` },
        tool: { driver: { name: "Argus", version: "5.0.0", rules: [...rulesMap.values()] } },
        results: sarifResults,
      }],
    }, null, 2)
  }
}

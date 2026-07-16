import { readFileSync } from "fs"
import { join, dirname } from "path"
import { fileURLToPath } from "url"
import type { FindingAnalysis, NormalizedFinding } from "../shared/types"
import { Severity, Confidence } from "../shared/types"
import type { Report, ReportFormat, ReportSummary } from "./types"
import { EngagementStore } from "../engagement/store"
import type { IEngagementStore } from "../engagement/types"

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

export class ReportGenerator {
  private analyses: FindingAnalysis[] = []
  private analysesMap: Map<string, FindingAnalysis> = new Map()

  setAnalyses(analyses: FindingAnalysis[]): void {
    this.analyses = analyses
    this.analysesMap = new Map(analyses.map((a) => [a.findingId, a]))
  }

  private getAnalysisForFinding(findingId: string): FindingAnalysis | undefined {
    return this.analysesMap.get(findingId)
  }

  /**
   * Generate a report directly from the SQLite store — re-queries findings
   * and evidence on every call so the report always reflects the latest state.
   */
  generateFromEngagement(engagementId: string, format: ReportFormat = "markdown", storeArg?: IEngagementStore): string {
    const store = storeArg ?? new EngagementStore()
    const engagement = store.getEngagement(engagementId)
    if (!engagement) return `Engagement not found: ${engagementId}`

    const findings = store.getFindings(engagementId)

    switch (format) {
      case "json": return this.generateJSON(findings, engagementId, engagement.target, engagement.workflow)
      case "sarif": return this.generateSARIF(findings, engagementId, engagement.target, engagement.workflow)
      case "html": return this.generateHTML(findings, engagementId, engagement.target, engagement.workflow)
      default: return this.generateMarkdown(findings, engagementId, engagement.target, engagement.workflow)
    }
  }

  generate(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): Report {
    return {
      engagementId,
      target,
      workflow,
      createdAt: new Date().toISOString(),
      findings: [...findings],
      analyses: this.analyses.length > 0 ? [...this.analyses] : undefined,
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
      analyzedCount: this.analyses.length > 0 ? this.analyses.length : undefined,
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
    if (report.summary.analyzedCount && report.summary.analyzedCount > 0) {
      lines.push(`- AI Analyses: ${report.summary.analyzedCount} findings analyzed`)
    }
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

  generateJSON(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    const report = this.generate(findings, engagementId, target, workflow)
    return JSON.stringify(report, null, 2)
  }

  generateHTML(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    const report = this.generate(findings, engagementId, target, workflow)
    const s = report.summary

    // Count by severity
    const sevCounts = {
      CRITICAL: s.bySeverity["CRITICAL"] ?? 0,
      HIGH: s.bySeverity["HIGH"] ?? 0,
      MEDIUM: s.bySeverity["MEDIUM"] ?? 0,
      LOW: s.bySeverity["LOW"] ?? 0,
      INFO: s.bySeverity["INFO"] ?? 0,
    }

    // Build findings HTML
    const severityLabels = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    const findingItems = findings
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

        return `
        <div class="finding severity-${f.severity}">
          <div class="title">${this.escapeHtml(f.title)}</div>
          <div>${badges.join(" ")} <span class="badge" style="background:#0d6efd;color:white">${this.escapeHtml(f.tool)}</span></div>
          <div class="details">${this.escapeHtml(f.description || "")}</div>
          ${refs.length > 0 ? `<div class="refs">${refs.join(" · ")}</div>` : ""}
          ${analysisHtml}
          <div style="margin-top:0.5rem;font-size:0.8rem;color:#6c757d">Phase: ${this.escapeHtml(f.phase)} · ${this.escapeHtml(f.status)}</div>
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
    html = html.replaceAll("{{FINDINGS}}", findingItems)

    return html
  }

  private escapeHtml(text: string): string {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;")
  }

  generateSARIF(findings: NormalizedFinding[], engagementId: string, target: string, workflow: string): string {
    // Build rules from findings keyed by a stable category ID (subtype, CWE, or tool name)
    // rather than per-finding unique ID — so SARIF consumers can group related results.
    function ruleKey(f: NormalizedFinding): string {
      return f.subtype ?? f.cwe ?? `argus-${f.tool}`
    }
    const rulesMap = new Map<string, { id: string; shortDescription: { text: string }; fullDescription: { text: string }; helpUri?: string }>()
    for (const f of findings) {
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

    const sarifResults = findings.map((f) => ({
      ruleId: ruleKey(f),
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

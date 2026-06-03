import { describe, expect, test } from "bun:test"
import { ReportGenerator } from "../../../../src/argus/reporting/generator"
import { Severity, Confidence } from "../../../../src/argus/planner/types"
import type { NormalizedFinding } from "../../../../src/argus/planner/types"

function makeFinding(overrides?: Partial<NormalizedFinding>): NormalizedFinding {
  return {
    id: "test-1",
    title: "Test Finding",
    severity: Severity.MEDIUM,
    confidence: Confidence.INFORMATIONAL,
    status: "PENDING",
    description: "A test finding",
    tool: "test-tool",
    phase: "test-phase",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("ReportGenerator", () => {
  test("generate() returns report with correct engagementId, target, workflow", () => {
    const generator = new ReportGenerator()
    const report = generator.generate(
      [makeFinding()],
      "eng-1",
      "https://example.com",
      "full-scan",
    )
    expect(report.engagementId).toBe("eng-1")
    expect(report.target).toBe("https://example.com")
    expect(report.workflow).toBe("full-scan")
    expect(report.createdAt).toBeTruthy()
  })

  test("generate() computes summary with totalFindings", () => {
    const generator = new ReportGenerator()
    const findings = [makeFinding({ id: "1" }), makeFinding({ id: "2" })]
    const report = generator.generate(findings, "eng-1", "target", "wf")
    expect(report.summary.totalFindings).toBe(2)
  })

  test("generate() groups by severity, confidence, status", () => {
    const generator = new ReportGenerator()
    const findings = [
      makeFinding({
        id: "1",
        severity: Severity.CRITICAL,
        confidence: Confidence.HIGH,
        status: "CONFIRMED",
      }),
      makeFinding({
        id: "2",
        severity: Severity.HIGH,
        confidence: Confidence.MEDIUM,
        status: "PENDING",
      }),
      makeFinding({
        id: "3",
        severity: Severity.MEDIUM,
        confidence: Confidence.LOW,
        status: "PENDING",
      }),
      makeFinding({
        id: "4",
        severity: Severity.LOW,
        confidence: Confidence.INFORMATIONAL,
        status: "REJECTED",
      }),
    ]
    const report = generator.generate(findings, "eng-1", "target", "wf")
    expect(report.summary.bySeverity["CRITICAL"]).toBe(1)
    expect(report.summary.bySeverity["HIGH"]).toBe(1)
    expect(report.summary.bySeverity["MEDIUM"]).toBe(1)
    expect(report.summary.bySeverity["LOW"]).toBe(1)
    expect(report.summary.byConfidence["HIGH"]).toBe(1)
    expect(report.summary.byConfidence["MEDIUM"]).toBe(1)
    expect(report.summary.byConfidence["LOW"]).toBe(1)
    expect(report.summary.byConfidence["INFORMATIONAL"]).toBe(1)
    expect(report.summary.byStatus["CONFIRMED"]).toBe(1)
    expect(report.summary.byStatus["PENDING"]).toBe(2)
    expect(report.summary.byStatus["REJECTED"]).toBe(1)
  })

  test("generateMarkdown() includes target in heading", () => {
    const generator = new ReportGenerator()
    const markdown = generator.generateMarkdown(
      [makeFinding()],
      "eng-1",
      "https://example.com",
      "wf",
    )
    expect(markdown).toContain(
      "# Security Assessment Report: https://example.com",
    )
  })

  test("generateMarkdown() lists all findings sorted by severity desc", () => {
    const generator = new ReportGenerator()
    const findings = [
      makeFinding({
        id: "1",
        severity: Severity.LOW,
        title: "Low Finding",
        description: "desc1",
        cve: undefined,
        cwe: undefined,
        owasp: undefined,
        remediation: undefined,
      }),
      makeFinding({
        id: "2",
        severity: Severity.HIGH,
        title: "High Finding",
        description: "desc2",
        cve: undefined,
        cwe: undefined,
        owasp: undefined,
        remediation: undefined,
      }),
      makeFinding({
        id: "3",
        severity: Severity.CRITICAL,
        title: "Critical Finding",
        description: "desc3",
        cve: undefined,
        cwe: undefined,
        owasp: undefined,
        remediation: undefined,
      }),
    ]
    const markdown = generator.generateMarkdown(
      findings,
      "eng-1",
      "target",
      "wf",
    )
    expect(markdown).toContain("Critical Finding")
    expect(markdown).toContain("High Finding")
    expect(markdown).toContain("Low Finding")
    const criticalIdx = markdown.indexOf("Critical Finding")
    const highIdx = markdown.indexOf("High Finding")
    const lowIdx = markdown.indexOf("Low Finding")
    expect(criticalIdx).toBeLessThan(highIdx)
    expect(highIdx).toBeLessThan(lowIdx)
  })

  test("generateJSON() returns valid JSON string", () => {
    const generator = new ReportGenerator()
    const json = generator.generateJSON(
      [makeFinding()],
      "eng-1",
      "target",
      "wf",
    )
    const parsed = JSON.parse(json)
    expect(parsed.engagementId).toBe("eng-1")
    expect(parsed.target).toBe("target")
    expect(parsed.workflow).toBe("wf")
    expect(parsed.findings).toHaveLength(1)
  })

  test("generateSARIF() produces valid SARIF 2.1.0 structure", () => {
    const generator = new ReportGenerator()
    const findings = [
      makeFinding({
        id: "1",
        severity: Severity.CRITICAL,
        title: "Critical Issue",
        description: "A critical issue",
        cwe: "CWE-89",
      }),
      makeFinding({
        id: "2",
        severity: Severity.INFO,
        title: "Info Note",
        description: "An informational note",
        cwe: undefined,
      }),
    ]
    const sarif = generator.generateSARIF(
      findings,
      "eng-1",
      "https://example.com",
      "full_assessment",
    )
    const parsed = JSON.parse(sarif)
    expect(parsed.$schema).toContain("sarif-schema-2.1.0")
    expect(parsed.version).toBe("2.1.0")
    expect(parsed.runs).toHaveLength(1)
    expect(parsed.runs[0].results).toHaveLength(2)
  })

  test("SARIF output has correct tool driver info", () => {
    const generator = new ReportGenerator()
    const sarif = generator.generateSARIF(
      [makeFinding()],
      "eng-1",
      "target",
      "full_assessment",
    )
    const parsed = JSON.parse(sarif)
    expect(parsed.runs[0].tool.driver.name).toBe("Argus")
    expect(parsed.runs[0].tool.driver.version).toBe("5.0.0")
  })

  test("SARIF results have ruleId, level, message", () => {
    const generator = new ReportGenerator()
    const findings = [
      makeFinding({
        id: "1",
        severity: Severity.HIGH,
        title: "High Issue",
        description: "desc",
        cwe: "CWE-200",
      }),
      makeFinding({
        id: "2",
        severity: Severity.INFO,
        title: "Info Issue",
        description: "desc",
        cwe: undefined,
      }),
    ]
    const sarif = generator.generateSARIF(
      findings,
      "eng-1",
      "target",
      "full_assessment",
    )
    const parsed = JSON.parse(sarif)
    const results = parsed.runs[0].results
    // ruleId now uses finding.id (stable) instead of cwe/array-index
    expect(results[0].ruleId).toBe("1")
    expect(results[0].level).toBe("error")
    expect(results[0].message.text).toBe("High Issue")
    expect(results[1].ruleId).toBe("2")
    expect(results[1].level).toBe("note")
    expect(results[1].message.text).toBe("Info Issue")
  })

  test("Empty findings array produces report with 0 totalFindings", () => {
    const generator = new ReportGenerator()
    const report = generator.generate([], "eng-1", "target", "wf")
    expect(report.summary.totalFindings).toBe(0)
    expect(report.summary.bySeverity).toEqual({})
    expect(report.summary.byConfidence).toEqual({})
    expect(report.summary.byStatus).toEqual({})
  })

  test("Handles findings with null cve/cwe/owasp/remediation", () => {
    const finding = makeFinding({
      cve: undefined,
      cwe: undefined,
      owasp: undefined,
      remediation: undefined,
    })
    const generator = new ReportGenerator()
    const report = generator.generate([finding], "eng-1", "target", "wf")
    expect(report.findings[0].cve).toBeUndefined()
    expect(report.findings[0].cwe).toBeUndefined()

    const markdown = generator.generateMarkdown(
      [finding],
      "eng-1",
      "target",
      "wf",
    )
    expect(markdown).toContain(finding.title)
    expect(markdown).not.toContain("CVE:")
    expect(markdown).not.toContain("CWE:")
    expect(markdown).not.toContain("OWASP:")
    expect(markdown).not.toContain("Remediation:")
  })
})

import { describe, expect, test } from "bun:test"
import { existsSync, mkdtempSync, readFileSync, rmSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"
import { ReportGenerator, coverageGapsFromPhases, evidenceMapFromEngagementEvidence, normalizeProofStatus, persistedReportOptions } from "../../../../src/argus/reporting/generator"
import type { IEngagementStore } from "../../../../src/argus/engagement/types"
import { Severity, Confidence } from "../../../../src/argus/planner/types"
import { ProofStatus } from "../../../../src/argus/shared/types"
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
    // ruleId uses subtype ?? cwe ?? tool for stable SARIF grouping
    expect(results[0].ruleId).toBe("CWE-200")
    expect(results[0].level).toBe("error")
    expect(results[0].message.text).toBe("High Issue")
    expect(results[1].ruleId).toBe("argus-test-tool")
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

  describe("generateHTML", () => {
    test("returns valid HTML with findings", () => {
      const generator = new ReportGenerator()
      const findings = [
        makeFinding({ severity: Severity.CRITICAL, title: "Critical Issue", description: "A critical finding" }),
        makeFinding({ severity: Severity.HIGH, title: "High Issue" }),
      ]
      const html = generator.generateHTML(findings, "eng-1", "https://test.com", "assessment")
      expect(html).toContain("<html")
      expect(html).toContain("Critical Issue")
      expect(html).toContain("High Issue")
      expect(html).toContain("A critical finding")
      expect(html).toContain("CRITICAL")
      expect(html).toContain("HIGH")
    })

    test("handles empty findings array", () => {
      const generator = new ReportGenerator()
      const html = generator.generateHTML([], "eng-1", "https://test.com", "assessment")
      expect(html).toContain("<html")
      expect(html).toContain("Report:")
    })

    test("handles findings with special HTML characters", () => {
      const generator = new ReportGenerator()
      const findings = [makeFinding({ title: "XSS <script>alert(1)</script>", description: "Description with <b>bold</b>" })]
      const html = generator.generateHTML(findings, "eng-1", "https://test.com", "assessment")
      expect(html).toContain("&lt;")
      expect(html).not.toContain("<script>")
    })
  })

  describe("setAnalyses", () => {
    test("analyses are included in markdown output", () => {
      const generator = new ReportGenerator()
      generator.setAnalyses([{
        findingId: "test-1",
        explanation: "This is a critical SQL injection vulnerability",
        impact: ["Data exposure", "Authentication bypass"],
        remediation: ["Use parameterized queries"],
        model: "gpt-4",
        generatedAt: Date.now(),
        findingUpdatedAt: Date.now(),
      }])
      const markdown = generator.generateMarkdown(
        [makeFinding({ id: "test-1" })],
        "eng-1",
        "https://test.com",
        "assessment",
      )
      expect(markdown).toContain("AI Analysis")
      expect(markdown).toContain("SQL injection")
      expect(markdown).toContain("parameterized queries")
    })

    test("analyses are included in HTML output", () => {
      const generator = new ReportGenerator()
      generator.setAnalyses([{
        findingId: "test-1",
        explanation: "Test analysis",
        impact: ["Impact 1"],
        remediation: ["Fix 1"],
        model: "gpt-4",
        generatedAt: Date.now(),
        findingUpdatedAt: Date.now(),
      }])
      const html = generator.generateHTML(
        [makeFinding({ id: "test-1" })],
        "eng-1",
        "https://test.com",
        "assessment",
      )
      expect(html).toContain("Test analysis")
      expect(html).toContain("Impact 1")
      expect(html).toContain("Fix 1")
      expect(html).toContain("ai-analysis")
      expect(html).toContain("gpt-4")
    })
  })

  describe("proof ledger", () => {
    function verifiedFinding(overrides?: Partial<NormalizedFinding>): NormalizedFinding {
      return makeFinding({
        id: "verified-1",
        verificationResult: {
          passed: true,
          proofStatus: ProofStatus.REPRODUCED,
          confidence: 0.92,
          summary: "Payload executed in the test browser",
          verifier: "browser-xss",
          verifiedAt: "2026-11-14T12:00:00.000Z",
          controls: [{ kind: "control-request", description: "Same request without payload" }],
        },
        ...overrides,
      })
    }

    test("counts proof outcomes and identifies findings needing attention", () => {
      const generator = new ReportGenerator()
      const ledger = generator.proofLedger([
        verifiedFinding({ id: "reproduced-1" }),
        makeFinding({ id: "unverified-1" }),
        makeFinding({
          id: "suspected-1",
          verificationResult: {
            passed: true,
            proofStatus: ProofStatus.SUSPECTED,
            confidence: 0.65,
            summary: "Detector matched, but exploitation was not observed",
            verifier: "scanner",
            verifiedAt: "2026-11-14T12:05:00.000Z",
            controls: [],
          },
        }),
      ], ["recon was skipped"])

      expect(ledger.totalFindings).toBe(3)
      expect(ledger.verifiedOutcomes).toBe(2)
      expect(ledger.reproduced).toBe(1)
      expect(ledger.suspected).toBe(1)
      expect(ledger.unverified).toBe(1)
      expect(ledger.reproducedFindingIds).toEqual(["reproduced-1"])
      expect(ledger.attentionFindingIds).toEqual(["unverified-1", "suspected-1"])
      expect(ledger.entries[0].controlComparisons).toEqual([{ kind: "control-request", description: "Same request without payload" }])
      expect(ledger.coverageGaps).toEqual(["recon was skipped"])
    })

    test("markdown reports proof outcomes, attention items, and coverage gaps", () => {
      const generator = new ReportGenerator()
      const markdown = generator.generateMarkdown(
        [verifiedFinding(), makeFinding({ id: "unverified-1" })],
        "eng-1",
        "https://example.com",
        "assessment",
        { coverageGaps: ["privilege escalation was skipped"] },
      )

      expect(markdown).toContain("## Proof ledger")
      expect(markdown).toContain("Verified outcomes: 1 of 2")
      expect(markdown).toContain("unverified-1 (unverified)")
      expect(markdown).toContain("- **Proof:** reproduced (verifier browser-xss, confidence 92%, verified at 2026-11-14T12:00:00.000Z, controls: control-request: Same request without payload)")
      expect(markdown).toContain("privilege escalation was skipped")
    })

    test("HTML and SARIF preserve machine- and human-readable proof metadata", () => {
      const generator = new ReportGenerator()
      const html = generator.generateHTML(
        [verifiedFinding()],
        "eng-1",
        "https://example.com",
        "assessment",
        { coverageGaps: ["post-exploitation was skipped"] },
      )
      expect(html).toContain("Proof ledger")
      expect(html).toContain("Proof: reproduced")
      expect(html).toContain("post-exploitation was skipped")

      const sarif = JSON.parse(generator.generateSARIF(
        [verifiedFinding()],
        "eng-1",
        "https://example.com",
        "assessment",
        { coverageGaps: ["post-exploitation was skipped"] },
      ))
      expect(sarif.runs[0].results[0].properties.proofStatus).toBe("reproduced")
      expect(sarif.runs[0].properties.proofByStatus.reproduced).toBe(1)
      expect(sarif.runs[0].properties.attentionFindingIds).toEqual([])
      expect(sarif.runs[0].properties.coverageGaps).toEqual(["post-exploitation was skipped"])
    })

    test("coverage helper distinguishes completed work from incomplete work", () => {
      expect(coverageGapsFromPhases([
        { name: "recon", status: "COMPLETED" },
        { name: "exploitation", status: "PARTIAL", error: "one tool failed" },
        { name: "post-exploitation", status: "SKIPPED" },
      ])).toEqual([
        "exploitation is partial: one tool failed",
        "post-exploitation was skipped",
      ])
      expect(normalizeProofStatus("PASS")).toBe("reproduced")
    })

    test("evidence packages and artifacts travel with the proof ledger", () => {
      const evidenceByFinding = {
        "verified-1": [{
          packageId: "pkg-1",
          packageHash: "abc123",
          createdAt: Date.now(),
          artifacts: [
            { id: "a-1", path: "requests/request-1.txt", type: "request", sizeBytes: 123 },
            { id: "a-2", path: "responses/response-1.txt", type: "response", sizeBytes: 456 },
          ],
        }],
      }
      const generator = new ReportGenerator()
      const ledger = generator.proofLedger([verifiedFinding()], [], evidenceByFinding)
      expect(ledger.evidencePackages).toBe(1)
      expect(ledger.evidenceArtifacts).toBe(2)
      expect(ledger.entries[0].evidencePackageHashes).toEqual(["abc123"])

      const markdown = generator.generateMarkdown(
        [verifiedFinding()],
        "eng-1",
        "https://example.com",
        "assessment",
        { evidenceByFinding },
      )
      expect(markdown).toContain("- **Evidence:** 1 package, 2 artifacts (abc123)")
      expect(markdown).toContain("requests/request-1.txt (request, 123 bytes)")

      const html = generator.generateHTML(
        [verifiedFinding()],
        "eng-1",
        "https://example.com",
        "assessment",
        { evidenceByFinding },
      )
      expect(html).toContain("Evidence packages")
      expect(html).toContain("responses/response-1.txt")

      const sarif = JSON.parse(generator.generateSARIF(
        [verifiedFinding()],
        "eng-1",
        "https://example.com",
        "assessment",
        { evidenceByFinding },
      ))
      expect(sarif.runs[0].results[0].properties.evidencePackageHashes).toEqual(["abc123"])
      expect(sarif.runs[0].results[0].properties.evidence).toHaveLength(2)
      expect(sarif.runs[0].properties.evidencePackages).toBe(1)
      expect(sarif.runs[0].results[0].properties.controlComparisons).toEqual([{
        kind: "control-request",
        description: "Same request without payload",
      }])
    })

    test("exported reports redact scanned secrets and preserve local finding values", () => {
      const canaries = [
        "canary-bearer-1234567890",
        "AKIAIOSFODNN7EXAMPLE",
        "canary-password-1234567890",
      ]
      const generator = new ReportGenerator()
      generator.setAnalyses([{
        findingId: "verified-1",
        explanation: "Use Authorization: Bearer canary-bearer-1234567890 for comparison.",
        impact: ["api_key=canary-password-1234567890 could be abused"],
        remediation: ["Rotate AKIAIOSFODNN7EXAMPLE"],
        model: "test-model",
        generatedAt: Date.now(),
        findingUpdatedAt: Date.now(),
      }])
      const finding = verifiedFinding({
        title: "Leaked AKIAIOSFODNN7EXAMPLE in response",
        description: "Authorization: Bearer canary-bearer-1234567890 and password=canary-password-1234567890 were returned.",
        verificationResult: {
          passed: true,
          proofStatus: ProofStatus.REPRODUCED,
          confidence: 0.9,
          summary: "Reproduced with Authorization: Bearer canary-bearer-1234567890.",
          verifier: "browser",
          verifiedAt: new Date().toISOString(),
          controls: [{ kind: "control-request", description: "Same request without AKIAIOSFODNN7EXAMPLE" }],
        },
      })
      const markdown = generator.generateMarkdown([finding], "eng-1", "https://example.com", "assessment")
      const json = generator.generateJSON([finding], "eng-1", "https://example.com", "assessment")
      const html = generator.generateHTML([finding], "eng-1", "https://example.com", "assessment")
      const sarif = generator.generateSARIF([finding], "eng-1", "https://example.com", "assessment")
      for (const output of [markdown, json, html, sarif]) {
        for (const canary of canaries) {
          expect(output).not.toContain(canary)
        }
      }
      expect(markdown).toContain("Bearer")
      expect(markdown).toContain("REDACTED")
      expect(json).toContain("__REDACTED_AWS_KEY__")
      expect(finding.title).toContain(canaries[1])
    })

    test("execution snapshots show scope, credential refs, budget, and action outcomes", () => {
      const generator = new ReportGenerator()
      const execution = {
        scope: ["https://example.com"],
        model: "provider/test-model",
        limits: { maxToolCalls: 10 },
        actions: [
          { id: "recon", tool: "recon", status: "succeeded" as const, readOnly: true, reason: "approved recon phase", source: "plan" as const, by: "local-operator" },
          { id: "exploit", tool: "exploit", status: "failed" as const, readOnly: false, error: "target refused the payload", reason: "followed an observed login form", source: "replan-llm" as const, by: "worker:attacker", provenanceActions: [{ tool: "nuclei", outcome: "failed", reasoning: "engine chose nuclei for the login form", identity: "attacker", source: "llm" as const, detail: "target refused the payload" }] },
        ],
        observations: ["recon: discovered a login form"],
        secretRefs: ["credential:analyst"],
        authIdentities: ["credential:analyst", "worker:attacker"],
        budgetUsage: {
          llmCalls: 2,
          llmFailures: 1,
          inputTokens: 100,
          outputTokens: 20,
          costUsd: 0,
          costKnown: false,
          toolCalls: 3,
          requestCount: 5,
          source: "merged (ts driver + worker agent sessions)" as const,
          workerToolCalls: 2,
          discrepancies: ["worker sessions recorded 2 tool call(s); TS driver recorded 3"],
        },
        checkpointAt: "2026-11-14T12:10:00.000Z",
      }
      const markdown = generator.generateMarkdown([makeFinding()], "eng-1", "https://example.com", "assessment", { execution })
      expect(markdown).toContain("## Execution context")
      expect(markdown).toContain("https://example.com")
      expect(markdown).toContain("credential:analyst")
      expect(markdown).toContain("worker:attacker")
      expect(markdown).toContain("merged (ts driver + worker agent sessions)")
      expect(markdown).toContain("worker sessions recorded 2 tool call(s); TS driver recorded 3")
      expect(markdown).toContain("exploit: failed (source replan-llm, by worker:attacker) — target refused the payload")
      expect(markdown).toContain("reason: followed an observed login form")
      expect(markdown).toContain("nuclei: failed (llm, attacker)")

      const html = generator.generateHTML([makeFinding()], "eng-1", "https://example.com", "assessment", { execution })
      expect(html).toContain("Execution context")
      expect(html).toContain("provider/test-model")

      const parsed = JSON.parse(generator.generateJSON([makeFinding()], "eng-1", "https://example.com", "assessment", { execution }))
      expect(parsed.execution.secretRefs).toEqual(["credential:analyst"])
      expect(parsed.execution.authIdentities).toEqual(["credential:analyst", "worker:attacker"])
      expect(parsed.execution.budgetUsage.toolCalls).toBe(3)
      expect(parsed.execution.budgetUsage.source).toBe("merged (ts driver + worker agent sessions)")
      expect(parsed.execution.actions[1].provenanceActions[0].identity).toBe("attacker")
    })

    test("persisted report options carry phases, evidence, and checkpoints together", () => {
      const store = {
        getPhases: () => [{ name: "post-exploitation", status: "SKIPPED" }],
        getEvidenceByEngagement: () => [{
          findingId: "finding-1",
          packages: [{ id: "pkg-1", packageHash: "abc123", createdAt: 123, artifacts: [] }],
        }],
        getLatestCheckpoint: () => ({
          scope: ["https://example.com"],
          secretRefs: ["credential:analyst"],
          authIdentities: ["credential:analyst", "worker:attacker"],
          actions: [{
            id: "recon",
            tool: "recon",
            status: "succeeded",
            readOnly: true,
            reason: "approved recon phase",
            source: "plan",
            by: "local-operator",
            provenance: {
              source: "plan",
              reason: "approved recon phase",
              by: "local-operator",
              actions: [{ tool: "nuclei", outcome: "succeeded-with-findings", reasoning: "engine choice", identity: "attacker", source: "llm" }],
            },
          }],
          observations: [],
          budgetUsage: {
            llmCalls: 0,
            llmFailures: 0,
            inputTokens: 0,
            outputTokens: 0,
            costUsd: 0,
            costKnown: false,
            toolCalls: 2,
            requestCount: 0,
          },
          workerBudget: { toolCalls: 1, executedTools: ["nuclei"], identities: ["attacker"], sessions: 1 },
          checkpointAt: "2026-11-14T12:10:00.000Z",
        }),
      } as unknown as IEngagementStore
      const options = persistedReportOptions(store, "eng-1")
      expect(options.coverageGaps).toEqual(["post-exploitation was skipped"])
      expect(options.evidenceByFinding?.["finding-1"]?.[0].packageId).toBe("pkg-1")
      expect(options.execution?.secretRefs).toEqual(["credential:analyst"])
      expect(options.execution?.authIdentities).toEqual(["credential:analyst", "worker:attacker"])
      expect(options.execution?.actions[0].reason).toBe("approved recon phase")
      expect(options.execution?.actions[0].provenanceActions?.[0].tool).toBe("nuclei")
      expect(options.execution?.budgetUsage.source).toBe("merged (ts driver + worker agent sessions)")
      expect(options.execution?.budgetUsage.workerToolCalls).toBe(1)
      expect(options.execution?.budgetUsage.discrepancies.join(" ")).toContain("worker sessions recorded 1 tool call(s); TS driver recorded 2")
    })

    test("engagement evidence rows are mapped to finding-keyed report evidence", () => {
      const mapped = evidenceMapFromEngagementEvidence([{
        findingId: "verified-1",
        packages: [{
          id: "pkg-1",
          packageHash: "abc123",
          createdAt: 123,
          artifacts: [{ id: "a-1", path: "requests/request-1.txt", type: "request", sizeBytes: 123 }],
        }],
      }])
      expect(mapped["verified-1"][0].packageId).toBe("pkg-1")
      expect(mapped["verified-1"][0].artifacts).toHaveLength(1)
    })
  })

  describe("writeArtifact()", () => {
    function tempDir(): string {
      return mkdtempSync(join(tmpdir(), "argus-report-"))
    }

    test("writes report.md and returns its path", () => {
      const dir = tempDir()
      try {
        const generator = new ReportGenerator()
        const path = generator.writeArtifact("eng-1", "# Report\n", "markdown", dir)
        expect(path).toBe(join(dir, "report.md"))
        expect(readFileSync(path, "utf-8")).toBe("# Report\n")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("creates the engagement directory when it does not exist yet", () => {
      const dir = tempDir()
      try {
        const nested = join(dir, "engagements", "eng-9")
        const generator = new ReportGenerator()
        const path = generator.writeArtifact("eng-9", "{}", "json", nested)
        expect(existsSync(path)).toBe(true)
        expect(path).toBe(join(nested, "report.json"))
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("uses the format as the file extension", () => {
      const dir = tempDir()
      try {
        const generator = new ReportGenerator()
        expect(generator.writeArtifact("eng-1", "<html>", "html", dir)).toBe(join(dir, "report.html"))
        expect(generator.writeArtifact("eng-1", "{}", "sarif", dir)).toBe(join(dir, "report.sarif"))
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("a report with zero findings still leaves an artifact", () => {
      const dir = tempDir()
      try {
        const generator = new ReportGenerator()
        const markdown = generator.generateMarkdown([], "eng-1", "https://test.com", "assessment")
        const path = generator.writeArtifact("eng-1", markdown, "markdown", dir)
        const written = readFileSync(path, "utf-8")
        expect(written).toContain("Total Findings: 0")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })
})

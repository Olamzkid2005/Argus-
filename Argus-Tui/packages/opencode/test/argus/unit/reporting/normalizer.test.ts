import { describe, expect, test } from "bun:test"
import { normalizeFinding } from "../../../../src/argus/reporting/normalizer"
import { Severity, Confidence } from "../../../../src/argus/planner/types"
import type { NormalizedFinding } from "../../../../src/argus/planner/types"

describe("normalizeFinding", () => {
  test("Normalizes a fully-formed finding correctly", () => {
    const raw = {
      id: "find-abc",
      title: "SQL Injection",
      severity: Severity.HIGH,
      confidence: Confidence.VERIFIED,
      description: "A SQL injection vulnerability was found",
      subtype: "injection",
      cve: "CVE-2024-0001",
      cwe: "CWE-89",
      owasp: "API1:2023",
      remediation: "Use parameterized queries",
      tool: "scanner",
      phase: "recon",
    }
    const result = normalizeFinding(raw)
    expect(result.id).toBe("find-abc")
    expect(result.title).toBe("SQL Injection")
    expect(result.severity).toBe(Severity.HIGH)
    expect(result.confidence).toBe(Confidence.VERIFIED)
    expect(result.description).toBe("A SQL injection vulnerability was found")
    expect(result.subtype).toBe("injection")
    expect(result.cve).toBe("CVE-2024-0001")
    expect(result.cwe).toBe("CWE-89")
    expect(result.owasp).toBe("API1:2023")
    expect(result.remediation).toBe("Use parameterized queries")
    expect(result.status).toBe("PENDING")
    expect(result.tool).toBe("scanner")
    expect(result.phase).toBe("recon")
  })

  test("Uses default values for missing fields (title: 'Unknown Finding', status: 'PENDING')", () => {
    const result = normalizeFinding({})
    expect(result.title).toBe("Unknown Finding")
    expect(result.status).toBe("PENDING")
    expect(result.description).toBe("")
    expect(result.tool).toBe("unknown")
    expect(result.phase).toBe("unknown")
  })

  test("Preserves subtype, cve, cwe, owasp, remediation when present", () => {
    const result = normalizeFinding({
      subtype: "xss",
      cve: "CVE-2024-1234",
      cwe: "CWE-79",
      owasp: "API3:2023",
      remediation: "Sanitize inputs",
    })
    expect(result.subtype).toBe("xss")
    expect(result.cve).toBe("CVE-2024-1234")
    expect(result.cwe).toBe("CWE-79")
    expect(result.owasp).toBe("API3:2023")
    expect(result.remediation).toBe("Sanitize inputs")
  })

  test("Generates a unique id when none provided", () => {
    const result1 = normalizeFinding({})
    const result2 = normalizeFinding({})
    expect(result1.id).toBeTruthy()
    expect(result2.id).toBeTruthy()
    expect(result1.id).not.toBe(result2.id)
  })

  test("Uses Severity.INFO and Confidence.INFORMATIONAL as defaults", () => {
    const result = normalizeFinding({})
    expect(result.severity).toBe(Severity.INFO)
    expect(result.confidence).toBe(Confidence.INFORMATIONAL)
  })
})

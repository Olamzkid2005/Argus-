import { describe, expect, test } from "bun:test"
import { ConfidenceEngine } from "@argus/engagement/confidence"
import { Confidence, Severity } from "@argus/planner/types"
import type { NormalizedFinding } from "@argus/planner/types"

function makeFinding(overrides?: Partial<NormalizedFinding>): NormalizedFinding {
  return {
    id: "test-1",
    title: "Test Finding",
    severity: Severity.INFO,
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

describe("ConfidenceEngine", () => {
  describe("promote", () => {
    test("promotes INFORMATIONAL to LOW unconditionally", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({ confidence: Confidence.INFORMATIONAL }))
      expect(result).toBe(Confidence.LOW)
    })

    test("promotes LOW to MEDIUM when tool exists and severity >= 2", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.LOW,
        severity: Severity.MEDIUM,
      }))
      expect(result).toBe(Confidence.MEDIUM)
    })

    test("keeps LOW when severity < 2", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.LOW,
        severity: Severity.INFO,
      }))
      expect(result).toBe(Confidence.LOW)
    })

    test("promotes MEDIUM to HIGH when owasp is set", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.MEDIUM,
        owasp: "API1:2023",
      }))
      expect(result).toBe(Confidence.HIGH)
    })

    test("promotes MEDIUM to HIGH when cwe is set", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.MEDIUM,
        cwe: "CWE-200",
      }))
      expect(result).toBe(Confidence.HIGH)
    })

    test("keeps MEDIUM when neither owasp nor cwe is set", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.MEDIUM,
        owasp: undefined,
        cwe: undefined,
      }))
      expect(result).toBe(Confidence.MEDIUM)
    })

    test("promotes HIGH to VERIFIED when evidence exists", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.HIGH,
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: "" }],
      }))
      expect(result).toBe(Confidence.VERIFIED)
    })

    test("keeps HIGH when evidence array is empty", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.HIGH,
        evidence: [],
      }))
      expect(result).toBe(Confidence.HIGH)
    })

    test("keeps VERIFIED — no promotion to CONFIRMED available", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.VERIFIED,
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: "" }],
      }))
      expect(result).toBe(Confidence.VERIFIED)
    })

    test("promotes INFORMATIONAL to LOW (one tier per call)", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.INFORMATIONAL,
        severity: Severity.MEDIUM,
        tool: "nuclei",
      }))
      expect(result).toBe(Confidence.LOW)
    })

    test("promotes LOW to MEDIUM with severity >= 2 (one tier per call)", () => {
      const engine = new ConfidenceEngine()
      const result = engine.promote(makeFinding({
        confidence: Confidence.LOW,
        severity: Severity.HIGH,
        cwe: "CWE-89",
        evidence: [{ packageId: "pkg-1", findingId: "f-1", artifacts: [], packageHash: "abc", createdAt: "" }],
      }))
      expect(result).toBe(Confidence.MEDIUM)
    })
  })

  describe("shouldFinalize", () => {
    test("returns true when status is CONFIRMED", () => {
      const engine = new ConfidenceEngine()
      expect(engine.shouldFinalize(makeFinding({ status: "CONFIRMED" }))).toBe(true)
    })

    test("returns true when confidence >= VERIFIED", () => {
      const engine = new ConfidenceEngine()
      expect(engine.shouldFinalize(makeFinding({ confidence: Confidence.VERIFIED }))).toBe(true)
      expect(engine.shouldFinalize(makeFinding({ confidence: Confidence.CONFIRMED }))).toBe(true)
    })

    test("returns false for low confidence PENDING findings", () => {
      const engine = new ConfidenceEngine()
      expect(engine.shouldFinalize(makeFinding({ confidence: Confidence.LOW, status: "PENDING" }))).toBe(false)
      expect(engine.shouldFinalize(makeFinding({ confidence: Confidence.INFORMATIONAL, status: "PENDING" }))).toBe(false)
    })

    test("returns false for REJECTED findings even if high confidence", () => {
      const engine = new ConfidenceEngine()
      expect(engine.shouldFinalize(makeFinding({ confidence: Confidence.HIGH, status: "REJECTED" }))).toBe(false)
    })
  })
})

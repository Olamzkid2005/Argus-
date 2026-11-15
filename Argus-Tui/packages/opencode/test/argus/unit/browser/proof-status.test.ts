/**
 * One consistent proof result for every verification path.
 *
 * Stage 4.1 item 1. Verification used to report only `passed` plus a confidence
 * score, so downstream code could not tell "we reproduced it" from "nothing
 * contradicted it" — and a thrown verifier looked the same as a clean negative.
 * `ProofStatus` has exactly five values: suspected, reproduced, not_reproduced,
 * inconclusive, unsupported. A pass with no explicit reproduction is
 * `suspected` (never `reproduced`); a throw is `inconclusive` with the failing
 * step and message; evidence and control references travel with the result.
 */

import { describe, expect, test } from "bun:test"

import { ProofStatus } from "../../../../src/argus/shared/types"
import { Confidence } from "../../../../src/argus/shared/types"
import { VerificationRunner } from "../../../../src/argus/browser/verifiers/runner"
import {
  proofStatusFor,
  verificationResultFrom,
} from "../../../../src/argus/browser/proof"
import type { VerificationScenario, VerifierResult } from "../../../../src/argus/browser/types"

function baseResult(overrides: Partial<VerifierResult> = {}): VerifierResult {
  return {
    passed: true,
    confidence: Confidence.MEDIUM,
    confidenceScore: 0.5,
    evidence: [],
    summary: "verified",
    ...overrides,
  }
}

function scenario(overrides: Partial<VerificationScenario>): VerificationScenario {
  return {
    name: "test-verifier",
    description: "test",
    setup: async () => {},
    execute: async () => {},
    verify: async () => baseResult(),
    collectEvidence: async () => ({
      packageId: "pkg-1",
      findingId: "finding-1",
      artifacts: [],
      packageHash: "hash",
      createdAt: new Date(0).toISOString(),
    }),
    ...overrides,
  }
}

describe("proofStatusFor", () => {
  test("a pass with no explicit reproduction is only suspected", () => {
    expect(proofStatusFor(baseResult({ passed: true }))).toBe(ProofStatus.SUSPECTED)
  })

  test("a negative result is not_reproduced", () => {
    expect(proofStatusFor(baseResult({ passed: false }))).toBe(
      ProofStatus.NOT_REPRODUCED,
    )
  })

  test("an explicit status is preserved — confidence never upgrades it", () => {
    expect(
      proofStatusFor(baseResult({ passed: true, proofStatus: ProofStatus.REPRODUCED })),
    ).toBe(ProofStatus.REPRODUCED)
    expect(
      proofStatusFor(
        baseResult({
          passed: false,
          confidence: Confidence.CONFIRMED,
          confidenceScore: 1,
          proofStatus: ProofStatus.UNSUPPORTED,
        }),
      ),
    ).toBe(ProofStatus.UNSUPPORTED)
  })
})

describe("VerificationRunner", () => {
  test("a completed scenario carries its proof status, evidence and controls", async () => {
    const evidence = {
      packageId: "pkg-1",
      findingId: "finding-1",
      artifacts: [],
      packageHash: "hash",
      createdAt: new Date(0).toISOString(),
    }
    const controls = [
      {
        kind: "control-request",
        description: "same endpoint without the payload",
        outcome: "no execution observed",
      },
    ]

    const result = await new VerificationRunner().run(
      scenario({
        verify: async () => baseResult({ evidence: [evidence], controls }),
      }),
    )

    expect(result.passed).toBe(true)
    expect(result.proofStatus).toBe(ProofStatus.SUSPECTED)
    expect(result.evidence).toEqual([evidence])
    expect(result.controls?.slice(0, controls.length)).toEqual(controls)
    // Teardown is recorded on every completed run (Stage 4.3 item 3).
    expect(result.cleanup).toEqual({ ok: true, detail: "cleanup completed" })
    expect(result.controls?.some((control) => control.kind === "cleanup" && control.outcome === "cleanup completed")).toBe(true)
    expect(result.error).toBeUndefined()
  })

  test("a completed scenario reports the verifier's own cleanup outcome", async () => {
    const result = await new VerificationRunner().run(
      scenario({
        cleanup: async () => {},
        cleanupOutcome: () => ({ ok: true, detail: "browser closed; temporary HAR directory removed" }),
      }),
    )

    expect(result.cleanup).toEqual({
      ok: true,
      detail: "browser closed; temporary HAR directory removed",
    })
    expect(result.controls?.some((control) => control.kind === "cleanup" && control.outcome === "browser closed; temporary HAR directory removed")).toBe(true)
  })

  test("a failed cleanup is recorded instead of being swallowed", async () => {
    const result = await new VerificationRunner().run(
      scenario({
        cleanup: async () => {
          throw new Error("browser already gone")
        },
      }),
    )

    expect(result.cleanup).toEqual({ ok: false, detail: "cleanup failed: browser already gone" })
    // The verification outcome itself is unchanged by a teardown failure.
    expect(result.proofStatus).toBe(ProofStatus.SUSPECTED)
  })

  test("a failing scenario is not_reproduced, not an error", async () => {
    const result = await new VerificationRunner().run(
      scenario({ verify: async () => baseResult({ passed: false, summary: "no diff" }) }),
    )

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.error).toBeUndefined()
  })

  test("a thrown step is inconclusive and records where it failed", async () => {
    const result = await new VerificationRunner().run(
      scenario({
        execute: async () => {
          throw new Error("navigation blocked by scope")
        },
      }),
    )

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.error).toMatchObject({
      step: "execute",
      name: "Error",
      message: "navigation blocked by scope",
    })
    expect(result.evidence).toEqual([])
  })
})

describe("verificationResultFrom", () => {
  test("produces the stored result with status, controls and error detail", () => {
    const controls = [{ kind: "second-identity", description: "user B token" }]
    const stored = verificationResultFrom({
      verifier: "BOLAVerifier",
      result: baseResult({
        proofStatus: ProofStatus.REPRODUCED,
        controls,
        confidenceScore: 0.9,
      }),
      verifiedAt: new Date("2026-01-01T00:00:00.000Z"),
    })

    expect(stored).toEqual({
      passed: true,
      proofStatus: ProofStatus.REPRODUCED,
      confidence: 0.9,
      summary: "verified",
      verifier: "BOLAVerifier",
      verifiedAt: "2026-01-01T00:00:00.000Z",
      controls,
    })
  })

  test("carries a verifier error detail through", () => {
    const stored = verificationResultFrom({
      verifier: "BOLAVerifier",
      result: baseResult({
        passed: false,
        proofStatus: ProofStatus.INCONCLUSIVE,
        error: { step: "verify", name: "Error", message: "boom" },
      }),
      verifiedAt: new Date("2026-01-01T00:00:00.000Z"),
    })

    expect(stored.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(stored.error).toEqual({ step: "verify", name: "Error", message: "boom" })
    expect(stored.controls).toEqual([])
  })

  test("carries the cleanup outcome into the stored result", () => {
    const stored = verificationResultFrom({
      verifier: "StoredXSSVerifier",
      result: baseResult({ cleanup: { ok: true, detail: "browser closed" } }),
      verifiedAt: new Date("2026-01-01T00:00:00.000Z"),
    })

    expect(stored.cleanup).toEqual({ ok: true, detail: "browser closed" })
  })
})

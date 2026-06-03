import { describe, expect, test } from "bun:test"
import { VerificationRunner } from "../../../../../src/argus/browser/verifiers/runner"
import type { VerificationScenario, VerifierResult } from "../../../../../src/argus/browser/types"
import { Confidence } from "../../../../../src/argus/planner/types"

const passingScenario: VerificationScenario = {
  name: "test",
  description: "test",
  setup: async () => {},
  execute: async () => {},
  verify: async () => ({
    passed: true,
    confidence: Confidence.HIGH,
    evidence: [],
    summary: "ok",
  }),
  collectEvidence: async () => ({
    packageId: "",
    findingId: "",
    screenshots: [],
    requests: [],
    responses: [],
    logs: [],
    createdAt: "",
  }),
}

describe("VerificationRunner", () => {
  test("run() executes setup, execute, verify, collectEvidence in order", async () => {
    const order: string[] = []
    const scenario: VerificationScenario = {
      name: "ordered",
      description: "ordered",
      setup: async () => {
        order.push("setup")
      },
      execute: async () => {
        order.push("execute")
      },
      verify: async () => {
        order.push("verify")
        return {
          passed: true,
          confidence: Confidence.HIGH,
          evidence: [],
          summary: "ok",
        }
      },
      collectEvidence: async () => {
        order.push("collectEvidence")
        return {
          packageId: "pkg-1",
          findingId: "f-1",
          screenshots: [],
          requests: [],
          responses: [],
          logs: [],
          createdAt: "",
        }
      },
    }
    const runner = new VerificationRunner()
    await runner.run(scenario)
    expect(order).toEqual(["setup", "execute", "verify", "collectEvidence"])
  })

  test("Returns result with evidence array from collectEvidence", async () => {
    const evidence = {
      packageId: "ev-1",
      findingId: "f-1",
      screenshots: ["shot1"],
      requests: [],
      responses: [],
      logs: [],
      createdAt: "2024-01-01",
    }
    const scenario: VerificationScenario = {
      name: "ev-test",
      description: "ev-test",
      setup: async () => {},
      execute: async () => {},
      verify: async () => ({
        passed: true,
        confidence: Confidence.MEDIUM,
        evidence: [],
        summary: "verified",
      }),
      collectEvidence: async () => evidence,
    }
    const runner = new VerificationRunner()
    const result = await runner.run(scenario)
    expect(result.evidence).toHaveLength(1)
    expect(result.evidence[0]).toBe(evidence)
    expect(result.passed).toBe(true)
  })

  test("Handles errors by returning failed result with error summary", async () => {
    const scenario: VerificationScenario = {
      name: "error-test",
      description: "error-test",
      setup: async () => {
        throw new Error("Setup failed")
      },
      execute: async () => {},
      verify: async () => ({
        passed: true,
        confidence: Confidence.HIGH,
        evidence: [],
        summary: "ok",
      }),
      collectEvidence: async () => ({
        packageId: "",
        findingId: "",
        screenshots: [],
        requests: [],
        responses: [],
        logs: [],
        createdAt: "",
      }),
    }
    const runner = new VerificationRunner()
    const result = await runner.run(scenario)
    expect(result.passed).toBe(false)
    expect(result.confidence).toBe(0)
    expect(result.evidence).toHaveLength(0)
    expect(result.summary).toBe("Verification failed: Setup failed")
  })

  test("Handles scenario where verify returns passed=false", async () => {
    const scenario: VerificationScenario = {
      name: "fail-test",
      description: "fail-test",
      setup: async () => {},
      execute: async () => {},
      verify: async () => ({
        passed: false,
        confidence: Confidence.LOW,
        evidence: [],
        summary: "verification did not pass",
      }),
      collectEvidence: async () => ({
        packageId: "",
        findingId: "",
        screenshots: [],
        requests: [],
        responses: [],
        logs: [],
        createdAt: "",
      }),
    }
    const runner = new VerificationRunner()
    const result = await runner.run(scenario)
    expect(result.passed).toBe(false)
    expect(result.summary).toBe("verification did not pass")
  })
})

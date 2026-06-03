import { describe, expect, test } from "bun:test"
import { detectTargetType, detectAuthState, determineRequiredCapabilities } from "../../../src/argus/planner/strategy"
import { ConfidenceEngine } from "../../../src/argus/engagement/confidence"
import { determineNewCapabilities } from "../../../src/argus/planner/replan-rules"
import { planDeterministic } from "../../../src/argus/planner/planDeterministic"
import { normalizeFinding } from "../../../src/argus/reporting/normalizer"
import { isAccessDenied } from "../../../src/argus/browser/login"
import { compareObservations } from "../../../src/argus/browser/observer"
import { VerificationRunner } from "../../../src/argus/browser/verifiers/runner"
import { WorkerSupervisor } from "../../../src/argus/bridge/supervisor"
import { ApprovalService } from "../../../src/argus/workflows/approval"
import { EvidenceCollector } from "../../../src/argus/evidence/collector"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { Capability } from "../../../src/argus/planner/capabilities"
import { Severity, Confidence } from "../../../src/argus/planner/types"
import type { NormalizedFinding, PlannerContext } from "../../../src/argus/planner/types"
import type { VerificationScenario, VerifierResult, EvidencePackage } from "../../../src/argus/browser/types"
import type { PhaseExecutionRequest } from "../../../src/argus/planner/types"

describe("Strategy edge cases", () => {
  describe("detectTargetType", () => {
    test("URL with mixed case", () => {
      expect(detectTargetType("HTTP://EXAMPLE.COM/API/V1")).toBe("api")
      expect(detectTargetType("HTTPS://MYAPP.COM")).toBe("web_app")
    })

    test("URL with query params", () => {
      expect(detectTargetType("https://example.com?api=true")).toBe("web_app")
      expect(detectTargetType("https://example.com/api?version=1")).toBe("api")
    })

    test("URL with fragments", () => {
      expect(detectTargetType("https://example.com#section")).toBe("web_app")
      expect(detectTargetType("https://example.com/api#fragment")).toBe("api")
    })

    test("IP address", () => {
      expect(detectTargetType("http://192.168.1.1")).toBe("web_app")
      expect(detectTargetType("http://10.0.0.1/api")).toBe("api")
    })

    test("localhost", () => {
      expect(detectTargetType("http://localhost:3000")).toBe("web_app")
      expect(detectTargetType("http://127.0.0.1")).toBe("web_app")
    })
  })

  describe("detectAuthState", () => {
    test("URL with 'oauth' in subdomain", () => {
      expect(detectAuthState("https://oauth.example.com")).toBe("oauth")
      expect(detectAuthState("https://auth.example.com/login")).toBe("oauth")
    })

    test("URL with 'token' in query params", () => {
      expect(detectAuthState("https://example.com?token=abc123")).toBe("jwt")
      expect(detectAuthState("https://example.com?access_token=xyz")).toBe("jwt")
    })
  })

  describe("determineRequiredCapabilities", () => {
    test("empty techStack array", () => {
      const caps = determineRequiredCapabilities("web_app", "none", [])
      expect(caps).toContain(Capability.WEB_RECON)
      expect(caps).toContain(Capability.PORT_SCANNING)
      expect(caps).toContain(Capability.BROWSER_VERIFICATION)
      expect(caps).toContain(Capability.REPORT_GENERATION)
    })

    test("duplicate capabilities are not returned", () => {
      const caps = determineRequiredCapabilities("web_app", "none", ["react", "react"])
      const unique = new Set(caps)
      expect(unique.size).toBe(caps.length)
    })

    test("all possible target types produce valid capability sets", () => {
      for (const target of ["web_app", "api", "spa", "unknown"] as const) {
        const caps = determineRequiredCapabilities(target, "none")
        expect(caps.length).toBeGreaterThan(0)
        expect(caps).toContain(Capability.WEB_RECON)
        expect(caps).toContain(Capability.BROWSER_VERIFICATION)
        expect(caps).toContain(Capability.REPORT_GENERATION)
      }
    })
  })
})

describe("ConfidenceEngine edge cases", () => {
  const engine = new ConfidenceEngine()

  test("promote: Finding with maximum confidence (CONFIRMED) stays CONFIRMED", () => {
    const finding: NormalizedFinding = {
      id: "test", title: "Test", severity: Severity.CRITICAL, confidence: Confidence.CONFIRMED,
      status: "PENDING", description: "", tool: "test", phase: "test",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }
    const result = engine.promote(finding)
    expect(result).toBe(Confidence.CONFIRMED)
  })

  test("promote: Finding with minimum values works", () => {
    const finding: NormalizedFinding = {
      id: "test", title: "Test", severity: Severity.INFO, confidence: Confidence.INFORMATIONAL,
      status: "PENDING", description: "", tool: "", phase: "",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }
    const result = engine.promote(finding)
    expect(result).toBe(Confidence.LOW)
  })

  test("shouldFinalize: Already FINALIZED findings", () => {
    const finding: NormalizedFinding = {
      id: "test", title: "Test", severity: Severity.MEDIUM, confidence: Confidence.MEDIUM,
      status: "FINALIZED", description: "", tool: "test", phase: "test",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }
    expect(engine.shouldFinalize(finding)).toBe(false)
  })

  test("Multiple sequential promotions", () => {
    const engine2 = new ConfidenceEngine()
    const finding: NormalizedFinding = {
      id: "test", title: "Test", severity: Severity.HIGH, confidence: Confidence.LOW,
      status: "PENDING", description: "", tool: "scanner", cwe: "CWE-79",
      phase: "test", created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }
    const first = engine2.promote(finding)
    expect(first).toBe(Confidence.HIGH)
    const secondFinding = { ...finding, confidence: first, evidence: [{ packageId: "p1", findingId: "test", artifacts: [], packageHash: "hash", createdAt: "" }] }
    const second = engine2.promote(secondFinding)
    expect(second).toBe(Confidence.VERIFIED)
    const thirdFinding = { ...secondFinding, confidence: second }
    const third = engine2.promote(thirdFinding)
    expect(third).toBe(Confidence.VERIFIED)
  })
})

describe("Replan-rules edge cases", () => {
  test("Multiple findings with same subtype deduplicated", () => {
    const context: PlannerContext = {
      target: "https://example.com", targetType: "web_app", authState: "none",
      findings: [
        { id: "1", title: "SQLi 1", severity: Severity.HIGH, confidence: Confidence.HIGH, status: "PENDING", description: "", subtype: "sqli_reflective", tool: "a", phase: "p", created_at: "", updated_at: "" },
        { id: "2", title: "SQLi 2", severity: Severity.HIGH, confidence: Confidence.HIGH, status: "PENDING", description: "", subtype: "sqli_reflective", tool: "a", phase: "p", created_at: "", updated_at: "" },
        { id: "3", title: "SQLi 3", severity: Severity.HIGH, confidence: Confidence.HIGH, status: "PENDING", description: "", subtype: "sqli_blind", tool: "a", phase: "p", created_at: "", updated_at: "" },
      ],
      executedCapabilities: new Set(),
      insertedPhases: new Set(),
      replanCount: 0,
    }
    const caps = determineNewCapabilities(context)
    expect(caps.size).toBe(1)
    expect(caps.has(Capability.SQLI_DETECTION)).toBe(true)
  })

  test("Finding with subtype that doesn't match any known key", () => {
    const context: PlannerContext = {
      target: "https://example.com", targetType: "web_app", authState: "none",
      findings: [
        { id: "1", title: "Unknown", severity: Severity.LOW, confidence: Confidence.LOW, status: "PENDING", description: "", subtype: "unknown_subtype_xyz", tool: "a", phase: "p", created_at: "", updated_at: "" },
      ],
      executedCapabilities: new Set(),
      insertedPhases: new Set(),
      replanCount: 0,
    }
    const caps = determineNewCapabilities(context)
    expect(caps.size).toBe(0)
  })

  test("Executed capabilities matching all findings' subtypes", () => {
    const context: PlannerContext = {
      target: "https://example.com", targetType: "web_app", authState: "none",
      findings: [
        { id: "1", title: "GraphQL", severity: Severity.MEDIUM, confidence: Confidence.MEDIUM, status: "PENDING", description: "", subtype: "graphql", tool: "a", phase: "p", created_at: "", updated_at: "" },
      ],
      executedCapabilities: new Set([Capability.GRAPHQL_ASSESSMENT]),
      insertedPhases: new Set(),
      replanCount: 0,
    }
    const caps = determineNewCapabilities(context)
    expect(caps.size).toBe(0)
  })

  test("Empty findings array", () => {
    const context: PlannerContext = {
      target: "https://example.com", targetType: "web_app", authState: "none",
      findings: [],
      executedCapabilities: new Set(),
      insertedPhases: new Set(),
      replanCount: 0,
    }
    const caps = determineNewCapabilities(context)
    expect(caps.size).toBe(0)
  })
})

describe("PlanDeterministic edge cases", () => {
  test("Unknown target type returns 2 phases only", () => {
    const plan = planDeterministic("unknown-target")
    expect(plan.phases).toHaveLength(2)
    expect(plan.phases[0].requiredCapabilities).toContain(Capability.WEB_RECON)
    expect(plan.phases[0].requiredCapabilities).toContain(Capability.PORT_SCANNING)
    expect(plan.phases[1].requiredCapabilities).toContain(Capability.REPORT_GENERATION)
  })

  test("Error recovery defaults to one of the valid policies", () => {
    const plan = planDeterministic("https://example.com")
    for (const recovery of Object.values(plan.errorRecovery)) {
      expect(["retry_once_then_skip", "skip_and_continue", "fail_fast"]).toContain(recovery)
    }
  })

  test("Phase IDs follow correct naming pattern", () => {
    const plan = planDeterministic("https://example.com/api")
    for (const phase of plan.phases) {
      expect(phase.phaseId).toMatch(/^phase-\d+-\w+$/)
    }
  })
})

describe("Normalizer edge cases", () => {
  test("Null input for optional fields coerces to null", () => {
    const result = normalizeFinding({ id: "f1", title: "Test", severity: 2, confidence: 2, description: null, cve: null, cwe: null, remediation: null })
    expect(result.description).toBe("")
    expect((result as any).cve).toBeNull()
    expect((result as any).cwe).toBeNull()
    expect((result as any).remediation).toBeNull()
  })

  test("Very long title strings", () => {
    const longTitle = "A".repeat(10000)
    const result = normalizeFinding({ id: "f1", title: longTitle, severity: 1, confidence: 1, description: "desc" })
    expect(result.title.length).toBe(10000)
    expect(result.title).toBe(longTitle)
  })

  test("Special characters in fields", () => {
    const special = "<script>alert('xss')</script> & \"quotes\""
    const result = normalizeFinding({ id: "f1", title: special, severity: 1, confidence: 1, description: special, tool: special, phase: special })
    expect(result.title).toBe(special)
    expect(result.description).toBe(special)
    expect(result.tool).toBe(special)
    expect(result.phase).toBe(special)
  })

  test("Missing tool and phase fields default to 'unknown'", () => {
    const result = normalizeFinding({ id: "f1", title: "Test", severity: 0, confidence: 0, description: "" })
    expect(result.tool).toBe("unknown")
    expect(result.phase).toBe("unknown")
  })
})

describe("isAccessDenied edge cases", () => {
  test("Text with '403' in a word (not status code)", () => {
    // Fixed: word-boundary regex means "403rd" no longer matches
    expect(isAccessDenied("The error code 403rd times the charm")).toBe(false)
  })

  test("HTML content with error messages in comments", () => {
    expect(isAccessDenied("<!-- 403 Forbidden -->")).toBe(true)
    expect(isAccessDenied("<!-- access denied -->")).toBe(true)
  })

  test("Mixed case 'Forbidden'", () => {
    expect(isAccessDenied("ForBidDen")).toBe(true)
    expect(isAccessDenied("fOrBiDdEn")).toBe(true)
  })
})

describe("compareObservations edge cases", () => {
  test("Null or undefined DOM fields", () => {
    const a = { url: "https://a.com", domSnapshot: "", responseHeaders: {}, statusCode: 200, timestamp: "" }
    const b = { url: "https://b.com", domSnapshot: "", responseHeaders: {}, statusCode: 200, timestamp: "" }
    const result = compareObservations(a, b)
    expect(result.changed).toBe(false)
  })

  test("Very large DOM diff", () => {
    const a = { url: "", domSnapshot: Array(1000).fill("line").join("\n"), responseHeaders: {}, statusCode: 200, timestamp: "" }
    const b = { url: "", domSnapshot: Array(1000).fill("different").join("\n"), responseHeaders: {}, statusCode: 200, timestamp: "" }
    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions.length).toBe(1000)
    expect(result.removals.length).toBe(1000)
  })

  test("Single line difference", () => {
    const a = { url: "", domSnapshot: "line1\nline2\nline3", responseHeaders: {}, statusCode: 200, timestamp: "" }
    const b = { url: "", domSnapshot: "line1\nCHANGED\nline3", responseHeaders: {}, statusCode: 200, timestamp: "" }
    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions).toContain("CHANGED")
    expect(result.removals).toContain("line2")
  })

  test("DOM with special characters", () => {
    const a = { url: "", domSnapshot: "<div data-test='hello & world'>a < b</div>", responseHeaders: {}, statusCode: 200, timestamp: "" }
    const b = { url: "", domSnapshot: "<div data-test='hello & world'>a < b</div>", responseHeaders: {}, statusCode: 200, timestamp: "" }
    const result = compareObservations(a, b)
    expect(result.changed).toBe(false)
  })
})

describe("VerificationRunner edge cases", () => {
  const runner = new VerificationRunner()

  test("Scenario that throws during setup", async () => {
    const scenario: VerificationScenario = {
      name: "throw-setup", description: "",
      async setup() { throw new Error("Setup failed") },
      async execute() {},
      async verify(): Promise<VerifierResult> { return { passed: true, confidence: 5, evidence: [], summary: "ok" } },
      async collectEvidence(): Promise<EvidencePackage> { return { packageId: "", findingId: "", screenshots: [], requests: [], responses: [], logs: [], createdAt: "" } },
    }
    const result = await runner.run(scenario)
    expect(result.passed).toBe(false)
    expect(result.confidence).toBe(0)
    expect(result.summary).toContain("Setup failed")
  })

  test("Scenario that throws during execute", async () => {
    const scenario: VerificationScenario = {
      name: "throw-execute", description: "",
      async setup() {},
      async execute() { throw new Error("Execute failed") },
      async verify(): Promise<VerifierResult> { return { passed: true, confidence: 5, evidence: [], summary: "ok" } },
      async collectEvidence(): Promise<EvidencePackage> { return { packageId: "", findingId: "", screenshots: [], requests: [], responses: [], logs: [], createdAt: "" } },
    }
    const result = await runner.run(scenario)
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("Execute failed")
  })

  test("scenario.verify returns empty evidence", async () => {
    const scenario: VerificationScenario = {
      name: "no-evidence", description: "",
      async setup() {},
      async execute() {},
      async verify(): Promise<VerifierResult> { return { passed: true, confidence: 3, evidence: [], summary: "passed" } },
      async collectEvidence(): Promise<EvidencePackage> { return { packageId: "", findingId: "", screenshots: [], requests: [], responses: [], logs: [], createdAt: "" } },
    }
    const result = await runner.run(scenario)
    expect(result.passed).toBe(true)
    expect(result.confidence).toBe(3)
  })
})

describe("WorkerSupervisor edge cases", () => {
  test("restartWorker called exactly maxRestarts times throws error", async () => {
    let connectCount = 0
    const bridge = {
      restartWorker: async () => {},
      killChild: () => {},
      connect: async () => { connectCount++ },
      isHealthy: async () => true,
    }
    const supervisor = new WorkerSupervisor(bridge)
    await supervisor.restartWorker()
    await supervisor.restartWorker()
    await supervisor.restartWorker()
    expect(connectCount).toBe(3)
    await expect(supervisor.restartWorker()).rejects.toThrow("Worker crashed too many times")
  })

  test("Worker health check that alternates healthy/unhealthy", async () => {
    let healthy = true
    const bridge = {
      restartWorker: async () => {},
      killChild: () => {},
      connect: async () => {},
      isHealthy: async () => healthy,
    }
    const supervisor = new WorkerSupervisor(bridge)
    expect(await supervisor.isHealthy()).toBe(true)
    healthy = false
    expect(await supervisor.isHealthy()).toBe(false)
  })

  test("Multiple resetAttempts calls keep attempts at 0", async () => {
    const bridge = {
      restartWorker: async () => {},
      killChild: () => {},
      connect: async () => {},
      isHealthy: async () => true,
    }
    const supervisor = new WorkerSupervisor(bridge)
    supervisor.resetAttempts()
    supervisor.resetAttempts()
    supervisor.resetAttempts()
    await supervisor.restartWorker()
  })
})

describe("ApprovalService edge cases", () => {
  const service = new ApprovalService()

  test("getRequiredGates with all false values", () => {
    const gates = service.getRequiredGates({ destructive_tools: false, auth_testing: false })
    expect(gates).toHaveLength(0)
  })

  test("needsApproval with duplicated capabilities", () => {
    const phase: PhaseExecutionRequest = {
      phaseId: "test", workflowName: "test", target: "https://example.com",
      requiredCapabilities: [Capability.AUTH_DETECTION, Capability.AUTH_DETECTION],
      config: {}, previousPhaseResults: [],
      approvalGateName: "auth_testing",
    }
    const gates = service.getRequiredGates({ auth_testing: true })
    const result = service.needsApproval(phase, gates)
    expect(result).not.toBeNull()
    expect(result!.name).toBe("auth_testing")
  })

  test("Multiple gates match the same phase", () => {
    const phase: PhaseExecutionRequest = {
      phaseId: "test", workflowName: "test", target: "https://example.com",
      requiredCapabilities: [Capability.VULNERABILITY_SCANNING, Capability.AUTH_DETECTION, Capability.BROWSER_VERIFICATION],
      config: {}, previousPhaseResults: [],
      approvalGateName: "destructive_tools",
    }
    const gates = service.getRequiredGates({ destructive_tools: true, auth_testing: true, privilege_escalation: true })
    const result = service.needsApproval(phase, gates)
    expect(result).not.toBeNull()
    expect(result!.name).toBe("destructive_tools")
  })
})

describe("EvidenceCollector edge cases", () => {
  let tmpDir: string

  test("saveRequest with empty string content", async () => {
    tmpDir = mkdtempSync(join(tmpdir(), "argus-evidence-test-"))
    const collector = new EvidenceCollector(tmpDir)
    const entry = await collector.saveRequest("eng-1", "find-1", "")
    expect(entry.type).toBe("request")
    expect(entry.size_bytes).toBe(0)
    expect(entry.hash).toBeTruthy()
    rmSync(tmpDir, { recursive: true, force: true })
  })

  test("createPackage with empty artifacts array", async () => {
    tmpDir = mkdtempSync(join(tmpdir(), "argus-evidence-test-"))
    const collector = new EvidenceCollector(tmpDir)
    const manifest = await collector.createPackage("eng-1", "find-empty", [])
    expect(manifest.artifacts).toHaveLength(0)
    expect(manifest.package_hash).toBeTruthy()
    expect(manifest.package_id).toBe("find-empty")
    rmSync(tmpDir, { recursive: true, force: true })
  })

  test("Concurrent save operations", async () => {
    tmpDir = mkdtempSync(join(tmpdir(), "argus-evidence-test-"))
    const collector = new EvidenceCollector(tmpDir)
    const results = await Promise.all([
      collector.saveRequest("eng-con", "find-con", "request data"),
      collector.saveResponse("eng-con", "find-con", "response data"),
      collector.saveRequest("eng-con", "find-con", "another request"),
    ])
    expect(results).toHaveLength(3)
    for (const r of results) {
      expect(r.hash).toBeTruthy()
      expect(r.path).toBeTruthy()
    }
    rmSync(tmpDir, { recursive: true, force: true })
  })
})

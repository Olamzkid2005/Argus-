import { describe, expect, test } from "bun:test"
import { planDeterministic } from "@argus/planner/planDeterministic"
import { Capability } from "@argus/planner/capabilities"

describe("planDeterministic", () => {
  test("creates 6 phases for web_app target", () => {
    const plan = planDeterministic("https://example.com")
    expect(plan.phases).toHaveLength(6)
    expect(plan.phases[0].phaseId).toContain("recon")
    expect(plan.phases[1].phaseId).toContain("auth_detection")
    expect(plan.phases[2].phaseId).toContain("vuln_scan")
    expect(plan.phases[3].phaseId).toContain("ai_testing")
    expect(plan.phases[4].phaseId).toContain("verification")
    expect(plan.phases[5].phaseId).toContain("reporting")
  })

  test("creates 7 phases for api target", () => {
    const plan = planDeterministic("https://example.com/api/v1")
    expect(plan.phases).toHaveLength(7)
    expect(plan.phases[0].phaseId).toContain("recon")
    expect(plan.phases[1].phaseId).toContain("api_discovery")
    expect(plan.phases[2].phaseId).toContain("auth_detection")
    expect(plan.phases[3].phaseId).toContain("vuln_scan")
    expect(plan.phases[4].phaseId).toContain("ai_testing")
    expect(plan.phases[5].phaseId).toContain("verification")
    expect(plan.phases[6].phaseId).toContain("reporting")
  })

  test("creates 6 phases for spa target", () => {
    const plan = planDeterministic("https://app.example.com")
    expect(plan.phases).toHaveLength(6)
    expect(plan.phases[0].phaseId).toContain("recon")
    expect(plan.phases[1].phaseId).toContain("auth_detection")
    expect(plan.phases[2].phaseId).toContain("vuln_scan")
    expect(plan.phases[3].phaseId).toContain("ai_testing")
    expect(plan.phases[4].phaseId).toContain("verification")
    expect(plan.phases[5].phaseId).toContain("reporting")
  })

  test("creates 2 phases for unknown target", () => {
    const plan = planDeterministic("localhost")
    expect(plan.phases).toHaveLength(2)
    expect(plan.phases[0].phaseId).toContain("recon")
    expect(plan.phases[1].phaseId).toContain("reporting")
  })

  test("auth-capable phases request the capabilities that reach auth/BOLA tests", () => {
    const plan = planDeterministic("https://example.com")
    const authPhase = plan.phases.find((p) => p.name === "auth_detection")
    expect(authPhase?.requiredCapabilities).toContain(Capability.AUTH_DETECTION)
    expect(authPhase?.requiredCapabilities).toContain(Capability.CREDENTIAL_ANALYSIS)

    const verification = plan.phases.find((p) => p.name === "verification")
    expect(verification?.requiredCapabilities).toContain(Capability.BROWSER_VERIFICATION)
    expect(verification?.requiredCapabilities).toContain(Capability.FINDING_VERIFICATION)
  })

  test("sets error recovery policy per phase", () => {
    const plan = planDeterministic("https://example.com")
    expect(plan.errorRecovery["phase-0-recon"]).toBe("retry_once_then_skip")
    expect(plan.errorRecovery["phase-2-vuln_scan"]).toBe("retry_once_then_skip")
    expect(plan.errorRecovery["phase-5-reporting"]).toBe("skip_and_continue")
  })

  test("sets workflow to deterministic", () => {
    const plan = planDeterministic("https://example.com")
    expect(plan.workflow).toBe("deterministic")
  })

  test("handles URLs with /api/ path -> api target type", () => {
    const plan = planDeterministic("https://example.com/api/v2/users")
    expect(plan.phases).toHaveLength(7)
    expect(plan.phases.some((p) => p.phaseId.includes("api_discovery"))).toBe(true)
  })

  test("target is stored in each phase request", () => {
    const plan = planDeterministic("https://example.com")
    for (const phase of plan.phases) {
      expect(phase).toHaveProperty("target")
    }
  })
})

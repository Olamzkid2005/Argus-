import type { TargetType, AssessmentPlan, PhaseExecutionRequest, ErrorRecovery } from "./types"
import { Capability } from "./capabilities"
import { detectTargetType } from "./strategy"

const PHASE_ERROR_POLICY: Record<string, ErrorRecovery> = {
  recon: "retry_once_then_skip",
  vuln_scan: "retry_once_then_skip",
  auth_detection: "skip_and_continue",
  api_discovery: "skip_and_continue",
  ai_testing: "skip_and_continue",
  verification: "skip_and_continue",
  reporting: "skip_and_continue",
}

function getTargetPlans(target: string): Record<TargetType, PhaseExecutionRequest[]> {
  return {
    // An authenticated target needs phases that can actually exercise its
    // logged-in surface. Without them the run only ever saw the public pages:
    // login, BOLA/BOPLA, JWT and session checks were never dispatched, so the
    // planted auth/IDOR findings on the labs were invisible (see
    // livefire-runs/autonomy-observed-20261118/README.md). The auth and
    // verification phases below are what make those capability providers
    // reachable; each is skipped with a recorded degradation when no tool for
    // it is installed.
    web_app: [
      createPhase("recon", [Capability.WEB_RECON, Capability.PORT_SCANNING, Capability.TECHNOLOGY_DETECTION], "parallel", 0, target),
      createPhase("auth_detection", [Capability.AUTH_DETECTION, Capability.CREDENTIAL_ANALYSIS], "sequential", 1, target),
      createPhase("vuln_scan", [Capability.VULNERABILITY_SCANNING, Capability.TEMPLATE_SCANNING], "parallel", 2, target),
      createPhase("ai_testing", [Capability.AI_VULNERABILITY_TESTING], "sequential", 3, target),
      createPhase("verification", [Capability.BROWSER_VERIFICATION, Capability.FINDING_VERIFICATION], "sequential", 4, target),
      createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 5, target),
    ],
    api: [
      createPhase("recon", [Capability.WEB_RECON, Capability.TECHNOLOGY_DETECTION], "parallel", 0, target),
      createPhase("api_discovery", [Capability.API_PROBING, Capability.CONTENT_DISCOVERY], "parallel", 1, target),
      createPhase("auth_detection", [Capability.AUTH_DETECTION, Capability.CREDENTIAL_ANALYSIS], "sequential", 2, target),
      createPhase("vuln_scan", [Capability.VULNERABILITY_SCANNING], "parallel", 3, target),
      createPhase("ai_testing", [Capability.AI_VULNERABILITY_TESTING], "sequential", 4, target),
      createPhase("verification", [Capability.BROWSER_VERIFICATION, Capability.FINDING_VERIFICATION], "sequential", 5, target),
      createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 6, target),
    ],
    spa: [
      createPhase("recon", [Capability.WEB_RECON, Capability.TECHNOLOGY_DETECTION], "parallel", 0, target),
      createPhase("auth_detection", [Capability.AUTH_DETECTION, Capability.CREDENTIAL_ANALYSIS], "sequential", 1, target),
      createPhase("vuln_scan", [Capability.VULNERABILITY_SCANNING], "parallel", 2, target),
      createPhase("ai_testing", [Capability.AI_VULNERABILITY_TESTING], "sequential", 3, target),
      createPhase("verification", [Capability.BROWSER_VERIFICATION, Capability.FINDING_VERIFICATION], "sequential", 4, target),
      createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 5, target),
    ],
    unknown: [
      createPhase("recon", [Capability.WEB_RECON, Capability.PORT_SCANNING], "parallel", 0, target),
      createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 1, target),
    ],
  }
}

function createPhase(
  name: string,
  capabilities: Capability[],
  execution: "parallel" | "sequential",
  phaseIndex: number,
  target: string,
): PhaseExecutionRequest {
  return {
    phaseId: `phase-${phaseIndex}-${name}`,
    name,
    workflowName: "deterministic",
    target,
    requiredCapabilities: capabilities,
    config: {},
    previousPhaseResults: [],
    toolExecution: execution,
  }
}

export function planDeterministic(target: string): AssessmentPlan {
  const targetType = detectTargetType(target)
  const phases = getTargetPlans(target)[targetType]
  const errorRecovery: Record<string, ErrorRecovery> = {}

  for (const phase of phases) {
    errorRecovery[phase.phaseId] = PHASE_ERROR_POLICY[phase.name] ?? "skip_and_continue"
  }

  return {
    workflow: "deterministic",
    phases,
    errorRecovery,
    planCreatedAt: new Date().toISOString(),
  }
}

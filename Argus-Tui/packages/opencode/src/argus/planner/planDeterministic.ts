import { TargetType, AssessmentPlan, PhaseExecutionRequest, ErrorRecovery } from "./types"
import { Capability } from "./capabilities"
import { detectTargetType } from "./strategy"

const PHASE_ERROR_POLICY: Record<string, ErrorRecovery> = {
  recon: "retry_once_then_skip",
  vuln_scan: "retry_once_then_skip",
  auth_detection: "skip_and_continue",
  api_discovery: "skip_and_continue",
  verification: "skip_and_continue",
  reporting: "fail_fast",
}

const TARGET_PLANS: Record<TargetType, PhaseExecutionRequest[]> = {
  web_app: [
    createPhase("recon", [Capability.WEB_RECON, Capability.PORT_SCANNING, Capability.TECHNOLOGY_DETECTION], "parallel", 0),
    createPhase("vuln_scan", [Capability.VULNERABILITY_SCANNING, Capability.TEMPLATE_SCANNING], "parallel", 1),
    createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 2),
  ],
  api: [
    createPhase("recon", [Capability.WEB_RECON, Capability.TECHNOLOGY_DETECTION], "parallel", 0),
    createPhase("api_discovery", [Capability.API_PROBING, Capability.CONTENT_DISCOVERY], "parallel", 1),
    createPhase("vuln_scan", [Capability.VULNERABILITY_SCANNING], "parallel", 2),
    createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 3),
  ],
  spa: [
    createPhase("recon", [Capability.WEB_RECON, Capability.TECHNOLOGY_DETECTION], "parallel", 0),
    createPhase("vuln_scan", [Capability.VULNERABILITY_SCANNING], "parallel", 1),
    createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 2),
  ],
  unknown: [
    createPhase("recon", [Capability.WEB_RECON, Capability.PORT_SCANNING], "parallel", 0),
    createPhase("reporting", [Capability.REPORT_GENERATION], "sequential", 1),
  ],
}

function createPhase(
  name: string,
  capabilities: Capability[],
  execution: "parallel" | "sequential",
  phaseIndex: number,
): PhaseExecutionRequest {
  return {
    phaseId: `phase-${phaseIndex}-${name}`,
    workflowName: "deterministic",
    target: "",
    requiredCapabilities: capabilities,
    config: {},
    previousPhaseResults: [],
  }
}

export function planDeterministic(target: string): AssessmentPlan {
  const targetType = detectTargetType(target)
  const phases = TARGET_PLANS[targetType]
  const errorRecovery: Record<string, ErrorRecovery> = {}

  for (const phase of phases) {
    errorRecovery[phase.phaseId] = PHASE_ERROR_POLICY[phase.phaseId.split("-")[2]] ?? "skip_and_continue"
  }

  return {
    workflow: "deterministic",
    phases,
    errorRecovery,
    planCreatedAt: new Date().toISOString(),
  }
}

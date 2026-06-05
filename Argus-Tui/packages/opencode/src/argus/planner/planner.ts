import type { PlannerContext, AssessmentPlan, PhaseExecutionRequest } from "./types"
import { Capability } from "./capabilities"
import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { detectTargetType, detectAuthState, determineRequiredCapabilities } from "./strategy"
import { determineNewCapabilities } from "./replan-rules"
import { planDeterministic } from "./planDeterministic"

const MAX_REPLANS = 10

interface PlanOptions {
  useLLM?: boolean
}

export class WorkflowPlanner {
  constructor(
    private workflowRegistry: WorkflowRegistry,
    private toolRegistry: ToolRegistry,
  ) {}

  async plan(target: string, context?: Partial<PlannerContext>, options?: PlanOptions): Promise<AssessmentPlan> {
    const targetType = detectTargetType(target)
    const authState = detectAuthState(target)

    const plannerContext: PlannerContext = {
      target,
      targetType,
      authState,
      findings: context?.findings ?? [],
      executedCapabilities: context?.executedCapabilities ?? new Set(),
      insertedPhases: context?.insertedPhases ?? new Set(),
      replanCount: context?.replanCount ?? 0,
      techStack: context?.techStack,
    }

    const techFromFindings = plannerContext.findings
      .filter((f) => f.subtype === "technology" || f.subtype === "framework" || f.subtype === "language")
      .map((f) => f.title)
    if (techFromFindings.length > 0) {
      plannerContext.techStack = [
        ...new Set([...(plannerContext.techStack ?? []), ...techFromFindings]),
      ]
    }

    if (options?.useLLM === false) {
      const plan = planDeterministic(target)
      // Filter out phases with zero tools (unless fail_fast) — deterministic
      // mode uses hardcoded phases that may reference capabilities no tool provides.
      plan.phases = plan.phases.filter((p) => {
        const tools = this.toolRegistry.selectBest(p.requiredCapabilities as any, targetType)
        if (tools.length > 0) return true
        const name = p.phaseId.split("-").slice(2).join("-")
        const skip = plan.errorRecovery?.[p.phaseId] !== "fail_fast"
        if (skip) return false
        process.stderr.write(`Warning: Adding fail_fast phase "${name}" with zero available tools\n`)
        return true
      })
      return plan
    }

    const requiredCaps = determineRequiredCapabilities(targetType, authState, plannerContext.techStack)
    const workflow = this.workflowRegistry.findByCapabilities(requiredCaps)

    if (!workflow) {
      return planDeterministic(target)
    }

    const phases: PhaseExecutionRequest[] = []
    for (let i = 0; i < workflow.phases.length; i++) {
      const def = workflow.phases[i]
      // Pass gate context for tech-based and scheme-based tool filtering
      const tools = this.toolRegistry.selectBest(def.required_capabilities, targetType, {
        techStack: plannerContext.techStack,
        targetScheme: target.startsWith("https") ? "https" : "http",
      })

      if (tools.length === 0) {
        if (def.error_recovery !== "fail_fast") {
          continue
        }
        process.stderr.write(`Warning: Adding fail_fast phase "${def.name}" with zero available tools\n`)
      }

      phases.push({
        phaseId: `phase-${i}-${def.name}`,
        workflowName: workflow.name,
        target,
        requiredCapabilities: def.required_capabilities,
        config: {},
        previousPhaseResults: [],
        approvalGateName: def.approval_gate,
      })
    }

    return {
      workflow: workflow.name,
      phases,
      errorRecovery: Object.fromEntries(
        workflow.phases.map((p, i) => [`phase-${i}-${p.name}`, p.error_recovery]),
      ),
      planCreatedAt: new Date().toISOString(),
    }
  }

  replan(context: PlannerContext): PhaseExecutionRequest[] | null {
    if (context.replanCount >= MAX_REPLANS) {
      return null
    }

    const newCapabilities = determineNewCapabilities(context)
    const unhandled = Array.from(newCapabilities).filter((c) => !context.executedCapabilities.has(c))

    if (unhandled.length === 0) return null

    const nextReplanCount = context.replanCount + 1

    return unhandled.map((cap) => ({
      phaseId: `replan-${nextReplanCount}-${cap}`,
      workflowName: "replan",
      target: context.target,
      requiredCapabilities: [cap],
      config: {},
      previousPhaseResults: [],
    }))
  }
}

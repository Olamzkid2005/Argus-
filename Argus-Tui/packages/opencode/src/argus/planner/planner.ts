import { PlannerContext, AssessmentPlan, PhaseExecutionRequest } from "./types"
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

    if (options?.useLLM === false) {
      return planDeterministic(target)
    }

    const requiredCaps = determineRequiredCapabilities(targetType, authState, plannerContext.techStack)
    const workflow = this.workflowRegistry.findByCapabilities(requiredCaps)

    if (!workflow) {
      return planDeterministic(target)
    }

    const phases: PhaseExecutionRequest[] = []
    for (let i = 0; i < workflow.phases.length; i++) {
      const def = workflow.phases[i]
      const tools = this.toolRegistry.findBestTools(def.required_capabilities, targetType)

      if (tools.length === 0 && def.error_recovery !== "fail_fast") {
        continue
      }

      phases.push({
        phaseId: `phase-${i}-${def.name}`,
        workflowName: workflow.name,
        target,
        requiredCapabilities: def.required_capabilities,
        config: {},
        previousPhaseResults: [],
      })
    }

    return {
      workflow: workflow.name,
      phases,
      errorRecovery: Object.fromEntries(
        workflow.phases.map((p) => [`phase-${workflow.phases.indexOf(p)}-${p.name}`, p.error_recovery]),
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

    context.replanCount++

    return unhandled.map((cap, i) => ({
      phaseId: `replan-${context.replanCount}-${cap}`,
      workflowName: "replan",
      target: context.target,
      requiredCapabilities: [cap],
      config: {},
      previousPhaseResults: [],
    }))
  }
}

import crypto from "crypto"
import type { PlannerContext, AssessmentPlan, PhaseExecutionRequest } from "./types"
import { Capability } from "./capabilities"
import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { detectTargetType, detectAuthState, determineRequiredCapabilities } from "./strategy"
import { determineNewCapabilities, REPLAN_INSERTABLE } from "./replan-rules"
import { planDeterministic } from "./planDeterministic"
import { resolvePipeline, formatPipelineGaps } from "./pipeline"
import { getTargetValidator } from "../shared/target-validator"

export const MAX_REPLANS = (() => {
  const raw = process.env.ARGUS_MAX_REPLANS
  if (raw === undefined || raw === "") return 10     // default
  const n = Number(raw)
  return Number.isFinite(n) && n >= 0 ? n : 10       // coerce NaN/negative to default
})()

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

    // Enforce allowed_git_hosts when the target looks like a git repository URL
    // (e.g. github.com/org/repo, gitlab.com/namespace/project.git)
    const gitHostMatch = target.match(
      /^(?:https?:\/\/)?(?:git@)?((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})(?=\/|:|$)/
    )
    if (gitHostMatch) {
      const validator = getTargetValidator()
      if (!validator.isGitHostAllowed(gitHostMatch[1])) {
        throw new Error(
          `Git host "${gitHostMatch[1]}" is not in the allowed list. ` +
          `Add it to security.allowed_git_hosts in argus.config.yaml or ` +
          `set allowed_git_hosts to [] to allow all hosts.`
        )
      }
    }

    const plannerContext: PlannerContext = {
      target,
      targetType,
      authState,
      findings: context?.findings ?? [],
      executedCapabilities: context?.executedCapabilities ?? new Set(),
      insertedPhases: context?.insertedPhases ?? new Set(),
      replanCount: context?.replanCount ?? 0,
      techStack: context?.techStack,
      hypotheses: context?.hypotheses,
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
        const skip = plan.errorRecovery?.[p.phaseId] !== "fail_fast"
        if (skip) {
          process.stderr.write(`Warning: Skipping phase "${p.name}" — zero available tools\n`)
          return false
        }
        process.stderr.write(`Warning: Adding fail_fast phase "${p.name}" with zero available tools\n`)
        return true
      })
      return plan
    }

    const requiredCaps = determineRequiredCapabilities(targetType, authState, plannerContext.techStack)
    const workflow = this.workflowRegistry.findByCapabilities(requiredCaps)

    if (!workflow) {
      console.warn(
        `[planner] No workflow found covering required capabilities for target "${target}" ` +
        `(${targetType}, ${authState}) — falling back to deterministic plan. ` +
        `Some capabilities may have no tool provider.`
      )
      return planDeterministic(target)
    }

    // quick_scan workflow uses cost-aware tool selection to prefer lightweight tools
    const workflowCostFilter = workflow.name === "quick_scan" ? "no_high" : undefined

    const phases: PhaseExecutionRequest[] = []
    for (let i = 0; i < workflow.phases.length; i++) {
      const def = workflow.phases[i]
      // Pass gate context for tech-based and scheme-based tool filtering
      const tools = this.toolRegistry.selectBest(def.required_capabilities, targetType, {
        techStack: plannerContext.techStack,
        targetScheme: target.startsWith("https") ? "https" : "http",
      }, workflowCostFilter)

      if (tools.length === 0) {
        if (def.error_recovery !== "fail_fast") {
          process.stderr.write(`Warning: Skipping phase "${def.name}" — zero available tools\n`)
          continue
        }
        process.stderr.write(`Warning: Adding fail_fast phase "${def.name}" with zero available tools\n`)
      }

      const pipeline = tools.length > 0
        ? resolvePipeline(tools.map(t => ({
            name: t.name,
            capabilities: t.capabilities,
            consumes: t.consumes,
            provides: t.provides,
          })))
        : null

      if (pipeline && pipeline.gaps.length > 0) {
        process.stderr.write(
          `[planner] Phase "${def.name}" — ${formatPipelineGaps(pipeline.gaps, tools.map(t => t.name))}\n`,
        )
      }

      if (pipeline && pipeline.circular) {
        process.stderr.write(`[planner] Warning: Circular dependency detected in phase "${def.name}" — broken by priority\n`)
      }

      phases.push({
        phaseId: `phase-${i}-${def.name}-${crypto.randomUUID().slice(0, 8)}`,
        name: def.name,
        workflowName: workflow.name,
        target,
        requiredCapabilities: def.required_capabilities,
        config: {
          pipelineSteps: pipeline?.steps,
          pipelineGaps: pipeline?.gaps,
        },
        previousPhaseResults: [],
        approvalGateName: def.approval_gate,
        toolExecution: def.execution,
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
    // Negative findings are exempt from MAX_REPLANS on first consideration
    const hasNegativeFindings = context.findings.some((f) => f.negative)
    const maxReplans = (context.maxReplans != null && Number.isFinite(context.maxReplans) && context.maxReplans >= 0)
      ? context.maxReplans
      : MAX_REPLANS
    const effectiveMax = hasNegativeFindings ? maxReplans + 1 : maxReplans
    if (context.replanCount >= effectiveMax) {
      return null
    }

    const newCapabilities = determineNewCapabilities(context)
    // Capabilities derived from negative findings are kept even if already
    // executed — the absence of evidence suggests a different approach is needed
    const unhandled = Array.from(newCapabilities).filter((c) => {
      if (context.executedCapabilities.has(c)) {
        return context.findings.some(
          (f) => f.negative && f.subtype && REPLAN_INSERTABLE[f.subtype] === c,
        )
      }
      return true
    })

    if (unhandled.length === 0) return null

    const nextReplanCount = context.replanCount + 1

    return unhandled.map((cap) => ({
      phaseId: `replan-${nextReplanCount}-${cap}`,
      name: `replan-${cap.toLowerCase()}`,
      workflowName: "replan",
      target: context.target,
      requiredCapabilities: [cap],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential",
      replanCycle: true,
    }))
  }
}

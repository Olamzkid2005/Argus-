import crypto from "crypto"
import type { PlannerContext, AssessmentPlan, PhaseExecutionRequest } from "./types"
import { Capability, guessCapability } from "./capabilities"
import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { detectTargetType, detectAuthState, determineRequiredCapabilities } from "./strategy"
import { determineNewCapabilities, REPLAN_INSERTABLE } from "./replan-rules"
import { planDeterministic } from "./planDeterministic"
import { resolvePipeline, formatPipelineGaps } from "./pipeline"
import { getTargetValidator } from "../shared/target-validator"
import { LLMPlannerService } from "./llm-service"
import type { ProgressEvent } from "../shared/progress"

export const MAX_REPLANS = (() => {
  const raw = process.env.ARGUS_MAX_REPLANS
  if (raw === undefined || raw === "") return 10     // default
  const n = Number(raw)
  return Number.isFinite(n) && n >= 0 ? n : 10       // coerce NaN/negative to default
})()

export const LLM_MAX_REPLANS = (() => {
  const raw = process.env.ARGUS_LLM_MAX_REPLANS
  if (raw === undefined || raw === "") return 10     // default
  const n = Number(raw)
  return Number.isFinite(n) && n >= 0 ? n : 10       // coerce NaN/negative to default
})()

interface PlanOptions {
  useLLM?: boolean
  /** Optional progress callback for emitting structured events to the TUI */
  onProgress?: (event: ProgressEvent) => void
}

export class WorkflowPlanner {
  constructor(
    private workflowRegistry: WorkflowRegistry,
    private toolRegistry: ToolRegistry,
  ) {}

  async plan(target: string, context?: Partial<PlannerContext>, options?: PlanOptions): Promise<AssessmentPlan> {
    const emitProgress = options?.onProgress
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
      const hasError = plan.phases.some((p) => {
        const tools = this.toolRegistry.selectBest(p.requiredCapabilities as any, targetType)
        return tools.length === 0 && plan.errorRecovery?.[p.phaseId] !== "fail_fast"
      })
      // In autonomous mode, fail hard if ANY phase has zero tools
      if (hasError) {
        const zeroToolsPhases = plan.phases
          .filter((p) => {
            const tools = this.toolRegistry.selectBest(p.requiredCapabilities as any, targetType)
            return tools.length === 0
          })
          .map((p) => p.name)
        if (process.env.ARGUS_AUTONOMOUS === "1" || process.env.ARGUS_AUTONOMOUS === "true") {
          throw new Error(
            `[Argus] ARGUS_AUTONOMOUS=1: ${zeroToolsPhases.length} phase(s) have zero available tools: ${zeroToolsPhases.join(", ")}. ` +
            `Install the required security tools or disable autonomous mode.`
          )
        }
      }
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

    // ── Phase 1: LLM-assisted capability suggestion ──
    // Use the OpenCode Session LLM to suggest additional capabilities
    // beyond the deterministic baseline. LLM suggestions are merged
    // with the deterministic set — duplicates are removed.
    const deterministicCaps = determineRequiredCapabilities(targetType, authState, plannerContext.techStack)

    // If LLM is enabled, ask it for phase suggestions
    let llmSuggested: string[] = []
    if (options?.useLLM !== false) {
      emitProgress?.({ type: "llm_planning_start", phase: "initial" })
      try {
        const llmSvc = LLMPlannerService.lazy()
        const result = await llmSvc.suggestPhases(target, targetType, plannerContext.techStack)
        if (result.suggestedPhases.length > 0) {
          for (const phase of result.suggestedPhases) {
            llmSuggested.push(...phase.capabilities)
          }
          process.stderr.write(
            `[planner] LLM suggested ${result.suggestedPhases.length} additional phase(s) for ${target}\n`,
          )
        }
        // Emit LLM analysis results for TUI display
        emitProgress?.({
          type: "llm_planning_complete",
          phase: "initial",
          targetAnalysis: result.targetAnalysis,
          suggestions: result.suggestedPhases.map((p) => ({
            capabilities: p.capabilities,
            reasoning: p.reasoning,
          })),
          llmModel: llmSvc.getModelId(),
          modelEnvDescription: LLMPlannerService.getModelEnvVarDescription(),
        })
      } catch (e) {
        emitProgress?.({
          type: "llm_planning_error",
          phase: "initial",
          error: (e as Error).message,
        })
        // LLM failure is non-blocking — fall back to deterministic planning
      }
    }

    // Merge LLM suggestions into deterministic capabilities
    const requiredCaps = [...deterministicCaps]
    for (const raw of llmSuggested) {
      const cap = guessCapability(raw)
      if (cap !== undefined && !requiredCaps.includes(cap)) {
        requiredCaps.push(cap)
      }
    }

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

  async replan(context: PlannerContext): Promise<PhaseExecutionRequest[] | null> {
    const emitProgress = context.onProgress
    // ── Independent budgets for LLM and rule-based replanning ──
    // LLM suggestions and rule-based capabilities each have their own counter
    // and max. This prevents LLM replanning from starving rule-based replanning
    // and vice versa.
    const hasNegativeFindings = context.findings.some((f) => f.negative)
    const maxReplans = (context.maxReplans != null && Number.isFinite(context.maxReplans) && context.maxReplans >= 0)
      ? context.maxReplans
      : MAX_REPLANS
    const effectiveMax = hasNegativeFindings ? maxReplans + 1 : maxReplans
    const ruleBudgetExhausted = context.replanCount >= effectiveMax

    const llmMax = (context.llmMaxReplans != null && Number.isFinite(context.llmMaxReplans) && context.llmMaxReplans >= 0)
      ? context.llmMaxReplans
      : LLM_MAX_REPLANS
    const llmBudgetExhausted = (context.llmReplanCount ?? 0) >= llmMax

    // If BOTH budgets are exhausted, no replanning at all
    if (ruleBudgetExhausted && llmBudgetExhausted) return null

    // ── Build capability set from rule-based sources (findings, hypotheses) ──
    const newCapabilities = new Set<Capability>()
    if (!ruleBudgetExhausted) {
      const ruleCaps = determineNewCapabilities(context)
      for (const cap of ruleCaps) newCapabilities.add(cap)
    }

    // ── Merge LLM-suggested capabilities (independent budget) ──
    // Two LLM sources feed into replanning:
    //   1. Python MCP worker (via bridge.phaseComplete) — existing, kept for
    //      backward compatibility
    //   2. OpenCode Session LLM (local, via @opencode-ai/llm) — NEW, runs
    //      alongside the MCP path for richer analysis
    let llmProducedPhases = false

    // Source 1: Python MCP bridge (existing) — external LLM analysis
    if (!llmBudgetExhausted && context.llmSuggestedCapabilities && context.llmSuggestedCapabilities.length > 0) {
      for (const raw of context.llmSuggestedCapabilities) {
        const cap = guessCapability(raw)
        if (cap && !context.executedCapabilities.has(cap)) {
          newCapabilities.add(cap)
          llmProducedPhases = true
        }
      }
    }

    // Source 2: OpenCode Session LLM (local) — runs alongside MCP path
    if (!llmBudgetExhausted && context.findings.length > 0) {
      try {
        const llmSvc = LLMPlannerService.lazy()
        const llmReplan = await llmSvc.suggestReplan(context.target, context.findings)
        if (llmReplan && !llmReplan.stopAssessment) {
          for (const raw of llmReplan.nextCapabilities) {
            const cap = guessCapability(raw)
            if (cap !== undefined && !context.executedCapabilities.has(cap) && !newCapabilities.has(cap)) {
              newCapabilities.add(cap)
              llmProducedPhases = true
            }
          }
        }
        // Emit LLM replan analysis for TUI display
        if (llmReplan) {
          emitProgress?.({
            type: "llm_replan_analysis",
            label: context.target,
            reasoning: llmReplan.reasoning,
            suggestedCapabilities: llmReplan.nextCapabilities,
            stopAssessment: llmReplan.stopAssessment,
            llmModel: llmSvc.getModelId(),
          })
        }
      } catch (e) {
        emitProgress?.({
          type: "llm_planning_error",
          phase: "replan",
          error: (e as Error).message,
        })
        // Local LLM failure is non-blocking — rule-based replanning continues
        console.warn(`[planner] Local LLM replan failed: ${(e as Error).message}`)
      }
    }

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

    // ── Attack chain phase generation ──
    // When the attack graph has detected chains, we generate exploitation
    // phases that turn correlated findings into active exploitation steps.
    // These are inserted IMMEDIATELY after the current phase using splice().
    const chainPhases: PhaseExecutionRequest[] = []
    if (context.chainPlans && context.chainPlans.length > 0) {
      const nextReplanCount = context.replanCount + 1
      for (const plan of context.chainPlans) {
        // Map chain suggested capabilities to actual registered capabilities
        const caps = plan.suggested_capabilities
          .map((c) => {
            // Find the matching Capability enum value
            const found = Object.values(Capability).find(
              (cap) => cap.toLowerCase() === c.toLowerCase() ||
                       cap.replace(/_/g, "").toLowerCase() === c.replace(/_/g, "").toLowerCase()
            )
            return found ?? c as Capability
          })
          .filter((c) => !context.executedCapabilities.has(c))

        if (caps.length === 0) continue

        chainPhases.push({
          phaseId: `chain-${nextReplanCount}-${plan.chain_id}-${crypto.randomUUID().slice(0, 8)}`,
          name: `exploit-${plan.chain_id}`,
          workflowName: "chain_exploitation",
          target: context.target,
          requiredCapabilities: caps,
          config: {
            chainPlan: plan,
            chainDescription: plan.description,
          },
          previousPhaseResults: [],
          toolExecution: "sequential",
          replanCycle: true,
        })
      }
    }

    // Combine regular replan phases with chain exploitation phases
    const nextReplanCount = context.replanCount + 1
    const regularPhases = unhandled.map((cap) => ({
      phaseId: `replan-${nextReplanCount}-${cap}`,
      name: `replan-${cap.toLowerCase()}`,
      workflowName: "replan",
      target: context.target,
      requiredCapabilities: [cap],
      config: {},
      previousPhaseResults: [],
      toolExecution: "sequential" as const,
      replanCycle: true,
    }))

    const allPhases = [...chainPhases, ...regularPhases]
    if (allPhases.length === 0) return null

    // ── Increment budgets independently ──
    // Each source that produced phases consumes one cycle of its own budget.
    // This prevents one source from starving the other.
    // Crucially, when the rule budget is exhausted, LLM-only phases must NOT
    // increment the rule counter — even though they flow through regularPhases.
    if (llmProducedPhases) {
      context.llmReplanCount = (context.llmReplanCount ?? 0) + 1
    }
    // Rule counter only increments for actual rule/chain content.
    // When ruleBudgetExhausted is true, regularPhases came entirely from
    // LLM suggestions (determineNewCapabilities was skipped).
    const hasRuleContent = (!ruleBudgetExhausted && regularPhases.length > 0) || chainPhases.length > 0
    if (hasRuleContent) {
      context.replanCount++
    }

    return allPhases
  }
}

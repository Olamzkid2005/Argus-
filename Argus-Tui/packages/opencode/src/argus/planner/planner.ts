import crypto from "crypto"
import type { PlannerContext, AssessmentPlan, PhaseExecutionRequest, ChainPhasePlan } from "./types"
import { Capability, guessCapability } from "./capabilities"
import { WorkflowRegistry } from "../workflows/registry"
import { ToolRegistry } from "../workflows/tool-registry"
import { detectTargetType, detectAuthState, determineRequiredCapabilities } from "./strategy"
import { determineNewCapabilities, REPLAN_INSERTABLE } from "./replan-rules"
import { planDeterministic } from "./planDeterministic"
import { resolvePipeline, formatPipelineGaps } from "./pipeline"
import { getTargetValidator } from "../shared/target-validator"
import { LLMPlannerService } from "./llm-service"
import type { LLMPhaseSuggestionResult, LLMReplanSuggestion } from "./llm-service"
import type { ProgressEvent } from "../shared/progress"
import type { GateContext } from "../workflows/tool-registry"

/** Actual URL scheme of a target (http/https/ftp...), lowercased. */
function targetSchemeOf(target: string): string {
  const match = target.trim().toLowerCase().match(/^([a-z][a-z0-9+.-]*):\/\//)
  if (match) return match[1]
  return "https"
}

/** Recon signals published so far: finding subtypes plus tech fingerprints. */
function reconSignalsOf(context: Partial<Pick<PlannerContext, "findings" | "techStack">>): string[] | undefined {
  const signals = new Set<string>()
  for (const finding of context.findings ?? []) {
    const subtype = (finding as { subtype?: unknown }).subtype
    if (typeof subtype === "string" && subtype.trim() !== "") signals.add(subtype.trim().toLowerCase())
  }
  for (const tech of context.techStack ?? []) {
    if (tech.trim() !== "") signals.add(tech.trim().toLowerCase())
  }
  return signals.size > 0 ? [...signals] : undefined
}

/** Full activation-gate context for the current target and observations. */
function gateContextFor(
  target: string,
  context: Partial<Pick<PlannerContext, "findings" | "techStack">>,
): GateContext {
  const reconSignals = reconSignalsOf(context)
  return {
    techStack: context.techStack,
    targetScheme: targetSchemeOf(target),
    ...(reconSignals !== undefined ? { reconSignals } : {}),
  }
}

/**
 * Names the LLM may pin: every tool that survives the full eligibility
 * filters (enabled, worker-runnable, target type, activation gates) for its
 * own capabilities. A named tool the LLM invents — or one whose gates are
 * not satisfied in this context — is absent and therefore never pinned.
 */
function eligibleToolNames(
  registry: ToolRegistry,
  targetType: string,
  gateContext: GateContext,
): Set<string> {
  const eligible = new Set<string>()
  const partial = registry as Partial<ToolRegistry> & {
    selectBest?: (caps: Capability[], targetType?: string, gate?: GateContext) => Array<{ name: string }>
    listTools?: () => Array<{ name: string }>
  }
  if (typeof partial.selectBest === "function") {
    // Union over every capability: selectBest returns all passing tools per
    // capability (sorted, not top-1), so the union is every runnable tool.
    const caps = Object.values(Capability)
    for (const cap of caps) {
      try {
        for (const tool of partial.selectBest([cap], targetType, gateContext)) {
          eligible.add(tool.name)
        }
      } catch {
        // A test-double registry may throw for unknown capabilities; ignore.
      }
    }
    return eligible
  }
  // Test doubles without selectBest: fall back to the raw tool list minus
  // worker-blocked entries (the only signal available).
  if (typeof partial.listTools === "function") {
    const isBlocked = typeof registry.isWorkerBlocked === "function"
      ? (name: string) => registry.isWorkerBlocked(name)
      : () => false
    for (const tool of partial.listTools()) {
      if (!isBlocked(tool.name)) eligible.add(tool.name)
    }
  }
  return eligible
}

/** Keep only LLM-named tools that are actually eligible right now. */
function validNamedTools(
  registry: ToolRegistry,
  names: readonly string[] | undefined,
  targetType: string,
  gateContext: GateContext,
): string[] {
  if (!names || names.length === 0) return []
  const eligible = eligibleToolNames(registry, targetType, gateContext)
  const seen = new Set<string>()
  const valid: string[] = []
  for (const name of names) {
    if (typeof name !== "string" || seen.has(name)) continue
    seen.add(name)
    if (eligible.has(name)) valid.push(name)
  }
  return valid
}

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

/**
 * The planner-facing surface of LLMPlannerService.
 *
 * Declared here so the planner can be exercised with a substituted LLM via
 * constructor injection instead of `mock.module()` — a process-global mock of
 * `./llm-service` leaks into every other test file in the same bun run and
 * silently replaces the real service (see planner LLM tests).
 */
export interface PlannerLLM {
  suggestPhases(
    target: string,
    targetType: string,
    techStack?: string[],
    toolCatalogue?: string,
  ): Promise<LLMPhaseSuggestionResult>
  suggestReplan(
    target: string,
    findings: ReadonlyArray<{ title: string; severity: number; subtype?: string; confidence: number }>,
    toolCatalogue?: string,
  ): Promise<LLMReplanSuggestion | null>
  getModelId(): string
}

export interface PlannerDeps {
  /** Override the LLM planner. Defaults to the real LLMPlannerService. */
  llm?: PlannerLLM
}

export class WorkflowPlanner {
  constructor(
    private workflowRegistry: WorkflowRegistry,
    private toolRegistry: ToolRegistry,
    private deps?: PlannerDeps,
  ) {}

  private plannerLLM(): PlannerLLM {
    return this.deps?.llm ?? LLMPlannerService.lazy()
  }

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
      // Autonomous runs do not abort over a missing tool: one unavailable
      // scanner used to end the whole assessment. The zero-tool phases are
      // dropped below and named on plan.degradations so the runner can report
      // the lost coverage and continue with the rest.
      if (hasError) {
        const zeroToolsPhases = plan.phases
          .filter((p) => {
            const tools = this.toolRegistry.selectBest(p.requiredCapabilities as any, targetType)
            return tools.length === 0
          })
          .map((p) => `${p.name} (no installed tool for ${p.requiredCapabilities.join(", ")})`)
        plan.degradations = [...(plan.degradations ?? []), ...zeroToolsPhases]
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

    // The planning LLM reasons over the actual eligible tool catalogue —
    // not bare capability names — so its suggestions name tools that exist
    // and can run against this target (gates already applied). Test doubles
    // predate the catalogue methods, so their absence means "no catalogue",
    // not a crash: the prompts degrade to capability-only mode.
    const gateContext = gateContextFor(target, plannerContext)
    const describe = (this.toolRegistry as Partial<ToolRegistry>).describeToolsForCapabilities
    const toolCatalogue = typeof describe === "function"
      ? describe.call(this.toolRegistry, deterministicCaps, targetType, gateContext)
      : undefined

    // LLM-assisted phase suggestions (explicit false handled by early return above)
    let llmSuggested: string[] = []
    let llmPinnedTools: string[] = []
    emitProgress?.({ type: "llm_planning_start", phase: "initial" })
      try {
        const llmSvc = this.plannerLLM()
        const result = await llmSvc.suggestPhases(target, targetType, plannerContext.techStack, toolCatalogue)
        if (result.suggestedPhases.length > 0) {
          for (const phase of result.suggestedPhases) {
            llmSuggested.push(...phase.capabilities)
          }
          process.stderr.write(
            `[planner] LLM suggested ${result.suggestedPhases.length} additional phase(s) for ${target}\n`,
          )
        }
        // Named-tool selection is structural on the initial plan too, not just
        // on replan: validate the names against the actually eligible set
        // (exists, enabled, worker-runnable, gates satisfied) and pin the
        // survivors per-phase below. An ineligible name is dropped, never trusted.
        llmPinnedTools = validNamedTools(this.toolRegistry, result.nextTools, targetType, gateContext)
        if ((result.nextTools?.length ?? 0) > 0) {
          process.stderr.write(
            `[planner] LLM named ${result.nextTools?.length} tool(s); ${llmPinnedTools.length} eligible and pinned for ${target}\n`,
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
    // Dropped phases are recorded on the plan just like the deterministic
    // path does, so `plan.degradations` is accurate regardless of `useLLM`.
    const droppedPhases: string[] = []
    // Pinning helper shared with replan(): only tools that provide the
    // phase's capability are pinned — a named tool serving another capability
    // stays available to its own phase, never forced elsewhere.
    const capsOfInitial = (this.toolRegistry as Partial<ToolRegistry>).getCapabilities
    const toolsForInitial = (cap: Capability): string[] =>
      typeof capsOfInitial === "function"
        ? llmPinnedTools.filter((name) => (capsOfInitial.call(this.toolRegistry, name) as string[]).includes(cap))
        : []
    for (let i = 0; i < workflow.phases.length; i++) {
      const def = workflow.phases[i]
      // Pass the full gate context (tech, actual scheme, recon signals) so
      // the initial selection obeys the same activation gates the executor
      // re-checks immediately before running each tool.
      const tools = this.toolRegistry.selectBest(def.required_capabilities, targetType, gateContext, workflowCostFilter)

      if (tools.length === 0) {
        if (def.error_recovery !== "fail_fast") {
          droppedPhases.push(
            `${def.name} (no installed tool for ${def.required_capabilities.join(", ")})`,
          )
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

      const pinnedInitial = def.required_capabilities.flatMap((cap) => toolsForInitial(cap as Capability))
      phases.push({
        phaseId: `phase-${i}-${def.name}-${crypto.randomUUID().slice(0, 8)}`,
        name: def.name,
        workflowName: workflow.name,
        target,
        requiredCapabilities: def.required_capabilities,
        config: {
          pipelineSteps: pipeline?.steps,
          pipelineGaps: pipeline?.gaps,
          ...(pinnedInitial.length > 0 ? { preferredTools: pinnedInitial } : {}),
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
      ...(droppedPhases.length > 0 ? { degradations: droppedPhases } : {}),
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
    const capabilityProvenance = new Map<Capability, { source: "replan-rule" | "replan-llm" | "replan-chain"; by: string }>()
    if (!ruleBudgetExhausted) {
      const ruleCaps = determineNewCapabilities(context)
      for (const cap of ruleCaps) {
        newCapabilities.add(cap)
        capabilityProvenance.set(cap, { source: "replan-rule", by: "local-planner" })
      }
      // ── Chain-Plan-Driven Capabilities (rule-based, no LLM needed) ──
      // Attack-graph chains detected in prior phases already name the
      // capabilities their exploitation steps need. Feed those straight into
      // replanning so chain exploitation proceeds without an LLM call.
      if (context.chainPlans && context.chainPlans.length > 0) {
        for (const chain of context.chainPlans) {
          for (const raw of chain.suggested_capabilities ?? []) {
            const cap = guessCapability(raw)
            if (!cap) continue
            if (context.executedCapabilities.has(cap)) continue
            if (newCapabilities.has(cap)) continue
            newCapabilities.add(cap)
            capabilityProvenance.set(cap, { source: "replan-chain", by: "attack-graph" })
          }
        }
      }
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
          capabilityProvenance.set(cap, { source: "replan-llm", by: "worker-llm" })
          llmProducedPhases = true
        }
      }
    }

    // Source 2: OpenCode Session LLM (local) — runs alongside MCP path
    if (!llmBudgetExhausted && context.findings.length > 0) {
      try {
        const llmSvc = this.plannerLLM()
        // Ground the replan LLM in every tool eligible right now, so a
        // finding (e.g. GraphQL) maps to the specific scanner that handles
        // it instead of an abstract capability the registry resolves later.
        // The catalogue carries the full gate context — actual target scheme
        // and current recon signals — so the LLM never sees a tool whose
        // activation gates are unsatisfied in this context.
        const replanTargetType = detectTargetType(context.target)
        const replanGateContext = gateContextFor(context.target, context)
        const describeAll = (this.toolRegistry as Partial<ToolRegistry>).describeAllEligibleTools
        const replanCatalogue = typeof describeAll === "function"
          ? describeAll.call(this.toolRegistry, replanTargetType, replanGateContext)
          : undefined
        const llmReplan = await llmSvc.suggestReplan(context.target, context.findings, replanCatalogue)
        if (llmReplan && !llmReplan.stopAssessment) {
          for (const raw of llmReplan.nextCapabilities) {
            const cap = guessCapability(raw)
            if (cap !== undefined && !context.executedCapabilities.has(cap) && !newCapabilities.has(cap)) {
              newCapabilities.add(cap)
              capabilityProvenance.set(cap, { source: "replan-llm", by: "local-llm" })
              llmProducedPhases = true
            }
          }
          // The LLM may name specific eligible tools (next_tools). Keep only
          // ones that survive the full eligibility check — registered,
          // enabled, worker-runnable, target-type compatible, and with
          // activation gates (tech, scheme, recon signals, credentials)
          // satisfied in this context. An existing but ineligible tool is
          // dropped, never trusted: naming a tool can never bypass its gate.
          const validTools = validNamedTools(
            this.toolRegistry,
            llmReplan.nextTools,
            replanTargetType,
            replanGateContext,
          )
          if (validTools.length > 0) {
            context.preferredTools = [...(context.preferredTools ?? []), ...validTools]
            llmProducedPhases = true
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
    // A phase is a unit of work, so one capability gets one phase even when
    // several chains call for it: building `exploit-<chain>` per chain runs the
    // same capability twice and buys no new evidence. Chains whose capabilities
    // are already owned are folded into the owning phase's
    // `coalescedChainPlans`, so their context (description, risk, prerequisites)
    // survives without a duplicate phase.
    const chainPhases: PhaseExecutionRequest[] = []
    const chainPhaseByCapability = new Map<Capability, PhaseExecutionRequest>()
    if (context.chainPlans && context.chainPlans.length > 0) {
      const nextReplanCount = context.replanCount + 1
      for (const plan of context.chainPlans) {
        // Map chain suggested capabilities to actual registered capabilities.
        // Resolved through `guessCapability` — the same resolver the chain-plan
        // capability block above uses — so a chain's capability has one identity
        // in both places and deduplication below compares like with like. The
        // per-chain `Set` also stops one chain listing a capability twice.
        const caps = [
          ...new Set(
            plan.suggested_capabilities
              .map((c) => guessCapability(c) ?? (c as Capability))
              .filter((c) => !context.executedCapabilities.has(c)),
          ),
        ]

        if (caps.length === 0) continue

        const unclaimedCaps = caps.filter((cap) => !chainPhaseByCapability.has(cap))
        if (unclaimedCaps.length === 0) {
          // Every capability is already owned by an earlier chain's phase.
          // Keep this chain's context, drop the duplicate phase.
          for (const cap of caps) {
            const owner = chainPhaseByCapability.get(cap)!
            const coalesced =
              (owner.config.coalescedChainPlans as ChainPhasePlan[] | undefined) ?? []
            if (!coalesced.some((coalescedPlan) => coalescedPlan.chain_id === plan.chain_id)) {
              owner.config.coalescedChainPlans = [...coalesced, plan]
            }
          }
          continue
        }

        const phase: PhaseExecutionRequest = {
          phaseId: `chain-${nextReplanCount}-${plan.chain_id}-${crypto.randomUUID().slice(0, 8)}`,
          name: `exploit-${plan.chain_id}`,
          workflowName: "chain_exploitation",
          target: context.target,
          requiredCapabilities: unclaimedCaps,
          config: {
            chainPlan: plan,
            chainDescription: plan.description,
            replan: {
              source: "replan-chain",
              reason: plan.description || `Attack graph correlated ${unclaimedCaps.join(", ")} into an exploitation phase`,
              by: "worker-attack-graph",
            },
          },
          previousPhaseResults: [],
          toolExecution: "sequential",
          replanCycle: true,
        }
        chainPhases.push(phase)
        for (const cap of unclaimedCaps) {
          chainPhaseByCapability.set(cap, phase)
        }
      }
    }

    // A chain capability must yield exactly ONE phase. The attack-chain block
    // above already builds the `exploit-<chain>` phase that carries the chain
    // plan (description, risk, context), so the same capability must not also
    // become a `replan-<cap>` phase — that queued two phases for one capability
    // and ran it twice.
    const chainedCapabilities = new Set(
      chainPhases.flatMap((phase) => phase.requiredCapabilities),
    )

    // Combine regular replan phases with chain exploitation phases
    const nextReplanCount = context.replanCount + 1
    // Tools the replan LLM picked by name, pinned so the executor tries them
    // before the capability-default ordering. Only tools that provide the
    // phase's capability are pinned — a named tool that serves another
    // capability stays available to its own phase, never forced elsewhere.
    const preferredTools = context.preferredTools ?? []
    const capsOf = (this.toolRegistry as Partial<ToolRegistry>).getCapabilities
    const toolsFor = (cap: Capability): string[] =>
      typeof capsOf === "function"
        ? preferredTools.filter((name) => (capsOf.call(this.toolRegistry, name) as string[]).includes(cap))
        : []
    const regularPhases = unhandled.filter((cap) => !chainedCapabilities.has(cap)).map((cap) => {
      const provenance = capabilityProvenance.get(cap) ?? {
        source: llmProducedPhases ? ("replan-llm" as const) : ("replan-rule" as const),
        by: llmProducedPhases ? "worker-llm" : "local-planner",
      }
      const pinned = toolsFor(cap)
      return {
        phaseId: `replan-${nextReplanCount}-${cap}`,
        name: `replan-${cap.toLowerCase()}`,
        workflowName: "replan",
        target: context.target,
        requiredCapabilities: [cap],
        config: {
          replan: {
            ...provenance,
            reason:
              provenance.source === "replan-rule"
                ? `Rule-based replan for newly observed ${cap}`
                : `Model suggested ${cap} after ${context.findings.length} accumulated finding(s)`,
          },
          ...(pinned.length > 0 ? { preferredTools: pinned } : {}),
        },
        previousPhaseResults: [],
        toolExecution: "sequential" as const,
        replanCycle: true,
      }
    })

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

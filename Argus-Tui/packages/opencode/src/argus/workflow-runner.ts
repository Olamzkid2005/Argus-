/**
 * ArgusWorkflowRunner — Runs assessment workflows through the planner/executor.
 *
 * This is the single entry point for all assessment executions, whether
 * triggered by /assess, natural language detection, CLI, or API.
 *
 * Supports progress streaming via onProgress callback for live TUI updates.
 * Engagement creation happens here, not in the caller.
 */

import { WorkflowRegistry } from "./workflows/registry"
import { ToolRegistry } from "./workflows/tool-registry"
import { WorkflowPlanner } from "./planner/planner"
import { InProcessExecutor } from "./planner/executor"
import { WorkersBridge } from "./bridge/mcp-client"
import { EngagementStore } from "./engagement/store"
import type { IEngagementStore } from "./engagement/types"
import { CredentialStore, type CredentialEntry } from "./engagement/credentials"
import { ConfidenceEngine } from "./engagement/confidence"
import { FeatureFlags, Feature } from "./config/feature-flags"
import { detectTargetType, detectAuthState } from "./planner/strategy"
import { join, resolve } from "path"
import { Capability } from "./planner/capabilities"
import type { NormalizedFinding, VerificationResult } from "./shared/types"
import { Severity } from "./shared/types"
import type { PhaseRecord } from "./engagement/types"
import { VerificationRunner } from "./browser/verifiers/runner"
import { PlaywrightEngine } from "./browser/engine"
import { StoredXSSVerifier } from "./browser/verifiers/xss"
import { BOLAVerifier } from "./browser/verifiers/bola"
import { PrivilegeEscalationVerifier } from "./browser/verifiers/priv-esc"
import type { ProgressEvent } from "./shared/progress"
import type { PlannerContext } from "./planner/types"
import { handleProgressEvent } from "./tui/scan-store"
import type { CacheMode } from "./bridge/types"
import { PROJECT_ROOT, MCP_WORKER_PATH } from "./shared/path"
import { getTargetValidator } from "./shared/target-validator"

export interface WorkflowRunOptions {
  target: string
  useLLM?: boolean
  workersPath?: string
  workflowsDir?: string
  /**
   * Cache execution mode.
   * - "normal": read cache, write cache (default)
   * - "no_cache": skip cache reads AND writes
   * - "refresh": skip cache reads, still write results
   */
  cacheMode?: CacheMode
  /**
   * Called with status updates during assessment execution.
   * Accepts both structured ProgressEvent objects and plain strings
   * for backward compatibility.
   */
  onProgress?: (event: ProgressEvent | string) => void
  /**
   * Existing engagement ID to use instead of creating a new one.
   * The caller is responsible for creating the engagement and passing
   * the ID here. If omitted, a new engagement is created automatically.
   */
  engagementId?: string
  /**
   * Path to credentials JSON file to load for authenticated testing.
   */
  credsPath?: string
  /**
   * Feature flag overrides.
   */
  features?: Partial<Record<Feature, boolean>>
  /**
   * Enable verbose logging in the executor.
   * When true, the executor will emit additional detail about tool execution,
   * timing, and phase transitions via console.log.
   */
  verbose?: boolean
}

export interface WorkflowRunResult {
  engagementId: string
  findings: number
  critical: number
  high: number
  medium: number
  low: number
  info: number
  durationMs: number
  success: boolean
  error?: string
  /** All findings with promoted confidence, for rendering summaries */
  allFindings: NormalizedFinding[]
}

/**
 * Format a findings summary string from raw findings.
 * Used by both TUI and CLI output.
 */
export function formatFindingsSummary(
  allFindings: WorkflowRunResult["allFindings"],
  engagementId: string,
  target: string,
): string {
  const critical = allFindings.filter((f) => f.severity >= 4)
  const high = allFindings.filter((f) => f.severity === 3)
  const medium = allFindings.filter((f) => f.severity === 2)
  const low = allFindings.filter((f) => f.severity === 1)
  const info = allFindings.filter((f) => f.severity === 0)

  const lines: string[] = [
    `**Assessment Complete: ${target}**`,
    `Engagement: \`${engagementId}\``,
    "",
    "**Summary**",
    `  Critical: ${critical.length}`,
    `  High:     ${high.length}`,
    `  Medium:   ${medium.length}`,
    `  Low:      ${low.length}`,
  ]

  if (info.length > 0) {
    lines.push(`  Info:     ${info.length}`)
  }

  // Top findings by severity
  const topFindings = [...critical, ...high, ...medium].slice(0, 5)
  if (topFindings.length > 0) {
    lines.push("", "**Top Findings**")
    for (const f of topFindings) {
      const sevLabel = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][f.severity] ?? "UNKNOWN"
      const confLabel = ["INFO", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"][f.confidence] ?? "UNKNOWN"
      lines.push(`  [${sevLabel}] ${f.title} (${confLabel})`)
    }
  }

  lines.push("", `Run \`/report ${engagementId}\` for the full report.`)
  return lines.join("\n")
}

export class WorkflowRunner {
  constructor(
    private deps?: {
      store?: IEngagementStore
      workflowRegistry?: WorkflowRegistry
      toolRegistry?: ToolRegistry
      planner?: WorkflowPlanner
      executor?: InProcessExecutor
      bridge?: WorkersBridge
      confidenceEngine?: ConfidenceEngine
      credStore?: CredentialStore
    },
  ) {}

  /**
   * Autonomously verify HIGH/CRITICAL findings using browser-based verifiers.
   * Returns findings annotated with verificationResult for any that passed.
   */
  private async verifyFindings(
    findings: NormalizedFinding[],
    target: string,
    creds: CredentialEntry | null | undefined,
    engagementId: string,
    emit: (event: ProgressEvent | string) => void,
  ): Promise<NormalizedFinding[]> {
    if (!creds) return findings

    const toVerify = findings.filter(
      (f) => (f.severity === Severity.HIGH || f.severity === Severity.CRITICAL) && !f.verificationResult,
    )
    if (toVerify.length === 0) return findings

    const runner = new VerificationRunner()
    const engine = new PlaywrightEngine()
    const updated: NormalizedFinding[] = []

    for (const finding of findings) {
      if (!toVerify.includes(finding)) {
        updated.push(finding)
        continue
      }

      let scenario
      try {
        switch (finding.subtype) {
          case "xss":
          case "xss_stored":
          case "xss_reflected": {
            const injectUrl = finding.statusCode ? target : `${target}/contact`
            scenario = new StoredXSSVerifier(
              engine,
              injectUrl,
              injectUrl,
              finding.description.includes("<script>") ? finding.description : "<img src=x onerror=alert(1)>",
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          case "bola":
          case "idor": {
            const resourcePath = finding.description.match(/(\/[^\s]+)/)?.[1] ?? "profile"
            scenario = new BOLAVerifier(
              engine,
              target,
              resourcePath,
              creds,
              { username: `${creds.username}_b`, password: creds.password },
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          case "privilege_escalation":
          case "privesc": {
            const endpoints = finding.description.match(/(\/[^\s,]+)/g) ?? ["/admin"]
            scenario = new PrivilegeEscalationVerifier(
              engine,
              target,
              endpoints.slice(0, 5),
              creds,
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          default:
            updated.push(finding)
            continue
        }

        emit(`⠋ Verifying ${finding.subtype} finding: ${finding.title}`)
        const result = await runner.run(scenario)
        const verificationResult: VerificationResult = {
          passed: result.passed,
          summary: result.summary,
          verifier: scenario.name,
          verifiedAt: new Date().toISOString(),
        }
        updated.push({ ...finding, verificationResult })
        emit(`✓ Verification ${result.passed ? "passed" : "failed"} for ${finding.title}`)
      } catch (error) {
        updated.push(finding)
        emit(`⚠ Verification error for ${finding.title}: ${(error as Error).message}`)
      }
    }

    try {
      await engine.close()
    } catch {
      // best-effort cleanup
    }

    return updated
  }

  /**
   * Run an assessment workflow against a target.
   * Creates an engagement, plans phases, executes them, and returns results.
   * Calls onProgress() with status updates for live TUI feedback.
   */
  async run(options: WorkflowRunOptions): Promise<WorkflowRunResult> {
    const startTime = Date.now()
    const target = options.target
    const userEmit = options.onProgress
    const emit = (event: ProgressEvent | string) => {
      userEmit?.(event)
      if (typeof event !== "string") handleProgressEvent(event, engagementId)
    }

    // ── Target scope validation (hard guardrail) ──
    const validator = getTargetValidator()
    const validationResult = await validator.validateTarget(target)
    if (!validationResult.valid) {
      throw new Error(validationResult.message)
    }
    if (!validationResult.dnsReachable) {
      emit(`⚠ Target DNS resolution failed for ${target} — target may be unreachable`)
    }
    emit(`✓ Target validated: ${target}`)

    // ── Target confirmation (soft guardrail, Task 4.1) ──
    // When security.scope.require_confirmation is true and the target is not
    // in the allowed list, prompt the user for confirmation before proceeding.
    // Respects ARGUS_AUTO_APPROVE=1 (auto-approves). Non-TTY auto-approves.
    if (validator.requiresConfirmation(target)) {
      if (process.env.ARGUS_AUTO_APPROVE === "1") {
        emit(`✓ Target confirmation auto-approved (ARGUS_AUTO_APPROVE=1)`)
      } else if (!process.stdout.isTTY) {
        emit(`✓ Target auto-confirmed (non-TTY)`)
      } else {
        process.stderr.write(`\n⚠  Target Confirmation Required\n`)
        process.stderr.write(`   Target: ${target}\n`)
        process.stderr.write(`   This target is not in the allowed targets list.\n`)
        process.stderr.write(`   Proceed? [y/N] `)

        const confirmed = await new Promise<boolean>((resolve) => {
          const stdin = process.stdin
          stdin.resume()
          const done = (result: boolean) => {
            stdin.pause()
            stdin.removeAllListeners("data")
            clearTimeout(timer)
            resolve(result)
          }
          stdin.once("data", (data: Buffer) => {
            const input = data.toString().trim().toLowerCase()
            process.stderr.write("\n")
            done(input === "y" || input === "yes")
          })
          const timer = setTimeout(() => {
            process.stderr.write("\n   Confirmation timed out.\n\n")
            done(false)
          }, 30000)
        })

        if (!confirmed) {
          throw new Error(`Target "${target}" not confirmed by user.`)
        }
        emit(`✓ Target confirmed by user`)
      }
    }

    // Paths resolved from the central project-root helper (shared/path.ts)
    const workersPath = options.workersPath ?? MCP_WORKER_PATH
    const workflowsDir = options.workflowsDir ?? resolve(PROJECT_ROOT, "Argus-Tui/packages/opencode/src/argus/workflows")
    const toolsPath = join(workflowsDir, "tool-definitions.yaml")

    // ── 1. Create or use existing engagement ──
    const store = this.deps?.store ?? new EngagementStore()
    let engagementId = options.engagementId
    if (engagementId) {
      // Verify the engagement exists
      const existing = store.getEngagement(engagementId)
      if (!existing) {
        throw new Error(`Engagement ${engagementId} not found in store`)
      }
      store.updateStatus(engagementId, "RUNNING")
      emit(`✓ Using existing engagement: \`${engagementId}\``)
    } else {
      const engagement = store.createEngagement(target, "assessment")
      engagementId = engagement.id
      store.updateStatus(engagementId, "RUNNING")
      emit(`✓ Engagement created: \`${engagementId}\``)
    }

    // ── 2. Load credentials, feature flags & replan config ──
    const featureFlags = new FeatureFlags(options.features)
    let configMaxReplans: number | undefined
    try {
      const { readFileSync } = await import("fs")
      const { parse: YAML } = await import("yaml")
      const configPath = join(process.cwd(), "argus.config.yaml")
      const raw = readFileSync(configPath, "utf-8")
      const parsed = YAML(raw) as { features?: Record<string, boolean>; replan?: { max_cycles?: number } } | undefined
      if (parsed?.features) {
        featureFlags.loadFromConfig(parsed.features)
      }
      configMaxReplans = parsed?.replan?.max_cycles
    } catch {
      console.warn("Config file missing or invalid, using defaults")
      /* config file missing or invalid — use defaults */
    }
    featureFlags.loadFromEnv()

    const credStore = this.deps?.credStore ?? new CredentialStore()
    const creds = options.credsPath ? credStore.load(options.credsPath) : credStore.load()
    const defaultCreds = credStore.getDefaultCredentials()
    if (defaultCreds) {
      store.appendAuditLog(engagementId, "CREDS_LOADED", `Loaded credentials for roles: ${credStore.listRoles().join(", ")}`)
      credStore.clear()
    }

    // ── 3. Load registries ──
    const workflowRegistry = this.deps?.workflowRegistry ?? new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = this.deps?.toolRegistry ?? new ToolRegistry()
    toolRegistry.load(toolsPath)

    // ── 4. Plan ──
    emit(`⠋ Planning assessment...`)
    const planner = this.deps?.planner ?? new WorkflowPlanner(workflowRegistry, toolRegistry)
    // Determine whether to use LLM: explicit option > DETERMINISTIC_FALLBACK flag > default (true)
    // When DETERMINISTIC_FALLBACK is enabled, default to deterministic mode (no LLM),
    // but an explicit useLLM option still takes precedence.
    const useLLM = options.useLLM !== undefined
      ? options.useLLM
      : !featureFlags.isEnabled(Feature.DETERMINISTIC_FALLBACK)
    const plan = await planner.plan(target, defaultCreds ? { authState: "basic" } : undefined, { useLLM })
    emit(`✓ Plan created: ${plan.phases.length} phase(s)`)
    if (defaultCreds) {
      for (const phase of plan.phases) {
        phase.config.credentials = defaultCreds
      }
    }

    // ── 5. Create phase records ──
    const phaseRecords = new Map<string, PhaseRecord>()
    for (const p of plan.phases) {
      const record: PhaseRecord = {
        id: p.phaseId,
        engagementId,
        name: p.name,
        status: "PENDING",
        capabilities: p.requiredCapabilities,
        executionMode: p.toolExecution ?? "sequential",
        replanCycle: p.replanCycle ?? false,
      }
      phaseRecords.set(p.phaseId, record)
    }
    store.savePhases(engagementId, Array.from(phaseRecords.values()))

    // ── 5. Connect bridge & execute ──
    const allFindings: NormalizedFinding[] = []
    let executionError: Error | null = null
    const bridge = this.deps?.bridge ?? new WorkersBridge(workersPath)

    try {
      emit(`⠋ Connecting MCP workers...`)
      await bridge.connect()
      emit(`✓ MCP workers connected`)

      const confidenceEngine = this.deps?.confidenceEngine ?? new ConfidenceEngine()
      const executor = this.deps?.executor ?? new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)
      // Wire up tool config for drift detection, circuit-breaker config, and tool enable/disable
      const { ToolConfig } = await import("./config/tool-config")
      const toolConfig = await ToolConfig.load()
      toolRegistry.setConfig(toolConfig)
      executor.setToolConfig(toolConfig)
      // Seed the bridge's tool cache with the local registry for drift comparison
      // Cast is safe: setRegistryTools only introspects .name and .capabilities, both present on ToolDef
      bridge.setRegistryTools(toolRegistry.listTools() as unknown as import("./bridge/types").ToolDefinition[])
      executor.setFeatureFlags(featureFlags)
      executor.loadGates(plan.workflow)
      executor.setOnProgress((event) => { if (typeof event !== "string") emit(event) })
      executor.setExecutionOptions({
        ...(options.cacheMode ? { cacheMode: options.cacheMode } : {}),
        ...(options.verbose ? { verbose: options.verbose } : {}),
      })
      const executedCapabilities = new Set<Capability>()
      const insertedPhaseIds = new Set<string>()
      const allHypotheses: Array<{ id: string; description: string; confidence: number; status: string }> = []
      let replanCount = 0
      const targetType = detectTargetType(target)
      const authState = detectAuthState(target)

      let i = 0
      while (i < plan.phases.length) {
        const phase = plan.phases[i]
        const phaseName = phase.name

        emit({ type: "phase_start", phaseId: phase.phaseId, name: phaseName, total: plan.phases.length, phaseIndex: i })
        emit(`⠋ Running phase ${i + 1}/${plan.phases.length}: ${phaseName}`)

        const record = phaseRecords.get(phase.phaseId)!
        record.status = "RUNNING"
        record.startedAt = new Date().toISOString()
        store.savePhase(engagementId, record)

        const result = await executor.execute(phase)

        let phaseFindings = result.findings
        if (phaseFindings.length > 0) {
          phaseFindings = await this.verifyFindings(phaseFindings, target, defaultCreds, engagementId, emit)
        }

        for (const finding of phaseFindings) {
          emit({ type: "finding", phaseId: phase.phaseId, severity: String(finding.severity), title: finding.title })
          const promoted = confidenceEngine.promote(finding)
          allFindings.push({ ...finding, confidence: promoted })
        }

        const phaseStatus = result.status === "failed" ? "FAILED" : result.status === "partial" ? "PARTIAL" : result.status === "skipped" ? "SKIPPED" : "COMPLETED"
        const finalRecord = phaseRecords.get(phase.phaseId)!
        finalRecord.status = phaseStatus
        finalRecord.completedAt = new Date().toISOString()
        if (result.errors.length > 0) finalRecord.error = result.errors.join("; ")
        store.savePhase(engagementId, finalRecord)

        const findingCount = phaseFindings.length
        const errorCount = result.errors.length
        if (phaseStatus === "FAILED") {
          emit({ type: "phase_error", phaseId: phase.phaseId, name: phaseName, error: result.errors.join("; ") })
          emit(`⚠ Phase ${phaseName}: ${findingCount} finding(s), ${errorCount} error(s)`)
        } else if (phaseStatus === "PARTIAL") {
          emit({ type: "phase_complete", phaseId: phase.phaseId, name: phaseName, findings: findingCount, status: phaseStatus })
          emit({ type: "phase_error", phaseId: phase.phaseId, name: phaseName, error: result.errors.join("; ") })
          emit(`⚠ Phase ${phaseName}: ${findingCount} finding(s), ${errorCount} error(s)`)
        } else {
          emit({ type: "phase_complete", phaseId: phase.phaseId, name: phaseName, findings: findingCount, status: phaseStatus })
          emit(`✓ Phase ${phaseName}: ${findingCount} finding(s)`)
        }

        for (const cap of phase.requiredCapabilities) {
          executedCapabilities.add(cap)
        }
        insertedPhaseIds.add(phase.phaseId)

        // Accumulate hypotheses from hybrid phases for replan decisions
        if (result.hypotheses && result.hypotheses.length > 0) {
          for (const h of result.hypotheses) {
            if (!allHypotheses.some((existing) => existing.id === h.id)) {
              allHypotheses.push(h)
            }
          }
        }

        if (!phase.replanCycle) {
          const replanCtx: PlannerContext = {
            target,
            targetType,
            authState,
            findings: allFindings,
            executedCapabilities,
            insertedPhases: insertedPhaseIds,
            replanCount,
            maxReplans: configMaxReplans,
            hypotheses: allHypotheses.length > 0 ? allHypotheses : undefined,
          }
          const replanPhases = planner.replan(replanCtx)
          replanCount = replanCtx.replanCount

          if (replanPhases && replanPhases.length > 0) {
            emit(`⠋ Replanning: ${replanPhases.length} new phase(s) from accumulated findings`)
            store.appendAuditLog(engagementId, "REPLAN_INSERT",
              `Inserting ${replanPhases.length} replan phase(s) at position ${i + 1}`)

            let insertOffset = 0
            for (const rp of replanPhases) {
              if (defaultCreds) {
                rp.config.credentials = defaultCreds
              }
              for (const cap of rp.requiredCapabilities) {
                executedCapabilities.add(cap)
              }
              plan.phases.splice(i + 1 + insertOffset, 0, rp)
              insertOffset++
              plan.errorRecovery[rp.phaseId] = "retry_once_then_skip"
              phaseRecords.set(rp.phaseId, {
                id: rp.phaseId,
                engagementId,
                name: rp.name,
                status: "PENDING",
                capabilities: rp.requiredCapabilities,
                executionMode: rp.toolExecution ?? "sequential",
                replanCycle: true,
              })
            }
            store.savePhases(engagementId, Array.from(phaseRecords.values()))
            emit({ type: "phase_replan", count: replanPhases.length })
          }
        }

        i++
      }
    } catch (error) {
      executionError = error as Error
      emit({ type: "scan_complete", totalFindings: allFindings.length })
      emit(`✗ Error: ${executionError.message}`)
      store.appendAuditLog(engagementId, "RUNNER_ERROR",
        `Workflow error: ${executionError.message}`)
    } finally {
      const allCompleted = Array.from(phaseRecords.values()).every((p) => p.status === "COMPLETED" || p.status === "PARTIAL")
      store.updateStatus(engagementId, executionError ? "FAILED" : allCompleted ? "COMPLETED" : "PAUSED")
      store.saveFindings(engagementId, allFindings)
      await bridge.disconnect()
      if (!executionError) {
        emit({ type: "scan_complete", totalFindings: allFindings.length })
      }
      emit(`✓ Assessment ${executionError ? "failed" : "complete"}`)
    }

    // ── 8. Collate and return results ──
    return {
      engagementId,
      findings: allFindings.length,
      critical: allFindings.filter((f) => f.severity >= 4).length,
      high: allFindings.filter((f) => f.severity === 3).length,
      medium: allFindings.filter((f) => f.severity === 2).length,
      low: allFindings.filter((f) => f.severity === 1).length,
      info: allFindings.filter((f) => f.severity === 0).length,
      durationMs: Date.now() - startTime,
      success: !executionError,
      error: executionError?.message,
      allFindings,
    }
  }
}

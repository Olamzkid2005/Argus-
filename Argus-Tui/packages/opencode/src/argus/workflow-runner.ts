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
import { CredentialStore } from "./engagement/credentials"
import { ConfidenceEngine } from "./engagement/confidence"
import { FeatureFlags, Feature } from "./config/feature-flags"
import { detectTargetType, detectAuthState } from "./planner/strategy"
import { join } from "path"
import { Capability } from "./planner/capabilities"
import type { NormalizedFinding } from "./shared/types"
import type { PhaseRecord } from "./engagement/types"
import type { ProgressEvent } from "./shared/progress"
import type { PlannerContext } from "./planner/types"
import { handleProgressEvent } from "./tui/scan-store"
import type { CacheMode } from "./bridge/types"

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
      store?: EngagementStore
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

    emit(`✓ Target validated: ${target}`)

    // Resolve paths relative to this file (src/argus/workflow-runner.ts)
    // File location:  Argus-Tui/packages/opencode/src/argus/workflow-runner.ts
    // Project root:   Argus Cli/  (parent of Argus-Tui/ and argus-workers/)
    // From src/argus/ to project root: 5 levels up
    // Use decodeURIComponent to handle spaces in path (e.g. "Argus Cli" → "Argus%20Cli" in file:// URL)
    const _dirname = decodeURIComponent(new URL(".", import.meta.url).pathname)

    const workersPath = options.workersPath ?? join(_dirname, "../../../../../argus-workers/mcp_server.py")
    const workflowsDir = options.workflowsDir ?? join(_dirname, "./workflows")
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
    } catch { /* config file missing or invalid — use defaults */ }
    featureFlags.loadFromEnv()

    const credStore = this.deps?.credStore ?? new CredentialStore()
    const creds = options.credsPath ? credStore.load(options.credsPath) : credStore.load()
    const defaultCreds = credStore.getDefaultCredentials()
    if (defaultCreds) {
      store.appendAuditLog(engagementId, "CREDS_LOADED", `Loaded credentials for roles: ${credStore.listRoles().join(", ")}`)
    }
    credStore.clear()

    // ── 3. Load registries ──
    const workflowRegistry = this.deps?.workflowRegistry ?? new WorkflowRegistry(workflowsDir)
    workflowRegistry.loadAll()
    const toolRegistry = this.deps?.toolRegistry ?? new ToolRegistry()
    toolRegistry.load(toolsPath)

    // ── 4. Plan ──
    emit(`⠋ Planning assessment...`)
    const planner = this.deps?.planner ?? new WorkflowPlanner(workflowRegistry, toolRegistry)
    const plan = await planner.plan(target, defaultCreds ? { authState: "basic" } : undefined, { useLLM: options.useLLM ?? true })
    emit(`✓ Plan created: ${plan.phases.length} phase(s)`)
    if (defaultCreds) {
      for (const phase of plan.phases) {
        phase.config.credentials = defaultCreds
      }
    }

    // ── 5. Create phase records ──
    const phaseRecords: PhaseRecord[] = plan.phases.map((p, i) => ({
      id: p.phaseId,
      engagementId,
      name: p.name,
      status: "PENDING" as const,
      capabilities: p.requiredCapabilities,
      executionMode: p.toolExecution ?? "sequential",
      replanCycle: p.replanCycle ?? false,
    })) as unknown as PhaseRecord[]
    store.savePhases(engagementId, phaseRecords)

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
      if (options.cacheMode) {
        executor.setExecutionOptions({ cacheMode: options.cacheMode })
      }
      const executedCapabilities = new Set<Capability>()
      const insertedPhaseIds = new Set<string>()
      let replanCount = 0
      const targetType = detectTargetType(target)
      const authState = detectAuthState(target)

      let i = 0
      while (i < plan.phases.length) {
        const phase = plan.phases[i]
        const phaseName = phase.name

        emit({ type: "phase_start", phaseId: phase.phaseId, name: phaseName, total: plan.phases.length, phaseIndex: i })
        emit(`⠋ Running phase ${i + 1}/${plan.phases.length}: ${phaseName}`)

        phaseRecords[i].status = "RUNNING"
        phaseRecords[i].startedAt = new Date().toISOString()
        store.savePhase(engagementId, phaseRecords[i])

        const result = await executor.execute(phase)

        for (const finding of result.findings) {
          emit({ type: "finding", phaseId: phase.phaseId, severity: String(finding.severity), title: finding.title })
          const promoted = confidenceEngine.promote(finding)
          allFindings.push({ ...finding, confidence: promoted })
        }

        const phaseStatus = result.status === "failed" ? "FAILED" : result.status === "partial" ? "PARTIAL" : result.status === "skipped" ? "SKIPPED" : "COMPLETED"
        phaseRecords[i].status = phaseStatus
        phaseRecords[i].completedAt = new Date().toISOString()
        if (result.errors.length > 0) phaseRecords[i].error = result.errors.join("; ")
        store.savePhase(engagementId, phaseRecords[i])

        const findingCount = result.findings.length
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
          }
          const replanPhases = planner.replan(replanCtx)
          replanCount = replanCtx.replanCount

          if (replanPhases && replanPhases.length > 0) {
            emit(`⠋ Replanning: ${replanPhases.length} new phase(s) from accumulated findings`)
            store.appendAuditLog(engagementId, "REPLAN_INSERT",
              `Inserting ${replanPhases.length} replan phase(s) at position ${i + 1}`)

            for (const rp of replanPhases) {
              if (defaultCreds) {
                rp.config.credentials = defaultCreds
              }
              for (const cap of rp.requiredCapabilities) {
                executedCapabilities.add(cap)
              }
              plan.phases.push(rp)
              plan.errorRecovery[rp.phaseId] = "retry_once_then_skip"
              phaseRecords.push({
                id: rp.phaseId,
                engagementId,
                name: rp.name,
                status: "PENDING" as const,
                capabilities: rp.requiredCapabilities,
                executionMode: rp.toolExecution ?? "sequential",
                replanCycle: true,
              })
            }
            store.savePhases(engagementId, phaseRecords)
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
      const allCompleted = phaseRecords.every((p) => p.status === "COMPLETED" || p.status === "PARTIAL")
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

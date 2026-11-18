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
import { mergeFinding } from "./engagement/finding-identity"
import { FeatureFlags, Feature } from "./config/feature-flags"
import { detectTargetType, detectAuthState } from "./planner/strategy"
import { join, resolve } from "path"
import { Capability, guessCapability } from "./planner/capabilities"
import type { NormalizedFinding, VerificationResult, EvidencePackage } from "./shared/types"
import { ProofStatus, Severity } from "./shared/types"
import type { PhaseRecord } from "./engagement/types"
import {
  buildCheckpoint,
  type CheckpointActionProvenance,
  type CheckpointBudgetUsage,
  type CheckpointProvenanceAction,
  type CheckpointWorkerBudget,
} from "./engagement/checkpoint"
import type { WorkerBudgetStatus } from "./bridge/mcp-client"
import { VerificationRunner } from "./browser/verifiers/runner"
import { PlaywrightEngine } from "./browser/engine"
import { scopeEntriesFor } from "./browser/scope-guard"
import { verificationResultFrom } from "./browser/proof"
import { StoredXSSVerifier } from "./browser/verifiers/xss"
import { XssProbeError } from "./browser/verifiers/xss-probe"
import { XssPlanError, xssInjectionPointForFinding } from "./browser/verifiers/xss-plan"
import type { XssDiscovery } from "./browser/verifiers/xss-plan"
import { BOLAVerifier } from "./browser/verifiers/bola"
import {
  ObjectAccessPlanError,
  discoveredResourceForFinding,
  objectAccessPlan,
} from "./browser/bola-plan"
import { PrivilegeEscalationVerifier } from "./browser/verifiers/priv-esc"
import { SSRFVerifier } from "./browser/verifiers/ssrf"
import { LFIVerifier } from "./browser/verifiers/lfi"
import { JWTVerifier } from "./browser/verifiers/jwt"
import { SecretsExposureVerifier } from "./browser/verifiers/secrets"
import type { ProgressEvent } from "./shared/progress"
import type { PlannerContext } from "./planner/types"
import { handleProgressEvent } from "./tui/scan-store"
import type { CacheMode } from "./bridge/types"
import { PROJECT_ROOT, MCP_WORKER_PATH } from "./shared/path"
import { getTargetValidator } from "./shared/target-validator"

interface PlannedPhaseProvenance {
  source: CheckpointActionProvenance["source"]
  reason: string
  by: string
}

type CheckpointActionDetail = NonNullable<Parameters<typeof buildCheckpoint>[0]["actionDetails"]>[string]

type BudgetStatusBridge = Pick<WorkersBridge, "budgetStatus">

/** Normalize a planned or replanned phase into its checkpoint authorship record. */
function plannedPhaseProvenance(
  phase: import("./planner/types").PhaseExecutionRequest,
  kind: "plan" | "replan",
): PlannedPhaseProvenance {
  if (kind === "plan") {
    const capabilities = phase.requiredCapabilities.join(", ") || "no capabilities"
    return {
      source: "plan",
      reason: `Approved ${phase.name} with ${capabilities}`,
      by: "local-operator",
    }
  }
  const replan = phase.config.replan as Partial<PlannedPhaseProvenance> | undefined
  if (
    replan &&
    (replan.source === "replan-rule" || replan.source === "replan-llm" || replan.source === "replan-chain") &&
    typeof replan.reason === "string" &&
    replan.reason.length > 0 &&
    typeof replan.by === "string" &&
    replan.by.length > 0
  ) {
    return { source: replan.source, reason: replan.reason, by: replan.by }
  }
  return {
    source: "replan-rule",
    reason: `Rule-based replan for ${phase.name}`,
    by: "local-planner",
  }
}

/** Combine planned authorship with the phase's tool-level execution records. */
function actionDetailForPhase(
  planned: PlannedPhaseProvenance,
  status: string,
  actions: Array<{
    tool: string
    outcome: string
    reasoning?: string
    identity?: string
    source: CheckpointProvenanceAction["source"]
    detail?: string
  }> = [],
): CheckpointActionDetail {
  return {
    reason: `${planned.reason}; phase ${status.toLowerCase()}`,
    source: planned.source,
    by: planned.by,
    provenance: {
      source: planned.source,
      reason: planned.reason,
      by: planned.by,
      actions: actions.map((action) => ({
        tool: action.tool,
        outcome: action.outcome,
        reasoning: action.reasoning,
        identity: action.identity,
        source: action.source,
        detail: action.detail,
      })),
    },
  }
}

/** Read the authoritative worker ledger without letting ledger outages fail the run. */
async function workerBudgetFor(
  bridge: BudgetStatusBridge | undefined,
  engagementId: string,
): Promise<CheckpointWorkerBudget | undefined> {
  if (!bridge || typeof bridge.budgetStatus !== "function") return undefined
  try {
    const status: WorkerBudgetStatus = await bridge.budgetStatus(engagementId)
    return {
      toolCalls: status.toolCalls,
      executedTools: [...status.executedTools],
      identities: [...status.identities],
      sessions: status.sessions,
    }
  } catch {
    return undefined
  }
}

/**
 * Persist one restart checkpoint (Stage 6.2). Storage failures are raised, not
 * swallowed: a run whose checkpoint could not be written must not report that
 * it is resumable. Test doubles without checkpoint support are skipped only
 * because the concrete store always implements it. The worker ledger is
 * best-effort: it enriches reconciliation when available but never blocks
 * checkpoint persistence.
 */
async function saveRunCheckpoint(params: {
  store: IEngagementStore
  engagement: ReturnType<IEngagementStore["getEngagement"]> & object
  bridge?: BudgetStatusBridge
  plan: import("./planner/types").AssessmentPlan
  phases: PhaseRecord[]
  target: string
  roles: string[]
  findings: NormalizedFinding[]
  toolCalls: number
  startedAt: string
  completedAt?: string
  limits?: Record<string, number | string | null>
  actionDetails?: Record<string, CheckpointActionDetail>
}): Promise<void> {
  const store = params.store as IEngagementStore & {
    saveCheckpoint?: (checkpoint: ReturnType<typeof buildCheckpoint>) => void
  }
  if (typeof store.saveCheckpoint !== "function") return

  const proofStatus: Record<string, string> = {}
  for (const finding of params.findings) {
    proofStatus[finding.id] = finding.verificationResult?.proofStatus ?? "suspected"
  }

  const engagementId = (params.engagement as { id?: unknown }).id
  const workerBudget = typeof engagementId === "string"
    ? await workerBudgetFor(params.bridge, engagementId)
    : undefined
  const workerIdentities = (workerBudget?.identities ?? []).map((identity) => `worker:${identity}`)
  const authIdentities = [...new Set([
    ...params.roles.map((role) => `credential:${role}`),
    ...workerIdentities,
  ])].sort()

  const budgetUsage: CheckpointBudgetUsage = {
    deadlineAt: process.env.ARGUS_DEADLINE_AT,
    llmCalls: 0,
    llmFailures: 0,
    inputTokens: 0,
    outputTokens: 0,
    costUsd: 0,
    // The worker's cumulative ledger is authoritative for cost; this TS-side
    // record is an explicit unknown rather than an invented zero.
    costKnown: false,
    toolCalls: params.toolCalls,
    requestCount: 0,
  }

  store.saveCheckpoint(buildCheckpoint({
    engagement: params.engagement,
    plan: params.plan,
    phases: params.phases,
    scope: scopeEntriesFor(params.target),
    secretRefs: params.roles.map((role) => `credential:${role}`),
    authIdentities,
    limits: params.limits,
    proofStatus,
    observations: params.findings.map(
      (finding) => `${finding.tool ?? "unknown"}: ${finding.url ?? finding.title}`,
    ),
    budgetUsage,
    workerBudget,
    actionDetails: params.actionDetails,
    startedAt: params.startedAt,
    completedAt: params.completedAt,
  }))
}

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
   * Called once the engagement is resolved (created or reused) and before any
   * phase runs. Lets UI callers attach to the engagement without creating it
   * themselves — engagement creation stays here, not in the caller.
   */
  onEngagement?: (engagement: { id: string; target: string; created: boolean }) => void
  /**
   * Cooperative stop: checked before each phase starts. A true result stops at
   * a phase boundary, marks remaining phases SKIPPED, and returns
   * `stopped: true` with `success: false`.
   */
  shouldStop?: () => boolean
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
  /**
   * Verification threshold — controls which findings get browser verification.
   * Only findings with severity >= this value are verified.
   * Default: 3 (HIGH). Set to 0 to verify ALL findings, 4 for CRITICAL only,
   * or 5 to disable verification entirely.
   */
  verificationSeverityThreshold?: number
  /**
   * Custom default XSS payload to use when a finding doesn't specify one.
   * Overrides the built-in "<img src=x onerror=alert(1)>" default.
   */
  xssDefaultPayload?: string
  /**
   * What discovery (or the operator) recorded about the XSS injection point:
   * the injectable parameter, method, encoding and, for stored XSS, the separate
   * victim page. The endpoint itself comes from the finding's structured URL.
   * Without usable discovery data, XSS verification is unsupported rather than
   * pointed at a guessed page.
   */
  xssInjection?: XssDiscovery
}

export interface VerifyEngagementResult {
  /** Number of findings that were verified (had a matching verifier run) */
  verified: number
  /** Number of findings where verification passed (exploit confirmed) */
  passed: number
  /** Number of findings where verification failed (exploit not confirmed) */
  failed: number
  /** Updated findings with verificationResult annotations */
  findings: NormalizedFinding[]
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
  /** True when a cooperative stop ended the run at a phase boundary. */
  stopped?: boolean
  /**
   * Steps the run tolerated instead of failing: phases skipped because no
   * installed tool provides their capability, and phases that failed and were
   * skipped after a retry. Empty/absent when every phase ran.
   */
  degradations?: string[]
  error?: string
  /** All findings with promoted confidence, for rendering summaries */
  allFindings: NormalizedFinding[]
}

/**
 * Validate that scope is explicitly configured before an autonomous run.
 *
 * Fails hard when:
 *   - scope.mode is 'warn' or 'open' (nothing is enforced), or
 *   - scope.mode is 'allowlist' but no allowed targets are configured.
 *
 * The second case matters because the two enforcement layers disagree by
 * default: the TS validator treats an empty allowlist as "no restriction" while
 * the Python workers reject every target ("allowlist mode with no
 * allowed_targets configured"). Without this check an autonomous run would
 * start and then scan nothing.
 *
 * Pure logic so it can be unit tested without a WorkflowRunner or config file.
 *
 * @param isAutonomous - Whether ARGUS_AUTONOMOUS mode is active
 * @param scopeMode - The resolved security.scope.mode (or undefined/unset)
 * @param allowedTargets - The resolved security.scope.allowed_targets
 * @throws Error if autonomous and the scope is not explicitly configured
 */
export function validateAutonomousScopeMode(
  isAutonomous: boolean,
  scopeMode: string | undefined,
  allowedTargets?: string[],
): void {
  if (!isAutonomous) return

  const mode = scopeMode ?? "warn"
  if (mode === "warn" || mode === "open") {
    throw new Error(
      "[Argus] ARGUS_AUTONOMOUS=1: security.scope.mode must be explicitly set to 'allowlist' " +
      "in autonomous mode. Current mode is '" + mode + "'. " +
      "Set 'scope.mode: allowlist' and 'scope.allowed_targets' in argus.config.yaml " +
      "(or ARGUS_SCOPE_MODE=allowlist with ARGUS_ALLOWED_TARGETS=host1,host2) " +
      "to define the authorized scope, or disable autonomous mode."
    )
  }

  if (mode === "allowlist" && !(allowedTargets && allowedTargets.length > 0)) {
    throw new Error(
      "[Argus] ARGUS_AUTONOMOUS=1: scope.mode is 'allowlist' but no authorized targets are " +
      "configured, so every target would be rejected. Set 'security.scope.allowed_targets' in " +
      "argus.config.yaml or ARGUS_ALLOWED_TARGETS=host1,host2 before running autonomously."
    )
  }
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
  /**
   * Bridge reference for MCP-based verification (finding_verifier tool calls).
   * Set during run() when the WorkersBridge is initialized.
   * Used by mcpVerifyFindings() to call the Python finding_verifier tool.
   */
  private executorBridge: WorkersBridge | null = null

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
    options?: {
      severityThreshold?: number
      xssDefaultPayload?: string
      /** Discovered parameter/method/encoding/victim page for XSS testing. */
      xssInjection?: XssDiscovery
      /** Every supplied role, so object-access checks can use real identities. */
      credentialRoles?: Record<string, CredentialEntry>
    },
  ): Promise<NormalizedFinding[]> {
    const threshold = options?.severityThreshold ?? Severity.HIGH
    // If threshold is > CRITICAL (5+), disable verification entirely
    if (threshold > Severity.CRITICAL) return findings

    // Subtypes that don't require authentication can be verified without
    // credentials. The set includes:
    // - SSRF, LFI, JWT, Secrets: Never need auth (they probe the server itself)
    // - XSS: Can test unauthenticated injection points (search, contact forms,
    //   login pages, public API endpoints). Auth-only XSS endpoints are tested
    //   when credentials are available.
    // - BOLA, PrivEsc: Require credentials to compare attacker vs victim roles.
    const noAuthSubtypes = new Set([
      "xss", "xss_stored", "xss_reflected",
      "ssrf", "lfi", "path_traversal",
      "jwt", "jwt_tampering", "jwt_none_algorithm",
      "secrets", "exposed_secrets", "exposed_credentials",
    ])

    const toVerify = !creds
      ? findings.filter(
          (f) => f.subtype && noAuthSubtypes.has(f.subtype) && f.severity >= threshold && !f.verificationResult,
        )
      : findings.filter(
          (f) => f.severity >= threshold && !f.verificationResult,
        )
    if (toVerify.length === 0) return findings

    // Emit verification_start event for TUI display
    emit({ type: "verification_start", phaseId: "", total: toVerify.length })

    const runner = new VerificationRunner()
    // Verification reuses the run's authenticated browser, so the engine is
    // authorized for the engagement target's origin only (Stage 3.2 item 2).
    const engine = new PlaywrightEngine({ allowedTargets: scopeEntriesFor(target) })
    const updated: NormalizedFinding[] = []
    let verifierPassed = 0
    let verifierFailed = 0
    let verifierCurrent = 0

    for (const finding of findings) {
      if (!toVerify.includes(finding)) {
        updated.push(finding)
        continue
      }

      verifierCurrent++
      let scenario
      try {
        switch (finding.subtype) {
          case "xss":
          case "xss_stored":
          case "xss_reflected": {
            // Stage 4.3: the injection point comes from what discovery found
            // (the finding's structured endpoint plus the discovered parameter,
            // method and encoding). The old `${target}/contact` guess is gone,
            // and a finding without usable discovery data is unsupported.
            const plan = xssInjectionPointForFinding(finding, target, options?.xssInjection)
            // The payload must be able to prove its own execution in the
            // victim view. Only a template with the `{{nonce}}` placeholder
            // (and the probe call) is accepted; the finding description and a
            // generic `alert(1)` fallback proved nothing about execution.
            scenario = new StoredXSSVerifier(
              engine,
              plan,
              undefined,
              engagementId,
              finding.id,
              { payloadTemplate: options?.xssDefaultPayload },
            )
            break
          }
          case "bola":
          case "idor": {
            // Stage 4.2: two real identities and a discovered resource. The
            // old code invented a "${username}_b" account with the same
            // password and guessed the path from the description; both are
            // refused by the plan rule now.
            const plan = objectAccessPlan(
              options?.credentialRoles ?? {},
              discoveredResourceForFinding(finding, target),
            )
            scenario = new BOLAVerifier(
              engine,
              target,
              plan,
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
              creds!,
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          case "ssrf": {
            // Extract the SSRF-prone parameter from the finding description or evidence
            const ssrfEndpoint = finding.description.match(/\/\S+/)?.[0] ?? "/"
            scenario = new SSRFVerifier(
              engine,
              target,
              ssrfEndpoint,
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          case "lfi":
          case "path_traversal": {
            // Extract the LFI-prone parameter from the finding
            const lfiParam = finding.description.match(/(?:file|page|include|path|template|load|read|document|folder|root|preview|view|dir|show|url|lang|cat)\s*[:=]\s*\S+/i)?.[0] ?? finding.description.match(/(\/[^\s,]+)/)?.[1] ?? "file"
            scenario = new LFIVerifier(
              engine,
              target,
              lfiParam.startsWith("/") ? lfiParam : `?${lfiParam}=`,
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          case "jwt":
          case "jwt_tampering":
          case "jwt_none_algorithm": {
            const protectedEndpoint = finding.description.match(/(\/[^\s,]+)/)?.[1] ?? "/admin"
            // Try to extract an original JWT from finding evidence
            const jwtMatch = finding.description.match(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/)
            scenario = new JWTVerifier(
              engine,
              target,
              protectedEndpoint,
              jwtMatch?.[0],
              undefined,
              engagementId,
              finding.id,
            )
            break
          }
          case "secrets":
          case "exposed_secrets":
          case "exposed_credentials": {
            const scanEndpoint = finding.description.match(/(\/[^\s,]+)/)?.[1] ?? "/"
            scenario = new SecretsExposureVerifier(
              engine,
              target,
              scanEndpoint,
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

        // Emit verification_progress event for TUI display
        emit({
          type: "verification_progress",
          phaseId: "",
          current: verifierCurrent,
          total: toVerify.length,
          findingTitle: finding.title,
          findingSubtype: finding.subtype,
        })
        const result = await runner.run(scenario)
        // One conversion from verifier result to stored claim: status, controls
        // and (when a step threw) the verifier's error detail.
        const verificationResult: VerificationResult = verificationResultFrom({
          verifier: scenario.name,
          result,
        })

        if (result.passed) {
          verifierPassed++
        } else {
          verifierFailed++
        }

        // Store verification evidence on the finding so the confidence engine's
        // HIGH→VERIFIED rule can use it. Without this, even passed verification
        // doesn't cascade beyond HIGH confidence.
        const verificationEvidence: EvidencePackage[] = (result.evidence || [])
          .filter((e): e is EvidencePackage =>
            (e as EvidencePackage).packageId !== undefined,
          )

        updated.push({
          ...finding,
          verificationResult,
          evidence: verificationEvidence.length > 0
            ? verificationEvidence
            : finding.evidence,  // Keep original evidence if verifier returned none
        })
        emit(`✓ Verification ${result.passed ? "passed" : "failed"} for ${finding.title}`)
      } catch (error) {
        verifierFailed++
        if (error instanceof XssProbeError || error instanceof XssPlanError) {
          // Stage 4.3: a payload that cannot prove execution (or a context that
          // cannot observe it) is unsupported, never a silent "not vulnerable".
          updated.push({
            ...finding,
            verificationResult: {
              passed: false,
              proofStatus: ProofStatus.UNSUPPORTED,
              confidence: 0,
              summary: `XSS verification unsupported: ${error.message}`,
              verifier: "xss",
              verifiedAt: new Date().toISOString(),
              controls: [],
              error: { step: "setup", name: error.name, message: error.message },
            },
          })
          emit(`⚠ XSS verification unsupported for ${finding.title}: ${error.message}`)
          continue
        }
        if (error instanceof ObjectAccessPlanError) {
          // The check could not be set up honestly (no second identity or no
          // discovered resource). Record it as unsupported, never as observed.
          const detail = error as ObjectAccessPlanError
          updated.push({
            ...finding,
            verificationResult: {
              passed: false,
              proofStatus: ProofStatus.UNSUPPORTED,
              confidence: 0,
              summary: `Object-access verification unsupported: ${detail.message}`,
              verifier: "bola",
              verifiedAt: new Date().toISOString(),
              controls: [],
              error: { step: "setup", name: detail.name, message: detail.message },
            },
          })
          emit(`⚠ Object-access verification unsupported for ${finding.title}: ${detail.message}`)
          continue
        }
        updated.push(finding)
        emit(`⚠ Verification error for ${finding.title}: ${(error as Error).message}`)
      }
    }

    // Emit verification_complete event for TUI display
    emit({
      type: "verification_complete",
      phaseId: "",
      passed: verifierPassed,
      failed: verifierFailed,
      total: toVerify.length,
    })

    try {
      await engine.close()
    } catch (closeErr) {
      // Blocker 21: Log engine close failures so they're observable
      console.warn(`[workflow-runner] Engine close error: ${(closeErr as Error).message}`)
    }

    return updated
  }

  /**
   * Verify findings for an existing engagement — public entry point for
   * WebSocket/SSE event-driven verification (Gap 1.1 end-to-end).
   *
   * When the Python orchestrator's run_scan() completes, it emits a
   * VERIFICATION_RECOMMENDED event via the WebSocket. This method can be
   * called by any event handler that receives that event, providing an
   * integration point for the TUI, CLI, or API.
   *
   * Steps:
   * 1. Loads all findings from the engagement store
   * 2. Filters for findings that need browser verification (severity >= threshold)
   * 3. Runs browser-based verifiers (BOLA, XSS, PrivEsc, SSRF, LFI, JWT, Secrets)
   * 4. Annotates findings with verification results
   * 5. Saves updated findings back to the store
   *
   * @param engagementId - The engagement to verify findings for.
   * @param options - Optional overrides (severity threshold, creds, etc.)
   * @returns Number of findings verified, and how many passed.
   */
  async verifyEngagement(
    engagementId: string,
    options?: {
      targetUrl?: string
      credsPath?: string
      severityThreshold?: number
      onProgress?: (event: ProgressEvent | string) => void
    },
  ): Promise<VerifyEngagementResult> {
    const emit = (event: ProgressEvent | string) => {
      options?.onProgress?.(event)
      if (typeof event !== "string") handleProgressEvent(event, engagementId)
    }

    const store = this.deps?.store ?? new EngagementStore()
    const engagement = store.getEngagement(engagementId)
    if (!engagement) {
      emit(`Engagement not found: ${engagementId}`)
      return { verified: 0, passed: 0, failed: 0, findings: [] }
    }

    const targetUrl = options?.targetUrl ?? engagement.target ?? ""
    if (!targetUrl) {
      emit(`No target URL for engagement ${engagementId}`)
      return { verified: 0, passed: 0, failed: 0, findings: [] }
    }

    emit(`⠋ Loading findings for engagement ${engagementId}...`)
    const allFindings = store.getFindings(engagementId) as NormalizedFinding[]
    if (!allFindings || allFindings.length === 0) {
      emit(`No findings to verify for engagement ${engagementId}`)
      return { verified: 0, passed: 0, failed: 0, findings: [] }
    }

    emit({ type: "verification_start", phaseId: "", total: allFindings.length })
    emit(`✓ Loaded ${allFindings.length} findings — running browser verification...`)

    // Load credentials
    const credStore = this.deps?.credStore ?? new CredentialStore()
    const creds = options?.credsPath ? credStore.load(options.credsPath) : credStore.load()
    const defaultCreds = credStore.getDefaultCredentials()
    const credentialRoles = credStore.getAllCredentials()
    credStore.clear()

    // Run verification using the existing verifyFindings logic
    const verifiedFindings = await this.verifyFindings(
      allFindings,
      targetUrl,
      defaultCreds,
      engagementId,
      emit,
                  {
              severityThreshold: options?.severityThreshold,
              credentialRoles,
              xssInjection: (options as { xssInjection?: XssDiscovery } | undefined)?.xssInjection,
            },
    )

    // Confidence promotion cascade: full while-loop through all tiers.
    // Each promote() call advances at most one tier, so the while loop
    // is required to reach CONFIRMED from any starting confidence. The engine
    // — not a bare `passed` flag — decides where it stops: metadata ends at
    // HIGH and only a reproduced verification with real proof may confirm, so
    // repeating promote() cannot override a failed check (Stage 4.1).
    const confidenceEngine = this.deps?.confidenceEngine ?? new ConfidenceEngine()
    for (const finding of verifiedFindings) {
      let promoted = confidenceEngine.promote(finding)
      while (promoted !== finding.confidence) {
        finding.confidence = promoted
        promoted = confidenceEngine.promote(finding)
      }
    }

    // Save updated findings back to the store with verification results
    const verifiedCount = verifiedFindings.filter((f) => f.verificationResult).length
    const passedCount = verifiedFindings.filter((f) => f.verificationResult?.passed).length
    const failedCount = verifiedFindings.filter((f) => f.verificationResult && !f.verificationResult.passed).length

    store.saveFindings(engagementId, verifiedFindings)

    emit({
      type: "verification_complete",
      phaseId: "",
      passed: passedCount,
      failed: failedCount,
      total: verifiedCount,
    })
    emit(`✓ Verification complete: ${passedCount} passed, ${failedCount} failed (${verifiedCount} total verified)`)

    return { verified: verifiedCount, passed: passedCount, failed: failedCount, findings: verifiedFindings }
  }

  /**
   * Run MCP-based verification for HIGH+ findings using the Python
   * finding_verifier tool (HTTP-based: SQLi, XSS, Open Redirect).
   *
   * This is a supplement to browser-based verification. It sends lightweight
   * HTTP probes to confirm findings like SQLi payload reflection, XSS payload
   * reflection, and open redirect chains.
   *
   * Findings that have already passed browser verification are skipped since
   * they already have higher-confidence verification results.
   */
  private async mcpVerifyFindings(
    findings: NormalizedFinding[],
    target: string,
    engagementId: string,
    emit: (event: ProgressEvent | string) => void,
  ): Promise<NormalizedFinding[]> {
    // Finding types that the Python finding_verifier can verify via HTTP
    const mcpVerifiableTypes = new Set([
      "sqli", "sql-injection", "sql_injection",
      "xss", "cross-site-scripting",
      "open-redirect", "open_redirect",
    ])

    const toVerify = findings.filter(
      (f) =>
        f.severity >= 3 &&  // HIGH+
        f.subtype &&
        mcpVerifiableTypes.has(f.subtype) &&
        !f.verificationResult,  // Skip already-verified findings
    )

    if (toVerify.length === 0) return findings

    // Get the bridge from the executor (set during run())
    // We access it via the deps pattern — bridge is created in run()
    // and available through the executor's bridge reference.
    // For standalone use, we check this.deps?.bridge first.
    // MCP call is best-effort — failures don't block the assessment.
    const finderResult = { verifiedCount: 0 }

    // Emit MCP verification start event
    emit({
      type: "verification_start",
      phaseId: "mcp",
      total: toVerify.length,
    })

    await Promise.all(
      toVerify.map(async (finding, idx) => {
        try {
          // Emit MCP verification progress
          emit({
            type: "verification_progress",
            phaseId: "mcp",
            current: idx + 1,
            total: toVerify.length,
            findingTitle: finding.title,
            findingSubtype: finding.subtype,
          })
          emit(`⠋ MCP-verifying ${finding.subtype} finding: ${finding.title}`)

          const endpoint = finding.url ?? finding.description?.match(/(https?:\/\/[^\s]+)/)?.[1] ?? target
          const payload = finding.description?.includes("<script>")
            ? finding.description
            : finding.evidence?.[0]?.artifacts?.[0]?.path ?? ""

          // The bridge must be available — if not, skip MCP verification silently
          let result: { success: boolean; data?: { verified?: boolean; confidence?: string; reason?: string } } | null = null
          try {
            // Use the properly-typed private field set during run().
            // If it's null, the bridge was never assigned (run() failed early
            // or mcpVerifyFindings was called outside the run() context).
            if (!this.executorBridge) {
              emit("⚠ MCP verification skipped: bridge not available (run() may not have completed setup)")
            } else if (this.executorBridge.callTool) {
              result = await this.executorBridge.callTool(
                "finding_verifier",
                {
                  target,
                  finding_type: finding.subtype,
                  payload,
                  endpoint,
                  engagement_id: engagementId,
                },
                60000,  // 60s timeout
              ) as { success: boolean; data?: { verified?: boolean; confidence?: string; reason?: string } }
            }
          } catch (bridgeErr) {
            emit(`⚠ MCP bridge call failed for ${finding.subtype} finding: ${(bridgeErr as Error).message}`)
          }

          if (result?.success && result.data?.verified) {
            finderResult.verifiedCount++
            finding.verificationResult = {
              passed: true,
              // An HTTP probe is reachability, not exploit proof: the finding is
              // suspected, and the later stages must not promote it further on
              // the strength of this answer alone.
              proofStatus: ProofStatus.SUSPECTED,
              confidence: 0.8,  // MCP HTTP verification — reasonable confidence
              summary: `MCP verified: ${result.data.reason ?? "HTTP probe confirmed"}`,
              verifier: "finding_verifier",
              verifiedAt: new Date().toISOString(),
              controls: [],
            }
            emit(`✓ MCP verification passed for ${finding.title}`)
          } else if (result) {
            emit(`⚠ MCP verification did not confirm for ${finding.title}: ${result.data?.reason ?? "no reason"}`)
          }
        } catch {
          // MCP verification failures are best-effort — don't block
        }
      }),
    )

    // Emit MCP verification complete event
    emit({
      type: "verification_complete",
      phaseId: "mcp",
      passed: finderResult.verifiedCount,
      failed: toVerify.length - finderResult.verifiedCount,
      total: toVerify.length,
    })

    if (finderResult.verifiedCount > 0) {
      emit(`✓ MCP verification: ${finderResult.verifiedCount} finding(s) confirmed`)
    }

    return findings
  }

  /**
   * Subscribe to VERIFICATION_RECOMMENDED events and automatically dispatch
   * browser verification when they arrive. This completes the Gap 1.1
   * end-to-end: the Python orchestrator emits events via run_verification(),
   * and this listener picks them up without manual intervention.
   *
   * The listener accepts a callback-based event source (e.g., from the TUI's
   * SSE stream, WebSocket handler, or MCP bridge). When a matching event
   * arrives, it calls verifyEngagement() to run browser verifiers.
   *
   * Usage with an SSE/WebSocket event source:
   * ```typescript
   * const runner = new WorkflowRunner()
   * const unsub = runner.subscribeToVerificationEvents({
   *   onEvent: (handler) => {
   *     // Wire to your event transport:
   *     // sseClient.on("message", handler)
   *     // websocket.on("message", handler)
   *     return () => { }  // cleanup function
   *   },
   * })
   * ```
   *
   * Note: The handler receives the **parsed event object**, not a message
   * wrapper. If your transport delivers wrapped events (e.g., MessageEvent
   * with a .data property), extract the inner payload before passing it
   * to the handler.
   *
   * @param source - Event source with an onEvent callback and optional targetUrl
   * @returns An unsubscribe function to stop listening
   */
  subscribeToVerificationEvents(source: {
    /**
     * Called to register the event handler. Receives a function that should
     * be called for every incoming event. Returns a cleanup function that
     * will be called to unsubscribe.
     */
    onEvent: (handler: (event: unknown) => void) => (() => void) | undefined
    /** Optional target URL override for verification */
    targetUrl?: string
    /** Optional severity threshold (default: Severity.HIGH = 3) */
    severityThreshold?: number
    /** Optional progress callback for status updates */
    onProgress?: (event: ProgressEvent | string) => void
  }): () => void {
    const pendingVerifications = new Set<string>()

    // Subscribe to events — handle both sync and async subscription APIs
    let cleanup: (() => void) | undefined
    try {
      cleanup = source.onEvent(async (rawEvent: unknown) => {
        try {
          const event = rawEvent as Record<string, unknown>

          // Check if this is a VERIFICATION_RECOMMENDED event from the Python orchestrator
          // The event can arrive in multiple formats depending on the transport:
          // 1. scanner_activity with tool_name="verification_runner" and activity="Browser verification recommended"
          // 2. A structured event with type/stype matching verification patterns
          const isVerificationEvent =
            // Format 1: scanner_activity from WebSocketEventPublisher
            (event.tool_name === "verification_runner" &&
              typeof event.activity === "string" &&
              event.activity.toLowerCase().includes("verification")) ||
            // Format 2: Direct event type match
            (typeof event.type === "string" &&
              (event.type.toUpperCase() === "VERIFICATION_RECOMMENDED" ||
                event.type === "scanner_activity")) ||
            // Format 3: Details field with finding_ids
            (typeof event.details === "string" &&
              event.details.includes("finding_ids"))

          if (!isVerificationEvent) return

          // Extract engagement ID from the event
          let eventEngagementId: string | undefined =
            (event.engagement_id as string) ??
            (event.engagementId as string)

          if (!eventEngagementId) {
            // Try to extract from details JSON
            if (typeof event.details === "string") {
              try {
                const details = JSON.parse(event.details)
                eventEngagementId = details.engagement_id as string
              } catch {
                // Ignore parse failures
              }
            }
          }

          if (!eventEngagementId) return

          // Deduplicate: don't verify the same engagement concurrently
          if (pendingVerifications.has(eventEngagementId)) return
          pendingVerifications.add(eventEngagementId)

          try {
            const result = await this.verifyEngagement(eventEngagementId, {
              targetUrl: source.targetUrl,
              severityThreshold: source.severityThreshold,
              onProgress: source.onProgress,
            })

            if (result.verified > 0) {
              source.onProgress?.(`✓ Auto-verification complete for ${eventEngagementId}: ${result.passed} passed, ${result.failed} failed`)
            }
          } finally {
            pendingVerifications.delete(eventEngagementId)
          }
        } catch {
          // Event processing is best-effort — don't crash on malformed events
        }
      })
    } catch {
      // Subscription setup failed — cleanup is undefined
    }

    return () => { cleanup?.() }
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

    // ── 0. Sweep plaintext scratch files from any previous session ──
    // `EncryptedDbHandle` writes the decrypted engagement database next to the
    // encrypted one while a session is open, and only a clean `close()` removes
    // it. Every crash or SIGKILL therefore left a plaintext copy of an
    // engagement database on disk permanently (950+ had accumulated here). The
    // encrypted `.db` is not touched.
    try {
      const { sweepEngagementsDir } = await import("./storage/encrypted-db")
      const { StoragePaths } = await import("./storage/paths")
      const swept = sweepEngagementsDir(StoragePaths.engagementsDir)
      if (swept.length > 0) {
        emit(`✓ Removed ${swept.length} leftover plaintext engagement file(s) from previous sessions`)
      }
    } catch (sweepErr) {
      emit(`⚠ Plaintext scratch sweep skipped: ${(sweepErr as Error).message}`)
    }

    // ── 1. Create or use existing engagement ──
    const store = this.deps?.store ?? new EngagementStore()
    // Register exit handler for clean SQLite shutdown (blocker 41)
    store.registerExitHandler()
    let engagementId = options.engagementId
    if (engagementId) {
      // Verify the engagement exists
      const existing = store.getEngagement(engagementId)
      if (!existing) {
        throw new Error(`Engagement ${engagementId} not found in store`)
      }
      store.updateStatus(engagementId, "RUNNING")
      options.onEngagement?.({ id: engagementId, target, created: false })
      emit(`✓ Using existing engagement: \`${engagementId}\``)
    } else {
      const engagement = store.createEngagement(target, "assessment")
      engagementId = engagement.id
      store.updateStatus(engagementId, "RUNNING")
      options.onEngagement?.({ id: engagementId, target, created: true })
      emit(`✓ Engagement created: \`${engagementId}\``)
    }

    // Stage 6.2: explicit UTC timestamp for the run, persisted in every
    // checkpoint. Missing progress is never inferred from this timestamp.
    const runStartedAt = new Date().toISOString()

    // ── 2. Load credentials, feature flags & replan config ──
    const featureFlags = new FeatureFlags(options.features)
    let configMaxReplans: number | undefined
    let configLlmMaxReplans: number | undefined
    const isAutonomous = process.env.ARGUS_AUTONOMOUS === "1" || process.env.ARGUS_AUTONOMOUS === "true"
    try {
      const { readFileSync } = await import("fs")
      const { parse: YAML } = await import("yaml")
      const configPath = join(process.cwd(), "argus.config.yaml")
      const raw = readFileSync(configPath, "utf-8")
      const parsed = YAML(raw) as {
        features?: Record<string, boolean>
        replan?: { max_cycles?: number; llm_max_cycles?: number }
        security?: { scope?: { mode?: string; allowed_targets?: string[] } }
      } | undefined
      if (parsed?.features) {
        featureFlags.loadFromConfig(parsed.features)
      }
      configMaxReplans = parsed?.replan?.max_cycles
      configLlmMaxReplans = parsed?.replan?.llm_max_cycles
    } catch (configErr) {
      if (isAutonomous) {
        // Refused before it starts — do not leave the engagement reading RUNNING.
        store.updateStatus(engagementId, "FAILED")
        throw new Error(
          "[Argus] ARGUS_AUTONOMOUS=1: config file 'argus.config.yaml' is missing or malformed. " +
          "A valid config file is required in autonomous mode. Fix the file or disable autonomous mode."
        )
      }
      // Blocker 21: Log the actual error so silent config fallback is observable
      console.warn("Config file missing or invalid, using defaults:", (configErr as Error).message)
      /* config file missing or invalid — use defaults */
    }

    // Autonomous mode requires scope to be explicitly configured so out-of-scope
    // targets are rejected instead of warned (blocker 36 fix). This runs OUTSIDE
    // the try above — otherwise its own error is swallowed and re-reported as a
    // "config file missing or malformed" failure.
    //
    // Resolved through the validator so ARGUS_SCOPE_MODE / ARGUS_ALLOWED_TARGETS
    // overrides are honoured — the same values the enforcer uses.
    if (isAutonomous) {
      try {
        const resolvedScope = getTargetValidator().load().scope
        validateAutonomousScopeMode(isAutonomous, resolvedScope?.mode, resolvedScope?.allowed_targets)
      } catch (scopeErr) {
        // Same reason as above: a refused run never started, so it must not
        // linger as RUNNING in `argus engagements`.
        store.updateStatus(engagementId, "FAILED")
        throw scopeErr
      }
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
    const plan = await planner.plan(target, defaultCreds ? { authState: "basic" } : undefined, {
      useLLM,
      onProgress: (event) => { if (typeof event !== "string") emit(event) },
    })
    emit(`✓ Plan created: ${plan.phases.length} phase(s)`)

    // ── Self-healing degradation ──
    // Autonomous runs must survive a missing tool or a crashing phase: the
    // offending step is skipped, recorded here, and the remaining phases still
    // run. Interactive runs keep the fail-fast behaviour below.
    const autonomousRun =
      process.env.ARGUS_AUTONOMOUS === "1" || process.env.ARGUS_AUTONOMOUS === "true"
    const degradations: string[] = []
    const recordDegradation = (kind: string, detail: string) => {
      const entry = `${kind}: ${detail}`
      degradations.push(entry)
      emit(`⚠ Degraded (${kind}) — ${detail}`)
      try {
        store.appendAuditLog(engagementId, "RUN_DEGRADED", entry)
      } catch {
        // Reporting is best-effort — it must never stop the assessment.
      }
    }
    if (plan.degradations && plan.degradations.length > 0) {
      for (const dropped of plan.degradations) {
        recordDegradation("capability-missing", dropped)
      }
    }

    if (defaultCreds) {
      for (const phase of plan.phases) {
        phase.config.credentials = defaultCreds
      }
    }
    // Inject engagementId into all phase configs so the executor can
    // forward it to agentInit for hypothesis loading.
    for (const phase of plan.phases) {
      phase.config.engagementId = engagementId
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
    let stopped = false
    // Set inside the try; read in the finally to record gate decisions.
    let approvalAuditExecutor: InProcessExecutor | undefined
    const phaseProvenance = new Map<string, PlannedPhaseProvenance>()
    const actionDetails: Record<string, CheckpointActionDetail> = {}
    const bridge = this.deps?.bridge ?? new WorkersBridge(workersPath)
    // Store bridge reference for mcpVerifyFindings() to access
    this.executorBridge = bridge

    try {
      emit(`⠋ Connecting MCP workers...`)
      await bridge.connect()
      emit(`✓ MCP workers connected`)

      // ── Worker tool state → planner registry ──
      // The plan above was built from the static TypeScript registry, which
      // knows nothing about which tools the worker can actually run. Ask it
      // once here so disabled tools (no execution phase worker-side) and tools
      // whose binary is not installed stop being dispatched. Without this the
      // run collected a usage/flag error for every one of them.
      try {
        const workerTools = await bridge.getTools()
        const blocked = toolRegistry.setWorkerToolStatus(
          workerTools as unknown as import("./workflows/tool-registry").WorkerToolStatus[],
        )
        if (blocked.length > 0) {
          emit(`⚠ ${blocked.length} tool(s) the worker cannot run will be skipped`)
          store.appendAuditLog(
            engagementId,
            "TOOL_AVAILABILITY",
            blocked.map((b) => `${b.name}: ${b.reason}`).join("; "),
          )
        }
      } catch (toolStatusErr) {
        // Advisory: a worker that cannot list its tools must not fail the run.
        emit(`⚠ Could not read worker tool state (${(toolStatusErr as Error).message}) — scheduling unfiltered`)
      }

      // Phase 4.4.1: Acquire distributed lock before phase execution
      // In autonomous mode, fail hard if the lock can't be acquired (blocker 23)
      const lockedEngagement = await bridge.acquireEngagementLock(engagementId).catch(() => ({ acquired: false }))
      if (!lockedEngagement.acquired) {
        const isAutonomous = process.env.ARGUS_AUTONOMOUS === "1" || process.env.ARGUS_AUTONOMOUS === "true"
        if (isAutonomous) {
          throw new Error(
            `[Argus] ARGUS_AUTONOMOUS=1: Could not acquire distributed lock for engagement ${engagementId}. ` +
            `Distributed locking is required in autonomous mode to prevent concurrent assessments on the same target. ` +
            `Ensure Redis is running or disable autonomous mode.`
          )
        }
        emit(`⚠ Could not acquire distributed lock for ${engagementId} — proceeding without lock`)
      } else {
        emit(`✓ Distributed lock acquired for engagement`)
      }

      // Phase 4.1.3: On resume, query checkpoints and skip completed tools
      // Check if engagement was previously started (has phases)
      const existingPhases = store.getPhases(engagementId)
      const isResume = existingPhases.length > 0
      if (isResume) {
        emit(`⠋ Engagement has existing phases — checking checkpoints for resume`)
      }

      const confidenceEngine = this.deps?.confidenceEngine ?? new ConfidenceEngine()
      const executor = this.deps?.executor ?? new InProcessExecutor(toolRegistry, bridge, confidenceEngine, workflowRegistry)
      // Reachable from the `finally` block for the approval-decision audit below.
      approvalAuditExecutor = executor
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
      let llmReplanCount = 0
      const targetType = detectTargetType(target)
      const authState = detectAuthState(target)
      for (const initialPhase of plan.phases) {
        phaseProvenance.set(initialPhase.phaseId, plannedPhaseProvenance(initialPhase, "plan"))
      }

      let i = 0
      while (i < plan.phases.length) {
        const phase = plan.phases[i]
        const phaseName = phase.name

        if (options.shouldStop?.()) {
          stopped = true
          emit(`⚠ Stop requested — not starting phase ${phaseName}`)
          try {
            store.appendAuditLog(engagementId, "STOP_REQUESTED", `Stopped before phase ${phaseName}`)
          } catch {
            // Audit logging is best-effort — never block the stop.
          }
          for (let j = i; j < plan.phases.length; j++) {
            const pending = phaseRecords.get(plan.phases[j].phaseId)
            if (!pending || pending.status !== "PENDING") continue
            pending.status = "SKIPPED"
            pending.completedAt = new Date().toISOString()
            store.savePhase(engagementId, pending)
          }
          break
        }

        emit({ type: "phase_start", phaseId: phase.phaseId, name: phaseName, total: plan.phases.length, phaseIndex: i })
        // Phase 4.2.3: In degraded mode, skip LLM-driven phases but continue
        // with deterministic phases using cached tool results.
        if (bridge.supervisor.degraded && phase.toolExecution === "llm_driven") {
          emit(`⚠ Degraded mode — skipping LLM-driven phase ${phaseName}`)
          store.appendAuditLog(engagementId, "DEGRADED_SKIP",
            `Skipped ${phaseName} (LLM-driven) — MCP worker in degraded mode`)
          i++
          continue
        }

        // ── Self-healing: capability with no installed tool ──
        // Replan and chain phases are built without a tool-availability check,
        // and a worker can report a tool unusable after the plan exists.
        // Dispatching a call that cannot succeed only collects a usage error,
        // so the phase is skipped and the run continues.
        if (autonomousRun && phase.toolExecution !== "llm_driven") {
          const runnable = toolRegistry.selectBest(phase.requiredCapabilities as any, targetType)
          if (runnable.length === 0) {
            const skippedRecord = phaseRecords.get(phase.phaseId)
            if (skippedRecord) {
              skippedRecord.status = "SKIPPED"
              skippedRecord.completedAt = new Date().toISOString()
              skippedRecord.error =
                "no installed tool for " + phase.requiredCapabilities.join(", ")
              store.savePhase(engagementId, skippedRecord)
            }
            recordDegradation(
              "capability-missing",
              `${phaseName}: no installed tool for ${phase.requiredCapabilities.join(", ")}`,
            )
            for (const cap of phase.requiredCapabilities) executedCapabilities.add(cap)
            i++
            continue
          }
        }

        emit(`⠋ Running phase ${i + 1}/${plan.phases.length}: ${phaseName}`)

        const record = phaseRecords.get(phase.phaseId)!
        record.status = "RUNNING"
        record.startedAt = new Date().toISOString()
        store.savePhase(engagementId, record)

        // ── Self-healing: a phase that throws ──
        // Autonomous runs retry once, then skip the phase so one broken
        // scanner cannot end the assessment. Interactive runs rethrow, which
        // the outer catch turns into a FAILED engagement (unchanged).
        let result: Awaited<ReturnType<InProcessExecutor["execute"]>> | undefined
        const maxAttempts = autonomousRun ? 2 : 1
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
          try {
            result = await executor.execute(phase)
            break
          } catch (execErr) {
            const message = (execErr as Error).message
            if (!autonomousRun) throw execErr
            if (attempt < maxAttempts) {
              emit(
                `⚠ Phase ${phaseName} failed (${message}) — retrying (attempt ${attempt + 1}/${maxAttempts})`,
              )
              try {
                store.appendAuditLog(engagementId, "PHASE_RETRY", `${phaseName}: ${message}`)
              } catch {
                // Audit logging is best-effort.
              }
              continue
            }
            recordDegradation(
              "phase-failed",
              `${phaseName} failed and was skipped: ${message}`,
            )
            emit({ type: "phase_error", phaseId: phase.phaseId, name: phaseName, error: message })
            const failedRecord = phaseRecords.get(phase.phaseId)
            if (failedRecord) {
              failedRecord.status = "FAILED"
              failedRecord.completedAt = new Date().toISOString()
              failedRecord.error = message
              store.savePhase(engagementId, failedRecord)
            }
            // Mark the capability executed so replanning does not immediately
            // queue the same failing work again (replan budget still bounds it).
            for (const cap of phase.requiredCapabilities) executedCapabilities.add(cap)
            insertedPhaseIds.add(phase.phaseId)
          }
        }
        if (!result) {
          i++
          continue
        }

        let phaseFindings = result.findings
        if (phaseFindings.length > 0) {
          // Step 1: Browser-based verification for subtypes with Playwright verifiers
          phaseFindings = await this.verifyFindings(
            phaseFindings,
            target,
            defaultCreds,
            engagementId,
            emit,
            {
              severityThreshold: options.verificationSeverityThreshold,
              xssDefaultPayload: options.xssDefaultPayload,
              xssInjection: options.xssInjection,
              credentialRoles: this.deps?.credStore?.getAllCredentials() ?? {},
            },
          )

          // Step 2: MCP-based verification for HIGH+ findings using the Python
          // finding_verifier tool (HTTP-based: SQLi, XSS, Open Redirect).
          // This supplements browser verification with lightweight HTTP probes.
          await this.mcpVerifyFindings(
            phaseFindings,
            target,
            engagementId,
            emit,
          )
        }

        for (const finding of phaseFindings) {
          // recon crawls a page and api_discovery crawls it again, so the same
          // finding arrives once per phase with its own id and the report (and
          // the total) counted it twice. Identity is what was found, where, by
          // which tool — the id says nothing.
          emit({ type: "finding", phaseId: phase.phaseId, severity: String(finding.severity), title: finding.title })
          // Promote confidence iteratively until no more promotions apply.
          // This cascades: MEDIUM→HIGH→VERIFIED→CONFIRMED in a single pass
          // only when a verification reproduced the issue with real proof;
          // metadata and a bare pass stop at HIGH (Stage 4.1).
          // Each promote() call advances at most one tier.
          let promoted = confidenceEngine.promote(finding)
          while (promoted !== finding.confidence) {
            finding.confidence = promoted
            promoted = confidenceEngine.promote(finding)
          }
          // One entry per distinct finding, with the promoted confidence — the
          // same identity the resume path uses, so a resumed phase cannot report
          // what was already collected a second time.
          mergeFinding(allFindings, { ...finding, confidence: promoted })
        }

        const phaseStatus = result.status === "failed" ? "FAILED" : result.status === "partial" ? "PARTIAL" : result.status === "skipped" ? "SKIPPED" : "COMPLETED"
        const finalRecord = phaseRecords.get(phase.phaseId)!
        finalRecord.status = phaseStatus
        finalRecord.completedAt = new Date().toISOString()
        if (result.errors.length > 0) finalRecord.error = result.errors.join("; ")
        store.savePhase(engagementId, finalRecord)

        // Stage 6.2 item 1: persist the approved plan, phase results, proof
        // status and budget usage at every phase boundary, so a restart resumes
        // this run instead of inventing a new one.
        actionDetails[phase.phaseId] = actionDetailForPhase(
          phaseProvenance.get(phase.phaseId) ?? plannedPhaseProvenance(phase, "replan"),
          phaseStatus,
          result.actionRecords ?? [],
        )
        await saveRunCheckpoint({
          store,
          engagement: store.getEngagement(engagementId)!,
          bridge,
          plan,
          phases: Array.from(phaseRecords.values()),
          target,
          roles: credStore.listRoles(),
          findings: allFindings,
          toolCalls: i + 1,
          startedAt: runStartedAt,
          limits: {
            maxReplans: configMaxReplans ?? null,
            llmMaxReplans: configLlmMaxReplans ?? null,
            deadlineAt: process.env.ARGUS_DEADLINE_AT ?? null,
          },
          actionDetails: { ...actionDetails },
        })

        // Durable progress. Findings used to be written once, after the last
        // phase, so a restart mid-run resumed with an empty database and the
        // next phase started from nothing. Writing them at every phase
        // boundary means a resumed run keeps everything already collected.
        try {
          store.saveFindings(engagementId, allFindings)
        } catch (saveErr) {
          emit(`⚠ Could not persist findings after ${phaseName}: ${(saveErr as Error).message}`)
        }

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

        // ── Phase 1.2: LLM-Driven Replanning — feed findings back ──
        // After each phase completes, signal completion to the Python MCP worker
        // so the LLM can analyze accumulated findings and suggest next capabilities.
        // This is best-effort — failures don't block the assessment.
        // Collect LLM suggestions for the planner's replan() method below.
        let llmSuggestedCapabilities: string[] | undefined
        let llmReasoningText: string | undefined
        try {
          const phaseCompleteResult = await bridge.phaseComplete({
            engagement_id: engagementId,
            phase: phaseName,
            target,
            findings: allFindings.map((f) => ({
              type: f.subtype?.toUpperCase() ?? "UNKNOWN",
              subtype: f.subtype,
              severity: f.severity >= 4 ? "CRITICAL" : f.severity === 3 ? "HIGH" : f.severity === 2 ? "MEDIUM" : f.severity === 1 ? "LOW" : "INFO",
              title: f.title,
              endpoint: f.url ?? f.description?.match(/(https?:\/\/[^\s]+)/)?.[1] ?? "",
              confidence: f.confidence,
            })),
          })

          // Log fallback (degraded) status from the Python side (blocker 16)
          if (phaseCompleteResult.fallback) {
            emit(`⚠ LLM unavailable for phase analysis — using fallback phase progression`)
            store.appendAuditLog(engagementId, "PHASE_COMPLETE_FALLBACK",
              `Phase ${phaseName} complete feedback used fallback (LLM unavailable): ${phaseCompleteResult.reasoning.slice(0, 200)}`)
          }

          if (!phaseCompleteResult.stop && phaseCompleteResult.next_capabilities.length > 0) {
            store.appendAuditLog(engagementId, "PHASE_COMPLETE_LLM",
              `Phase ${phaseName} complete — LLM suggests ${phaseCompleteResult.next_capabilities.join(", ")}: ${phaseCompleteResult.reasoning.slice(0, 200)}`)
            emit(`⠋ LLM analysis: phase ${phaseName} complete — suggested next: ${phaseCompleteResult.next_capabilities.join(", ")}`)

            // ── LLM-Driven Replanning ──
            // Instead of creating phases inline, pass the LLM suggestions to the
            // planner's replan() method below. This ensures all replan decisions
            // (deduplication, attack chain merging, MAX_REPLANS budget, and tool
            // selection) go through the same single code path in WorkflowPlanner.
            llmSuggestedCapabilities = phaseCompleteResult.next_capabilities
            llmReasoningText = phaseCompleteResult.reasoning
          }

          // If the next phase is llm_driven, wire accumulated findings as previousPhaseResults
          // so the hybrid executor's agentInit call receives context about past findings.
          const nextPhase = plan.phases[i + 1]
          if (nextPhase && nextPhase.toolExecution === "llm_driven") {
            nextPhase.previousPhaseResults = (nextPhase.previousPhaseResults ?? []).concat([{
              phaseId: phase.phaseId,
              status: phaseStatus === "FAILED" ? "failed" : phaseStatus === "PARTIAL" ? "partial" : "completed",
              findings: allFindings.filter(f => !f.verificationResult || f.verificationResult.passed),
              artifacts: [],
              errors: result.errors,
              durationMs: Date.now() - startTime,
            }])
          }
        } catch (err) {
          // Phase complete feedback is best-effort — don't block the assessment
          emit(`⚠ Phase complete feedback failed (non-blocking): ${(err as Error).message}`)
        }

        if (!phase.replanCycle) {
          // ── Fetch attack graph chains from Python worker ──
          // Build the attack graph from accumulated findings to detect
          // vulnerability chains that suggest exploitation phases.
          let chainPlans: import("./planner/types").ChainPhasePlan[] | undefined
          try {
            const agResult = await bridge.getAttackGraph({
              engagement_id: engagementId,
              findings: allFindings.map((f) => ({
                type: f.subtype?.toUpperCase() ?? "UNKNOWN",
                severity: f.severity >= 4 ? "CRITICAL" : f.severity === 3 ? "HIGH" : f.severity === 2 ? "MEDIUM" : f.severity === 1 ? "LOW" : "INFO",
                endpoint: f.url ?? f.description?.match(/(https?:\/\/[^\s]+)/)?.[1] ?? "",
                source_tool: f.source ?? "",
                confidence: f.confidence ? f.confidence / 5 : 0.5,
              })),
            })
            if (agResult.chain_plans && agResult.chain_plans.length > 0) {
              chainPlans = agResult.chain_plans
              emit(`⠋ Attack graph: ${agResult.chains.length} chain(s) detected, ${agResult.chain_plans.length} exploitation phase(s) available`)
              store.appendAuditLog(engagementId, "ATTACK_GRAPH",
                `Detected ${agResult.chains.length} chain(s), ${agResult.chain_plans.length} exploitation plan(s)`)
            }

            // ── Fetch full attack graph snapshot for frontend visualization ──
            // Runs alongside the chain detection above but returns the complete
            // to_snapshot_dict() output with node/edge/risk data for the SVG visualizer.
            // Best-effort: failures don't block the assessment.
            try {
              const snapshot = await bridge.getAttackGraphSnapshot({
                engagement_id: engagementId,
                findings: allFindings.map((f) => ({
                  type: f.subtype?.toUpperCase() ?? "UNKNOWN",
                  severity: f.severity >= 4 ? "CRITICAL" : f.severity === 3 ? "HIGH" : f.severity === 2 ? "MEDIUM" : f.severity === 1 ? "LOW" : "INFO",
                  endpoint: f.url ?? f.description?.match(/(https?:\/\/[^\s]+)/)?.[1] ?? "",
                  source_tool: f.source ?? "",
                  confidence: f.confidence ? f.confidence / 5 : 0.5,
                })),
              })
              // Emit the snapshot as a structured progress event so the TUI's
              // scan-store can store it and render the AttackGraphVisualizer.
              emit({
                type: "attack_graph_update",
                engagementId,
                snapshot,
              })
            } catch (snapErr) {
              // Snapshot fetch is best-effort — visualizer just won't update
              emit(`⚠ Attack graph snapshot failed (non-blocking): ${(snapErr as Error).message}`)
            }
          } catch (err) {
            // Attack graph is best-effort — don't block replanning if it fails
            emit(`⚠ Attack graph fetch failed (non-blocking): ${(err as Error).message}`)
          }

          const replanCtx: PlannerContext = {
            target,
            targetType,
            authState,
            findings: allFindings,
            executedCapabilities,
            insertedPhases: insertedPhaseIds,
            replanCount,
            maxReplans: configMaxReplans,
            llmMaxReplans: (() => {
              // Config file takes precedence over env var
              if (configLlmMaxReplans !== undefined) return configLlmMaxReplans
              const raw = process.env.ARGUS_LLM_MAX_REPLANS
              if (!raw) return undefined  // unset → planner default
              const n = Number(raw)
              return Number.isFinite(n) && n >= 0 ? n : undefined
            })(),
            llmReplanCount,
            hypotheses: allHypotheses.length > 0 ? allHypotheses : undefined,
            chainPlans,
            llmSuggestedCapabilities,
            llmReasoning: llmReasoningText,
            onProgress: (event) => { if (typeof event !== "string") emit(event) },
          }
          const replanPhases = await planner.replan(replanCtx)
          replanCount = replanCtx.replanCount
          llmReplanCount = replanCtx.llmReplanCount ?? 0

          if (replanPhases && replanPhases.length > 0) {
            emit(`⠋ Replanning: ${replanPhases.length} new phase(s) from accumulated findings`)
            store.appendAuditLog(engagementId, "REPLAN_INSERT",
              `Inserting ${replanPhases.length} replan phase(s) at position ${i + 1}`)

            let insertOffset = 0
            for (const rp of replanPhases) {
              if (defaultCreds) {
                rp.config.credentials = defaultCreds
              }
              rp.config.engagementId = engagementId
              for (const cap of rp.requiredCapabilities) {
                executedCapabilities.add(cap)
              }
              plan.phases.splice(i + 1 + insertOffset, 0, rp)
              insertOffset++
              plan.errorRecovery[rp.phaseId] = "retry_once_then_skip"
              phaseProvenance.set(rp.phaseId, plannedPhaseProvenance(rp, "replan"))
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
      try {
        store.appendAuditLog(engagementId, "RUNNER_ERROR",
          `Workflow error: ${executionError.message}`)
      } catch {
        // Audit logging is best-effort — a storage failure must never mask the
        // original execution error (or skip the teardown below).
      }
    } finally {
      // Persist results, but never let a storage failure escape the finally:
      // the MCP worker is a child process whose pipes keep the event loop
      // alive, so skipping bridge.disconnect() hangs the whole CLI run.
      // Record every approval-gate decision. With ARGUS_AUTO_APPROVE=1 the
      // prompts are silent, so without this there is no evidence that the
      // destructive/privilege-escalation gates were consulted at all — which is
      // why their behaviour was unproven. Refusals are included, so a run with
      // ARGUS_DENY_DESTRUCTIVE=1 shows exactly what the gate blocked.
      try {
        const decisions = approvalAuditExecutor?.getApprovalDecisions() ?? []
        if (decisions.length > 0) {
          const refused = decisions.filter((d) => !d.approved)
          store.appendAuditLog(
            engagementId,
            "APPROVAL_DECISIONS",
            `${decisions.length} gate decision(s), ${refused.length} refused: ` +
              decisions.map((d) => `${d.kind}:${d.gate}=${d.approved ? "approved" : "refused"}(${d.source})`).join("; "),
          )
          emit(`✓ ${decisions.length} approval gate decision(s) recorded${refused.length > 0 ? `, ${refused.length} refused` : ""}`)
        }
      } catch (auditErr) {
        emit(`⚠ Could not record approval decisions: ${(auditErr as Error).message}`)
      }

      let persistError: Error | null = null
      try {
        const records = Array.from(phaseRecords.values())
        const allCompleted = records.every((p) => p.status === "COMPLETED" || p.status === "PARTIAL")
        // Stage 6.2 item 4: explicit terminal states. A cooperative stop is
        // INTERRUPTED (resumable), never PAUSED and never COMPLETED; a run whose
        // phases are all terminal but not all successful is PARTIAL.
        const finalStatus = executionError
          ? "FAILED"
          : stopped
            ? "INTERRUPTED"
            : allCompleted
              ? "COMPLETED"
              : "PARTIAL"
        store.updateStatus(engagementId, finalStatus)
        await saveRunCheckpoint({
          store,
          engagement: store.getEngagement(engagementId)!,
          bridge,
          plan,
          phases: records,
          target,
          roles: credStore.listRoles(),
          findings: allFindings,
          toolCalls: records.length,
          startedAt: runStartedAt,
          completedAt: new Date().toISOString(),
          limits: {
            maxReplans: configMaxReplans ?? null,
            llmMaxReplans: configLlmMaxReplans ?? null,
            deadlineAt: process.env.ARGUS_DEADLINE_AT ?? null,
          },
          actionDetails: { ...actionDetails },
        })
        store.saveFindings(engagementId, allFindings)
      } catch (err) {
        persistError = err as Error
        emit(`✗ Failed to persist results: ${persistError.message}`)
      }

      // Auto-prune evidence at end of assessment (blocker 61)
      try {
        const { EvidenceCollector } = await import("./evidence/collector")
        const { StoragePaths } = await import("./storage/paths")
        const collector = new EvidenceCollector(StoragePaths.evidenceDir)
        const pruned = await collector.pruneEngagement(engagementId)
        if (pruned > 0) {
          emit(`✓ Pruned ${pruned} stale evidence file(s)`)
        }
      } catch (pruneErr) {
        emit(`⚠ Evidence prune skipped: ${(pruneErr as Error).message}`)
      }

      await bridge.disconnect()

      // A run whose findings could not be saved is not a success — surface it
      // so an unattended driver sees a non-zero exit instead of a clean result
      // over an empty database.
      if (persistError && !executionError) {
        executionError = persistError
      }
      if (!executionError && !stopped) {
        emit({ type: "scan_complete", totalFindings: allFindings.length })
      }
      if (degradations.length > 0) {
        emit(
          `⚠ Assessment ran degraded: ${degradations.length} step(s) skipped or failed — ${degradations.join(" | ")}`,
        )
      }
      emit(`✓ Assessment ${executionError ? "failed" : stopped ? "stopped" : "complete"}`)
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
      success: !executionError && !stopped,
      stopped: stopped || undefined,
      ...(degradations.length > 0 ? { degradations } : {}),
      error: executionError?.message,
      allFindings,
    }
  }

  /**
   * Autonomous assessment loop — runs the whole plan without operator
   * intervention. It plans and replans without the LLM (rule-based and
   * attack-graph chain plans only), and stops only when the cooperative
   * `shouldStop()` signal fires at a phase boundary or when scope enforcement
   * rejects the target.
   *
   * Scope enforcement (ARGUS_AUTONOMOUS=1 requires scope.mode=allowlist with
   * configured allowed_targets) is validated inside run(), so an out-of-scope
   * target still fails the engagement before any phase executes.
   *
   * Requires ARGUS_AUTONOMOUS=1.
   */
  async runAutonomous(
    options: Omit<WorkflowRunOptions, "useLLM" | "shouldStop"> & {
      shouldStop?: () => boolean
    },
  ): Promise<WorkflowRunResult> {
    const isAutonomous =
      process.env.ARGUS_AUTONOMOUS === "1" || process.env.ARGUS_AUTONOMOUS === "true"
    if (!isAutonomous) {
      throw new Error(
        "[Argus] ARGUS_AUTONOMOUS=1 must be set to run an autonomous assessment",
      )
    }

    return this.run({
      ...options,
      useLLM: false,
      shouldStop: options.shouldStop ?? (() => false),
    })
  }
}

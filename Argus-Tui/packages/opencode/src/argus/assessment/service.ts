/**
 * ArgusAssessmentService — the single assessment policy/launch boundary.
 *
 * Slash commands, recognized natural-language requests, and the CLI all enter
 * here. The service owns:
 *   - target validation
 *   - planner-model handoff (the model the operator selected in the TUI)
 *   - engagement resolution (delegated to WorkflowRunner, which creates it once)
 *   - progress fan-out through hooks
 *
 * It deliberately imports no SolidJS, scan store, terminal, or session code.
 * UI and CLI adapters supply hooks, so the same policy drives both surfaces.
 */

import type { CacheMode } from "../bridge/types"
import type { Feature } from "../config/feature-flags"
import type { ProgressEvent } from "../shared/progress"
import type { WorkflowRunner, WorkflowRunResult } from "../workflow-runner"

export type AssessmentMode = "assess" | "recon"

export interface AssessmentRequest {
  target: string
  /** "assess" enables LLM planning; "recon" stays deterministic. */
  mode?: AssessmentMode
  /** Explicit override; takes precedence over `mode`. */
  useLLM?: boolean
  cacheMode?: CacheMode
  verbose?: boolean
  workersPath?: string
  workflowsDir?: string
  credsPath?: string
  features?: Partial<Record<Feature, boolean>>
  /** Reuse an existing engagement instead of creating a fresh one. */
  engagementId?: string
  /** "provider/model" selected by the operator; forwarded to the planner. */
  model?: string
  /** Cooperative stop, checked by the runner before each phase. */
  shouldStop?: () => boolean
}

export interface AssessmentEngagement {
  id: string
  target: string
  created: boolean
}

export interface AssessmentHooks {
  onProgress?: (event: ProgressEvent | string) => void
  onEngagement?: (engagement: AssessmentEngagement) => void
}

export interface AssessmentDeps {
  runner?: Pick<WorkflowRunner, "run">
  switchModel?: (model: string) => void | Promise<void>
}

/**
 * Parse a raw `/assess <target> [flags]` argument string.
 * Shared so the TUI and command registry cannot disagree about flags.
 */
export function parseAssessmentArgs(raw: string): {
  target: string
  cacheMode?: CacheMode
  verbose: boolean
} {
  const tokens = raw.trim().split(/\s+/).filter(Boolean)
  const target = tokens.find((token) => !token.startsWith("--")) ?? ""
  const cacheMode: CacheMode | undefined = tokens.includes("--no-cache")
    ? "no_cache"
    : tokens.includes("--refresh-cache")
      ? "refresh"
      : undefined
  return { target, cacheMode, verbose: tokens.includes("--verbose") }
}

export async function runAssessment(
  request: AssessmentRequest,
  hooks: AssessmentHooks = {},
  deps: AssessmentDeps = {},
): Promise<WorkflowRunResult> {
  const target = request.target?.trim()
  if (!target) throw new Error("An assessment requires an authorized target")

  if (request.model) {
    const switchModel = deps.switchModel ?? (await import("../planner/llm-service")).LLMPlannerService.switchModel
    await switchModel(request.model)
  }

  const useLLM = request.useLLM ?? (request.mode ? request.mode === "assess" : undefined)
  const runner = deps.runner ?? new (await import("../workflow-runner")).WorkflowRunner()
  return runner.run({
    target,
    useLLM,
    cacheMode: request.cacheMode,
    verbose: request.verbose,
    workersPath: request.workersPath,
    workflowsDir: request.workflowsDir,
    credsPath: request.credsPath,
    features: request.features,
    engagementId: request.engagementId,
    shouldStop: request.shouldStop,
    onProgress: hooks.onProgress,
    onEngagement: hooks.onEngagement,
  })
}

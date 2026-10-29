/**
 * TUI adapter for the single assessment service.
 *
 * Structured ProgressEvents go to the scan store; plain progress strings go to
 * the scan log. Assessment output never reaches session.prompt, so a scan can
 * not turn into a coding-agent conversation.
 *
 * Two concurrency rules live here:
 *   - single-flight per target/engagement, so a duplicate submission cannot
 *     start a second run or a second engagement;
 *   - a cooperative stop flag checked by the runner at each phase boundary.
 */

import { runAssessment, type AssessmentDeps, type AssessmentRequest } from "../assessment/service"
import type { WorkflowRunResult } from "../workflow-runner"
import { navigateTo } from "./navigator"
import { appendLog, completeScan, handleProgressEvent, initScan, setPlannerModel } from "./scan-store"

export type TuiAssessmentStatus = "completed" | "partial" | "stopped" | "failed"

export interface TuiAssessmentOutcome {
  result: WorkflowRunResult
  engagementId: string
  status: TuiAssessmentStatus
}

export type TuiAssessmentOptions = AssessmentDeps & {
  /** Skip navigating to the scan route (tests, headless callers). */
  navigate?: boolean
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function runKey(request: AssessmentRequest): string {
  return request.engagementId ?? request.target.trim().toLowerCase()
}

interface Control {
  stop: boolean
}

const controls = new Map<string, Control>()
const inFlight = new Map<string, Promise<TuiAssessmentOutcome>>()

/**
 * Request a cooperative stop at the next phase boundary. With no target, every
 * running assessment is asked to stop. Returns true when at least one run was
 * actually running.
 */
export function requestAssessmentStop(target?: string): boolean {
  const key = target?.trim().toLowerCase()
  let requested = false
  for (const [id, control] of controls) {
    if (key && id !== key) continue
    control.stop = true
    requested = true
  }
  return requested
}

export function isAssessmentRunning(target?: string): boolean {
  if (target === undefined) return controls.size > 0
  return controls.has(target.trim().toLowerCase())
}

export function runTuiAssessment(
  request: AssessmentRequest,
  options: TuiAssessmentOptions = {},
): Promise<TuiAssessmentOutcome> {
  const key = runKey(request)
  const existing = inFlight.get(key)
  if (existing) return existing

  const run = executeTuiAssessment(request, options, key).finally(() => {
    inFlight.delete(key)
    controls.delete(key)
  })
  inFlight.set(key, run)
  return run
}

async function executeTuiAssessment(
  request: AssessmentRequest,
  options: TuiAssessmentOptions,
  key: string,
): Promise<TuiAssessmentOutcome> {
  const control: Control = { stop: false }
  controls.set(key, control)

  let engagementId = request.engagementId ?? ""
  let partial = false
  // Serialize progress so the terminal `completeScan` cannot be overtaken by an
  // in-flight `scan_complete` event and flip a failure back to "completed".
  let queue: Promise<void> = Promise.resolve()
  const enqueue = (work: () => void | Promise<void>) => {
    queue = queue.then(work).catch(() => {})
  }

  let result: WorkflowRunResult
  try {
    result = await runAssessment(
      { ...request, shouldStop: () => control.stop },
      {
        onEngagement(engagement) {
          engagementId = engagement.id
          initScan(engagement.target, engagement.id)
          if (request.model) setPlannerModel(request.model, `ARGUS_PLANNER_MODEL=${request.model}`)
          if (options.navigate !== false) {
            navigateTo({ type: "scan", target: engagement.target, engagementId: engagement.id })
          }
        },
        onProgress(event) {
          if (typeof event !== "string") {
            if (event.type === "phase_error" || (event.type === "phase_complete" && event.status === "PARTIAL")) {
              partial = true
            }
          }
          enqueue(() =>
            typeof event === "string" ? appendLog(event) : handleProgressEvent(event, engagementId || undefined),
          )
        },
      },
      { runner: options.runner, switchModel: options.switchModel },
    )
  } catch (error) {
    await queue
    completeScan("failed")
    appendLog(`Assessment failed: ${message(error)}`)
    throw error
  }

  await queue
  if (!engagementId) engagementId = result.engagementId

  const status: TuiAssessmentStatus = result.stopped
    ? "stopped"
    : !result.success
      ? "failed"
      : partial
        ? "partial"
        : "completed"

  completeScan(status)
  if (status === "failed") appendLog(`Assessment failed: ${result.error ?? "unknown error"}`)
  if (status === "partial") appendLog("Assessment finished with partial coverage")
  if (status === "stopped") appendLog("Assessment stopped at a phase boundary")

  return { result, engagementId, status }
}

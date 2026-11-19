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
import { ReportGenerator, persistedReportOptions } from "../reporting/generator"
import { EngagementStore } from "../engagement/store"
import { appendLog, completeScan, handleProgressEvent, initScan, setPlannerModel, setTotalFindings } from "./scan-store"

export type TuiAssessmentStatus = "completed" | "partial" | "stopped" | "failed"

/**
 * Append a breadcrumb to `<data dir>/tui-assessment-trace.log`.
 *
 * The TUI once finished every phase and then never drew the terminal line: the
 * transcript stopped mid-assessment while the engagement database kept moving.
 * A file survives a frozen renderer, so the next run says where it stopped.
 */
function makeTrace(): (line: string) => void {
  const { appendFileSync } = require("node:fs") as typeof import("node:fs")
  const { join } = require("node:path") as typeof import("node:path")
  const { homedir } = require("node:os") as typeof import("node:os")
  const dir = process.env["ARGUS_DATA_DIR"] || join(homedir(), ".argus")
  const file = join(dir, "tui-assessment-trace.log")
  return (line: string) => {
    try {
      appendFileSync(file, `${new Date().toISOString()} ${line}\n`)
    } catch {
      // Tracing must never break an assessment.
    }
  }
}

/**
 * Keep stray stderr output off the TUI's screen.
 *
 * The renderer owns the terminal, so a plain `process.stderr.write` — the
 * planner's missing-signal warnings, an approval prompt, a tool's own logging —
 * is painted straight over the panels and leaves fragments of text across the
 * scan dashboard. In the TUI those lines are diagnostics, not UI: append them to
 * `<data dir>/tui-stderr.log` and let the renderer keep the terminal.
 */
function redirectStderrForTui(): void {
  if (process.env.ARGUS_MODE !== "1") return
  const { appendFileSync } = require("node:fs") as typeof import("node:fs")
  const { join } = require("node:path") as typeof import("node:path")
  const { homedir } = require("node:os") as typeof import("node:os")
  const dir = process.env["ARGUS_DATA_DIR"] || join(homedir(), ".argus")
  const file = join(dir, "tui-stderr.log")
  const write = (chunk: unknown, ...rest: unknown[]) => {
    try {
      appendFileSync(file, String(chunk))
    } catch {
      // Diagnostics must never break the run.
    }
    const callback = rest.find((entry) => typeof entry === "function")
    if (typeof callback === "function") (callback as () => void)()
    return true
  }
  ;(process.stderr as unknown as { write: typeof write }).write = write
}

redirectStderrForTui()

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
  const trace = makeTrace()

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
          enqueue(() => {
            trace(typeof event === "string" ? `log ${event.slice(0, 80)}` : `event ${event.type}`)
            return typeof event === "string" ? appendLog(event) : handleProgressEvent(event, engagementId || undefined)
          })
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

  // Diagnostic breadcrumb: a run can finish its phases and still never reach
  // the terminal line (the screen froze mid-assessment once and the marker was
  // never drawn), so record the boundary in the data directory next to the
  // engagement it belongs to.
  trace("runAssessment returned")
  await queue
  trace("progress queue drained")
  if (!engagementId) engagementId = result.engagementId

  // A run that skipped or failed steps is not a clean pass: the scan view and
  // the terminal line must say so, otherwise degraded coverage reads as a
  // complete assessment with suspiciously few findings.
  const degradedSteps = result.degradations?.length ?? 0
  const degraded = degradedSteps > 0
  const status: TuiAssessmentStatus = result.stopped
    ? "stopped"
    : !result.success
      ? "failed"
      : partial || degraded
        ? "partial"
        : "completed"

  // The CLI adapter always leaves a markdown report on disk; the TUI used to
  // stop at the rendered dashboard, so a finished TUI assessment had no
  // artifact to read afterwards. Write the same file here (no stdout: that
  // would paint over the view).
  let reportPath: string | undefined
  if (status !== "failed" && engagementId) {
    try {
      const generator = new ReportGenerator()
      const markdown = generator.generateMarkdown(
        result.allFindings,
        engagementId,
        request.target,
        "assessment",
        persistedReportOptions(new EngagementStore(), engagementId),
      )
      reportPath = generator.writeArtifact(engagementId, markdown, "markdown")
      trace(`report written ${reportPath}`)
    } catch (error) {
      appendLog(`Could not write the report artifact: ${message(error)}`)
      trace(`report write failed: ${message(error)}`)
    }
  }

  // Phase counts overlap (one finding can be reported by several phases), so
  // the dashboard total read higher than the report: 119 vs the 43 deduplicated
  // findings in the artifact. Once the run is over the authoritative number is
  // the one the report and the terminal line print.
  setTotalFindings(result.findings)
  completeScan(status)
  trace(`completeScan(${status})`)
  if (reportPath) appendLog(`Report written: ${reportPath}`)
  if (status === "failed") appendLog(`Assessment failed: ${result.error ?? "unknown error"}`)
  if (status === "partial") appendLog("Assessment finished with partial coverage")
  if (degraded) appendLog(`Assessment finished with ${degradedSteps} degraded step(s)`)
  if (status === "stopped") appendLog("Assessment stopped at a phase boundary")
  // Every other outcome prints a terminal line; a clean finish used to print
  // nothing, so anything watching the log for a completion marker (the Gate A
  // harness, an operator reading the transcript) saw the run hang forever even
  // though the scan dashboard had already flipped to COMPLETED.
  const breakdown = `${result.critical} critical, ${result.high} high, ${result.medium} medium`
  const summary = `Assessment complete — ${result.findings} finding(s) (${breakdown})`
  if (status === "completed") appendLog(summary)

  // Also write the terminal line to the terminal itself. The scan screen is a
  // rendered view: when its render loop stops (observed: the screen froze after
  // a mid-run approval while the assessment kept going), a log line that only
  // exists in that view is never drawn and the run looks hung. A line on the
  // terminal is the operator's guarantee that the run ended and how.
  const terminalLine =
    status === "completed"
      ? summary
      : status === "partial"
        ? `Assessment finished — partial coverage${degraded ? ` (${degradedSteps} degraded step(s))` : ""} (${result.findings} finding(s): ${breakdown})`
        : status === "stopped"
          ? `Assessment stopped at a phase boundary (${result.findings} finding(s))`
          : `Assessment failed: ${result.error ?? "unknown error"}`
  process.stderr.write(`\n${terminalLine}\n`)
  trace("terminal line written")

  return { result, engagementId, status }
}

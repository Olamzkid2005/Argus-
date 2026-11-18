import { runAssessment } from "../assessment/service"
import type { WorkflowRunResult } from "../workflow-runner"
import { ReportGenerator, persistedReportOptions } from "../reporting/generator"
import { EngagementStore } from "../engagement/store"
import type { Feature } from "../config/feature-flags"
import type { ProgressEvent } from "../shared/progress"
import { cliProgress } from "./progress"

export async function assessCommand(target: string, options?: {
  workersPath?: string
  useLLM?: boolean
  credsPath?: string
  cacheMode?: "normal" | "no_cache" | "refresh"
  verbose?: boolean
  features?: Partial<Record<Feature, boolean>>
  onProgress?: (event: ProgressEvent | string) => void
  /**
   * When true (default for CLI, false for TUI), writes a markdown summary
   * to stdout after the assessment completes. TUI callers should set this
   * to false to avoid raw markdown polluting the terminal UI.
   */
  writeReport?: boolean
  /** Cooperative cancellation, checked by the runner at each phase boundary. */
  shouldStop?: () => boolean
}): Promise<WorkflowRunResult> {
  const result = await runAssessment(
    {
      target,
      useLLM: options?.useLLM,
      workersPath: options?.workersPath,
      credsPath: options?.credsPath,
      cacheMode: options?.cacheMode,
      verbose: options?.verbose,
      features: options?.features,
      shouldStop: options?.shouldStop,
    },
    { onProgress: options?.onProgress ?? cliProgress },
  )

  // Render once and always leave the report on disk — stdout is easy to lose in
  // an unattended run, and "0 findings" is exactly when an artifact matters.
  const reportGen = new ReportGenerator()
  const store = new EngagementStore()
  const report = reportGen.generateMarkdown(result.allFindings, result.engagementId, target, "assessment", persistedReportOptions(store, result.engagementId))
  try {
    const reportPath = reportGen.writeArtifact(result.engagementId, report, "markdown")
    process.stderr.write(`\n✓ Report written: ${reportPath}\n`)
  } catch (err) {
    process.stderr.write(`\n⚠ Could not write the report artifact: ${(err as Error).message}\n`)
  }

  // Keep stdout clean for piping/redirecting, and unchanged for TUI callers.
  if (result.allFindings.length > 0 && (options?.writeReport ?? true)) {
    process.stdout.write(report + "\n")
  }

  return result
}

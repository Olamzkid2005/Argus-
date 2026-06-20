import { WorkflowRunner, type WorkflowRunResult } from "../workflow-runner"
import { ReportGenerator } from "../reporting/generator"
import type { Feature } from "../config/feature-flags"
import type { ProgressEvent } from "../shared/progress"

/**
 * Default CLI progress callback — prints workflow phase info to stderr
 * so the final report (stdout) stays clean for piping/redirecting.
 */
function cliProgress(event: ProgressEvent | string): void {
  if (typeof event === "string") {
    process.stderr.write(event + "\n")
    return
  }
  switch (event.type) {
    case "phase_start": {
      process.stderr.write(`
── Phase ${event.phaseIndex + 1}/${event.total}: ${event.name} ──
`)
      break
    }
    case "phase_complete":
      process.stderr.write(`  ✓ ${event.findings} finding(s)\n`)
      break
    case "phase_error":
      process.stderr.write(`  ✗ ${event.error}\n`)
      break
    case "finding": {
      const sevLabel = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][parseInt(event.severity)] ?? event.severity
      process.stderr.write(`  • [${sevLabel}] ${event.title}\n`)
      break
    }
    case "phase_replan":
      process.stderr.write(`  ⤵ Replanning: ${event.count} new phase(s) inserted\n`)
      break
    case "scan_complete":
      process.stderr.write(`
✓ Assessment complete — ${event.totalFindings} total finding(s)\n`)
      break
    default:
      break
  }
}

export async function assessCommand(target: string, options?: {
  workersPath?: string
  useLLM?: boolean
  credsPath?: string
  cacheMode?: "normal" | "no_cache" | "refresh"
  features?: Partial<Record<Feature, boolean>>
  onProgress?: (event: ProgressEvent | string) => void
  /**
   * When true (default for CLI, false for TUI), writes a markdown summary
   * to stdout after the assessment completes. TUI callers should set this
   * to false to avoid raw markdown polluting the terminal UI.
   */
  writeReport?: boolean
}): Promise<WorkflowRunResult> {
  const runner = new WorkflowRunner()
  const result = await runner.run({
    target,
    useLLM: options?.useLLM,
    workersPath: options?.workersPath,
    credsPath: options?.credsPath,
    cacheMode: options?.cacheMode,
    features: options?.features,
    onProgress: options?.onProgress ?? cliProgress,
  })

  if (result.allFindings.length > 0 && (options?.writeReport ?? true)) {
    const reportGen = new ReportGenerator()
    const report = reportGen.generateMarkdown(result.allFindings, result.engagementId, target, "assessment")
    process.stdout.write(report + "\n")
  }

  return result
}

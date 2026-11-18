import type { ProgressEvent } from "../shared/progress"

/**
 * Default CLI progress callback — prints workflow phase info to stderr
 * so the final report (stdout) stays clean for piping/redirecting.
 *
 * Shared by `assess` and `resume`: a resumed run must describe its progress
 * (including degraded steps) exactly the way a fresh assessment does.
 */
export function cliProgress(event: ProgressEvent | string): void {
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

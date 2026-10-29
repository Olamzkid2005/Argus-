/**
 * Argus — Security Assessment Platform
 *
 * Primary entry point for the Argus CLI and TUI.
 *
 * Usage:
 *   argus                        Launch Argus TUI (interactive dashboard)
 *   argus doctor                 Run health checks
 *   argus assess <target>        Run full assessment
 *   argus --help                 Show this help
 *
 * The TUI is powered by OpenCode's SolidJS terminal UI framework
 * (@opentui/solid) with Argus branding and routes. When ARGUS_MODE=1,
 * the TUI shows ArgusDashboard, ScanDashboard, FindingsViewer, and
 * other Argus-specific screens instead of the default OpenCode home.
 */
import yargs from "yargs"
import { hideBin } from "yargs/helpers"
import { EOL } from "os"
import { launchTui } from "./launcher"
import {
  ArgusAssessCommand,
  ArgusDoctorCommand,
  ArgusReportCommand,
  ArgusResumeCommand,
  ArgusVerifyCommand,
  ArgusEvidenceCommand,
  ArgusConfigCommand,
  ArgusEncryptionCommand,
  ArgusToolsCommand,
  ArgusFindingsCommand,
  ArgusEngagementsCommand,
  ArgusWorkflowsCommand,
} from "./cli"
import { UI } from "./ui"
import { formatCliHelp } from "./tui-commands"

const args = hideBin(process.argv)

function show(out: string) {
  process.stderr.write(UI.logo() + EOL + EOL)
  process.stderr.write(out)
}

/** Wait until everything written to a stream has been handed to the OS. */
function drain(stream: { write(chunk: string, callback: () => void): unknown }): Promise<void> {
  return new Promise((resolve) => stream.write("", () => resolve()))
}

/**
 * Exit once a one-shot command is done.
 *
 * Some commands lazily boot OpenCode's runtime to read the provider registry
 * (the planner check in `doctor` does). That runtime owns long-lived watchers
 * and timers by design, so the event loop never drains on its own and the
 * command would appear to hang after printing its results. Flush the streams
 * first so nothing is truncated, then exit with the status the command set.
 */
async function exitWhenDone(): Promise<never> {
  await Promise.all([drain(process.stdout), drain(process.stderr)])
  process.exit(process.exitCode ?? 0)
}

async function main(): Promise<boolean> {
  if (args.length === 0 || (args[0].startsWith("-") && !["--help", "-h", "--version", "-v"].includes(args[0]))) {
    // No arguments: launch the rich TUI directly.
    // The TUI's home route shows ArgusDashboard (via ARGUS_MODE=1) with
    // stats loaded from the engagement store, so no need to pre-render here.
    launchTui(args)
    return false
  } else if (args[0] === "--help" || args[0] === "-h") {
    show(formatCliHelp())
    return true
  } else {
    const cli = yargs(args)
      .scriptName("argus")
      .wrap(100)
      .help("help", "show help")
      .alias("help", "h")
      .version("version", "show version number", "5.0.0")
      .alias("version", "v")
      .usage("")
      .command(ArgusAssessCommand)
      .command(ArgusDoctorCommand)
      .command(ArgusReportCommand)
      .command(ArgusResumeCommand)
      .command(ArgusVerifyCommand)
      .command(ArgusEvidenceCommand)
      .command(ArgusFindingsCommand)
      .command(ArgusConfigCommand)
      .command(ArgusEncryptionCommand)
      .command(ArgusToolsCommand)
      .command(ArgusEngagementsCommand)
      .command(ArgusWorkflowsCommand)
      .fail((msg, err) => {
        if (err) throw err
        cli.showHelp(show)
      })
      .strict()
    await cli.parse()
    return true
  }
}

main()
  .then(async (oneShot) => {
    if (oneShot) await exitWhenDone()
  })
  .catch(async (e) => {
    const message = e instanceof Error ? e.message : String(e)
    UI.error(message)
    process.exitCode = 1
    await exitWhenDone()
  })

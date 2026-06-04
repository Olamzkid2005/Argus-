/**
 * Argus — Security Assessment Platform
 *
 * Primary entry point for the Argus CLI and TUI.
 *
 * Usage:
 *   argus                        Launch Argus TUI
 *   argus doctor                 Run health checks
 *   argus assess <target>        Run full assessment
 *   argus --help                 Show this help
 *
 * This file replaces `src/index.ts` as the user-facing binary.
 * OpenCode's `src/index.ts` remains available for development.
 */

import yargs from "yargs"
import { hideBin } from "yargs/helpers"
import { EOL } from "os"
import {
  ArgusAssessCommand,
  ArgusDoctorCommand,
  ArgusReportCommand,
  ArgusResumeCommand,
  ArgusVerifyCommand,
  ArgusEvidenceCommand,
  ArgusConfigCommand,
} from "./cli"
import { UI } from "./ui"

const args = hideBin(process.argv)

function show(out: string) {
  process.stderr.write(UI.logo() + EOL + EOL)
  process.stderr.write(out)
}

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
  .command(ArgusConfigCommand)
  .fail((msg, err) => {
    if (err) throw err
    cli.showHelp(show)
  })
  .strict()

try {
  if (args.length === 0) {
    // No arguments: show splash + help
    cli.showHelp(show)
  } else if (args.includes("-h") || args.includes("--help")) {
    await cli.parse(args, (err: Error | undefined, _argv: unknown, out: string) => {
      if (err) throw err
      if (!out) return
      show(out)
    })
  } else {
    await cli.parse()
  }
} catch (e) {
  const message = e instanceof Error ? e.message : String(e)
  UI.error(message)
  process.exitCode = 1
}

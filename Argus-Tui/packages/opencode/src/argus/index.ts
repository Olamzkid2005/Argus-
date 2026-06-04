/**
 * Argus — Security Assessment Platform
 *
 * Primary entry point for the Argus CLI and TUI.
 *
 * Usage:
 *   argus                        Launch Argus TUI (interactive)
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
import { spawn } from "child_process"
import { fileURLToPath } from "url"
import { dirname, join } from "path"
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
import { formatCliHelp } from "./tui-commands"

const args = hideBin(process.argv)

function show(out: string) {
  process.stderr.write(UI.logo() + EOL + EOL)
  process.stderr.write(out)
}

/**
 * Launch the interactive Argus TUI (OpenCode TUI with Argus branding).
 */
function launchTui() {
  const __dirname = typeof __dirname !== "undefined"
    ? __dirname
    : dirname(fileURLToPath(import.meta.url))
  const entry = join(__dirname, "../../src/index.ts")

  const child = spawn("bun", ["run", "--conditions=browser", entry, "run", "--interactive"], {
    stdio: "inherit",
    env: { ...process.env, ARGUS_MODE: "1" },
  })

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal)
      return
    }
    process.exit(typeof code === "number" ? code : 0)
  })
}

try {
  if (args.length === 0) {
    // No arguments: launch the interactive TUI
    launchTui()
  } else if (args[0] === "--help" || args[0] === "-h") {
    show(formatCliHelp())
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
      .command(ArgusConfigCommand)
      .fail((msg, err) => {
        if (err) throw err
        cli.showHelp(show)
      })
      .strict()
    await cli.parse()
  }
} catch (e) {
  const message = e instanceof Error ? e.message : String(e)
  UI.error(message)
  process.exitCode = 1
}

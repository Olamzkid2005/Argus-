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

/**
 * Launch the interactive Argus TUI (OpenCode TUI with Argus branding).
 *
 * The TUI uses SolidJS via @opentui/solid for a rich terminal interface.
 * When ARGUS_MODE=1, the home screen shows ArgusDashboard and all
 * Argus routes (scan, findings, engagements, workspace) are available.
 */
function launchTui() {
  const _dirname = dirname(fileURLToPath(import.meta.url))
  const entry = join(_dirname, "../../src/index.ts")
  const pkgDir = join(_dirname, "../..")

  const child = spawn("bun", ["run", "--conditions=browser", entry, "run", "--interactive"], {
    stdio: "inherit",
    cwd: pkgDir,
    env: { ...process.env, ARGUS_MODE: "1" },
  })

  child.on("error", (err) => {
    console.error("Failed to launch TUI:", err.message)
    process.exit(1)
  })

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal)
      return
    }
    process.exit(typeof code === "number" ? code : 0)
  })
}

async function main() {
  if (args.length === 0) {
    // No arguments: launch the rich TUI directly.
    // The TUI's home route shows ArgusDashboard (via ARGUS_MODE=1) with
    // stats loaded from the engagement store, so no need to pre-render here.
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
      .command(ArgusFindingsCommand)
      .command(ArgusConfigCommand)
      .command(ArgusToolsCommand)
      .command(ArgusEngagementsCommand)
      .command(ArgusWorkflowsCommand)
      .fail((msg, err) => {
        if (err) throw err
        cli.showHelp(show)
      })
      .strict()
    await cli.parse()
  }
}

main().catch((e) => {
  const message = e instanceof Error ? e.message : String(e)
  UI.error(message)
  process.exitCode = 1
})

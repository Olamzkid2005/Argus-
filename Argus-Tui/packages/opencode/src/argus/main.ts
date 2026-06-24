/**
 * Argus CLI entry point.
 * Wires command definitions into yargs and parses process.argv.
 * Run: bun run src/argus/main.ts <command> [options]
 *
 * NOTE: .env files are auto-loaded by Bun; for Node.js runtimes,
 * add `import "dotenv/config"` here (requires dotenv dependency).
 */
import yargs from "yargs"
import { hideBin } from "yargs/helpers"
import {
  ArgusAssessCommand,
  ArgusDoctorCommand,
  ArgusReportCommand,
  ArgusResumeCommand,
  ArgusVerifyCommand,
  ArgusEvidenceCommand,
  ArgusConfigCommand,
  ArgusEngagementsCommand,
  ArgusFindingsCommand,
  ArgusWorkflowsCommand,
  ArgusToolsCommand,
} from "./cli"

yargs(hideBin(process.argv))
  .scriptName("argus")
  .command(ArgusAssessCommand)
  .command(ArgusDoctorCommand)
  .command(ArgusReportCommand)
  .command(ArgusResumeCommand)
  .command(ArgusVerifyCommand)
  .command(ArgusEvidenceCommand)
  .command(ArgusConfigCommand)
  .command(ArgusEngagementsCommand)
  .command(ArgusFindingsCommand)
  .command(ArgusWorkflowsCommand)
  .command(ArgusToolsCommand)
  .demandCommand(1, "Usage: argus <command> [options]\n\nCommands: assess, doctor, report, resume, verify, evidence, config, engagements, findings, workflows, tools")
  .strict()
  .help()
  .parse()

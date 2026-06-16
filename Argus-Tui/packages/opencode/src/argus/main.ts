/**
 * Argus CLI entry point.
 * Wires command definitions into yargs and parses process.argv.
 * Run: bun run src/argus/main.ts <command> [options]
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
  .command(ArgusAssessCommand as any)
  .command(ArgusDoctorCommand as any)
  .command(ArgusReportCommand as any)
  .command(ArgusResumeCommand as any)
  .command(ArgusVerifyCommand as any)
  .command(ArgusEvidenceCommand as any)
  .command(ArgusConfigCommand as any)
  .command(ArgusEngagementsCommand as any)
  .command(ArgusFindingsCommand as any)
  .command(ArgusWorkflowsCommand as any)
  .command(ArgusToolsCommand as any)
  .demandCommand(1, "Usage: argus <command> [options]\n\nCommands: assess, doctor, report, resume, verify, evidence, config, engagements, findings, workflows, tools")
  .strict()
  .help()
  .parse()

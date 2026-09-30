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
  ArgusEncryptionCommand,
  ArgusEngagementsCommand,
  ArgusFindingsCommand,
  ArgusWorkflowsCommand,
  ArgusToolsCommand,
} from "./cli"

const cli = yargs(hideBin(process.argv))
  .scriptName("argus")
  .command(ArgusAssessCommand)
  .command(ArgusDoctorCommand)
  .command(ArgusReportCommand)
  .command(ArgusResumeCommand)
  .command(ArgusVerifyCommand)
  .command(ArgusEvidenceCommand)
  .command(ArgusConfigCommand)
  .command(ArgusEncryptionCommand)
  .command(ArgusEngagementsCommand)
  .command(ArgusFindingsCommand)
  .command(ArgusWorkflowsCommand)
  .command(ArgusToolsCommand)
  .demandCommand(1, "Usage: argus <command> [options]\n\nCommands: assess, doctor, report, resume, verify, evidence, config, encryption, engagements, findings, workflows, tools")
  .strict()
  .help()

// `parseAsync` so async handlers finish before cleanup.
await cli.parseAsync()

// Reading OpenCode's provider registry boots its managed Effect runtime.
// This CLI owns the process, so release it — otherwise the process will not
// terminate once anything has consulted the registry.
try {
  const { disposePlannerRuntime } = await import("./planner/model-registry")
  await disposePlannerRuntime()
} catch {
  // Cleanup is best-effort; a disposed/absent runtime must not mask the command result.
}

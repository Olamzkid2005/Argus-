import type { Argv } from "yargs"
import { assessCommand } from "./commands/assess"
import { doctorCommand } from "./commands/doctor"
import { reportCommand } from "./commands/report"
import { resumeCommand } from "./commands/resume"

export const ArgusAssessCommand = {
  command: "assess <target>",
  describe: "Run a full autonomous security assessment against a target",
  builder: (yargs: Argv) =>
    yargs
      .positional("target", { describe: "Target URL to assess", type: "string", demandOption: true })
      .option("workers-path", { describe: "Path to the MCP worker script" })
      .option("creds", { describe: "Path to credentials JSON file (see credentials.json.example)", type: "string" })
      .option("deterministic", { describe: "Use deterministic mode only (no LLM)", type: "boolean", default: false }),
  handler: async (argv: Record<string, unknown>) => {
    const target = argv.target as string
    process.stderr.write(`[Argus] Starting assessment against: ${target}\n`)
    await assessCommand(target, { useLLM: !argv.deterministic, credsPath: argv.creds as string | undefined })
  },
}

export const ArgusDoctorCommand = {
  command: "doctor",
  describe: "Run comprehensive health checks on the Argus runtime",
  handler: async () => {
    const results = await doctorCommand()
    let passes = 0, warns = 0, fails = 0
    for (const r of results) {
      const icon = r.status === "PASS" ? "✓" : r.status === "WARN" ? "⚠" : "✗"
      process.stdout.write(`${icon} [${r.name}] ${r.message}\n`)
      if (r.status === "PASS") passes++
      else if (r.status === "WARN") warns++
      else fails++
    }
    process.stdout.write(`\n${passes} passed, ${warns} warnings, ${fails} failed\n`)
    if (fails > 0) process.exitCode = 1
  },
}

export const ArgusReportCommand = {
  command: "report <engagement-id>",
  describe: "Generate a report for a completed engagement",
  builder: (yargs: Argv) =>
    yargs
      .positional("engagement-id", { describe: "Engagement ID", type: "string", demandOption: true })
      .option("format", { describe: "Output format", choices: ["markdown", "json", "sarif"] as const, default: "markdown" }),
  handler: async (argv: Record<string, unknown>) => {
    const id = argv.engagementId as string
    const format = argv.format as "markdown" | "json" | "sarif"
    const output = await reportCommand(id, format)
    process.stdout.write(output + "\n")
  },
}

export const ArgusResumeCommand = {
  command: "resume <engagement-id>",
  describe: "Resume a paused or running engagement",
  builder: (yargs: Argv) =>
    yargs.positional("engagement-id", { describe: "Engagement ID", type: "string", demandOption: true }),
  handler: async (argv: Record<string, unknown>) => {
    const id = argv.engagementId as string
    const result = await resumeCommand(id)
    process.stdout.write(result + "\n")
  },
}

import type { Argv } from "yargs"
import { assessCommand } from "./commands/assess"
import { doctorCommand } from "./commands/doctor"
import { reportCommand } from "./commands/report"
import { resumeCommand } from "./commands/resume"
import { verifyCommand } from "./commands/verify"
import { evidenceCommand } from "./commands/evidence"
import { configCommand } from "./commands/config"

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
      .catch((e: Error) => process.stderr.write(`[Argus] assess error: ${e.message}\n`))
  },
}

export const ArgusDoctorCommand = {
  command: "doctor",
  describe: "Run comprehensive health checks on the Argus runtime",
  builder: (yargs: Argv) =>
    yargs.option("online", { describe: "Run network-dependent checks (LLM provider)", type: "boolean", default: false }),
  handler: async (argv: Record<string, unknown>) => {
    const results = await doctorCommand({ online: argv.online as boolean }).catch((e: Error) => {
      process.stderr.write(`[Argus] doctor error: ${e.message}\n`)
      return []
    })
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
    try {
      const output = await reportCommand(id, format)
      process.stdout.write(output + "\n")
    } catch (e) {
      process.stderr.write(`[Argus] report error: ${(e as Error).message}\n`)
    }
  },
}

export const ArgusResumeCommand = {
  command: "resume <engagement-id>",
  describe: "Resume a paused or running engagement",
  builder: (yargs: Argv) =>
    yargs.positional("engagement-id", { describe: "Engagement ID", type: "string", demandOption: true }),
  handler: async (argv: Record<string, unknown>) => {
    const id = argv.engagementId as string
    try {
      const result = await resumeCommand(id)
      process.stdout.write(result + "\n")
    } catch (e) {
      process.stderr.write(`[Argus] resume error: ${(e as Error).message}\n`)
    }
  },
}

export const ArgusVerifyCommand = {
  command: "verify <finding-id>",
  describe: "Re-run browser verification for a specific finding",
  builder: (yargs: Argv) =>
    yargs
      .positional("finding-id", { describe: "Finding ID to verify", type: "string", demandOption: true })
      .option("target", { describe: "Target URL override", type: "string" })
      .option("creds", { describe: "Path to credentials JSON file", type: "string" }),
  handler: async (argv: Record<string, unknown>) => {
    const findingId = argv.findingId as string
    const output = await verifyCommand(findingId, {
      targetUrl: argv.target as string | undefined,
      credsPath: argv.creds as string | undefined,
    }).catch((e: Error) => `[Argus] verify error: ${e.message}`)
    process.stdout.write(output + "\n")
  },
}

export const ArgusEvidenceCommand = {
  command: "evidence <action> [args..]",
  describe: "Browse and manage captured evidence",
  builder: (yargs: Argv) =>
    yargs
      .positional("action", {
        describe: "Action: list, show <package-id>, prune [keep-last], verify-package <package-id>",
        type: "string", demandOption: true,
      })
      .positional("args", { describe: "Arguments for the action", type: "string", array: true }),
  handler: async (argv: Record<string, unknown>) => {
    const action = argv.action as string
    const args = (argv.args as string[]) ?? []
    const output = await evidenceCommand(action as any, args)
      .catch((e: Error) => `[Argus] evidence error: ${e.message}`)
    process.stdout.write(output + "\n")
  },
}

export const ArgusConfigCommand = {
  command: "config [filter]",
  describe: "Show effective Argus configuration",
  builder: (yargs: Argv) =>
    yargs.positional("filter", { describe: "Optional filter string", type: "string" }),
  handler: async (argv: Record<string, unknown>) => {
    const filter = argv.filter as string | undefined
    const output = await configCommand(filter)
      .catch((e: Error) => `[Argus] config error: ${e.message}`)
    process.stdout.write(output + "\n")
  },
}

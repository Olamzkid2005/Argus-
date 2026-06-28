import type { Argv } from "yargs"
import { assessCommand } from "./commands/assess"
import { doctorCommand } from "./commands/doctor"
import { reportCommand } from "./commands/report"
import { resumeCommand } from "./commands/resume"
import type { ProgressCallback } from "./shared/progress"
import { verifyCommand } from "./commands/verify"
import { evidenceCommand } from "./commands/evidence"
import { configCommand } from "./commands/config"
import { encryptionCommand } from "./commands/encryption"
import { Feature, getFeatureFlags } from "./config/feature-flags"
import { MCP_WORKER_PATH } from "./shared/path"

export const ArgusAssessCommand = {
  command: "assess <target>",
  describe: "Run a full autonomous security assessment against a target",
  builder: (yargs: Argv) =>
    yargs
      .positional("target", { describe: "Target URL to assess", type: "string", demandOption: true })
      .option("workers-path", { describe: "Path to the MCP worker script" })
      .option("creds", { describe: "Path to credentials JSON file (see credentials.json.example)", type: "string" })
      .option("deterministic", { describe: "Use deterministic mode only (no LLM)", type: "boolean", default: false })
      .option("no-cache", { describe: "Skip cache reads and writes (fresh scan)", type: "boolean", default: false })
      .option("refresh-cache", { describe: "Skip cache reads but still write results (refresh stale data)", type: "boolean", default: false })
      .option("verbose", { describe: "Enable verbose executor logging with detailed tool execution info", type: "boolean", default: false })
      // Task 4.1: Feature flags — all opt-in
      .option("enable-workflow-registry", { describe: "Enable workflow registry for capability-based planning", type: "boolean", default: undefined })
      .option("enable-engagement-store", { describe: "Enable SQLite engagement persistence", type: "boolean", default: undefined })
      .option("enable-approval-gates", { describe: "Enable interactive approval prompts for destructive actions", type: "boolean", default: undefined }),
  handler: async (argv: Record<string, unknown>) => {
    const target = argv.target as string
    process.stderr.write(`[Argus] Starting assessment against: ${target}\n`)

    // Warn if all feature flags are disabled (degraded mode)
    const flags = getFeatureFlags()
    if (flags.isDegradedMode()) {
      process.stderr.write("[Argus] WARNING: All feature flags are disabled — running in degraded mode.\n")
    }

    // Build feature flag overrides from CLI
    const featureOverrides: Partial<Record<Feature, boolean>> = {}
    const cliFeatureMap: Record<string, Feature> = {
      "enable-workflow-registry": Feature.WORKFLOW_REGISTRY,
      "enable-engagement-store": Feature.ENGAGEMENT_STORE,
      "enable-approval-gates": Feature.APPROVAL_GATES,
    }
    for (const [cliKey, feature] of Object.entries(cliFeatureMap)) {
      const val = argv[cliKey]
      if (typeof val === "boolean") {
        featureOverrides[feature] = val
      }
    }

    await assessCommand(target, {
      useLLM: !argv.deterministic,
      cacheMode: argv.noCache ? "no_cache" as const : argv.refreshCache ? "refresh" as const : undefined,
      verbose: argv.verbose as boolean,
      credsPath: argv.creds as string | undefined,
      features: featureOverrides,
    }).catch((e: Error) => process.stderr.write(`[Argus] assess error: ${e.message}\n`))
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
      .option("format", { describe: "Output format", choices: ["markdown", "json", "sarif", "html"] as const, default: "markdown" }),
  handler: async (argv: Record<string, unknown>) => {
    const id = argv.engagementId as string
    const format = argv.format as "markdown" | "json" | "sarif" | "html"
    try {
      // Wire progress to stderr for CLI visibility
      const onProgress: ProgressCallback = (event) => {
        if (event.type === "analysis_progress") {
          process.stderr.write(`\r[Argus] Analyzing findings: ${event.current}/${event.total}`)
          if (event.current === event.total) {
            process.stderr.write("\n")
          }
        }
      }
      const output = await reportCommand(id, format, undefined, onProgress)
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
        choices: ["list", "show", "prune", "verify-package"] as const,
      })
      .positional("args", { describe: "Arguments for the action", type: "string", array: true }),
  handler: async (argv: Record<string, unknown>) => {
    const action = argv.action as "list" | "show" | "prune" | "verify-package"
    const args = (argv.args as string[]) ?? []
    const output = await evidenceCommand(action, args)
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

export const ArgusEncryptionCommand = {
  command: "encryption <action>",
  describe: "Manage encryption-at-rest (master key lifecycle)",
  builder: (yargs: Argv) =>
    yargs
      .positional("action", {
        describe: "Action: init, status, on, off, export, import, decrypt",
        type: "string", demandOption: true,
        choices: ["init", "status", "on", "off", "export", "import", "decrypt"] as const,
      })
      .option("passphrase", {
        describe: "Passphrase for key export/import",
        type: "string",
      })
      .option("output", {
        describe: "Output file path for key export, or output directory for decrypt",
        type: "string",
      })
      .option("input", {
        describe: "Input file path for key import",
        type: "string",
      })
      .option("engagement", {
        describe: "Engagement ID to decrypt (required for decrypt action)",
        type: "string",
      }),
  handler: async (argv: Record<string, unknown>) => {
    const action = argv.action as "init" | "status" | "on" | "off" | "export" | "import" | "decrypt"
    const passphrase = argv.passphrase as string | undefined
    const output = argv.output as string | undefined
    const input = argv.input as string | undefined
    const engagement = argv.engagement as string | undefined
    const result = await encryptionCommand(action, { passphrase, output, input, engagement })
      .catch((e: Error) => `[Argus] encryption error: ${e.message}`)
    process.stdout.write(result + "\n")
  },
}

export const ArgusDecryptCommand = {
  command: "decrypt",
  describe: "Emergency plaintext export of an encrypted engagement database",
  builder: (yargs: Argv) =>
    yargs
      .option("engagement", {
        alias: "e",
        describe: "Engagement ID to decrypt",
        type: "string",
        demandOption: true,
      })
      .option("output", {
        alias: "o",
        describe: "Output directory for the decrypted SQLite file",
        type: "string",
        demandOption: true,
      }),
  handler: async (argv: Record<string, unknown>) => {
    const engagement = argv.engagement as string
    const output = argv.output as string
    const result = await encryptionCommand("decrypt", { engagement, output })
      .catch((e: Error) => `[Argus] decrypt error: ${e.message}`)
    process.stdout.write(result + "\n")
  },
}

export const ArgusEngagementsCommand = {
  command: "engagements",
  describe: "List all saved engagements/assessments",
  builder: (yargs: Argv) =>
    yargs.option("id", { describe: "Filter by engagement ID", type: "string" })
      .option("status", { describe: "Filter by status (CREATED, RUNNING, COMPLETED, FAILED, PAUSED)", type: "string" })
      .option("json", { describe: "Output as JSON", type: "boolean", default: false }),
  handler: async (argv: Record<string, unknown>) => {
    const { EngagementStore } = await import("./engagement/store")
    const store = new EngagementStore()
    const engagements = store.listEngagements()

    if (engagements.length === 0) {
      process.stdout.write("No engagements found.\n")
      return
    }

    const filterId = argv.id as string | undefined
    const filterStatus = argv.status as string | undefined
    const asJson = argv.json as boolean

    let filtered = engagements
    if (filterId) filtered = filtered.filter(e => e.id.toLowerCase().includes(filterId.toLowerCase()))
    if (filterStatus) filtered = filtered.filter(e => e.status.toUpperCase() === filterStatus.toUpperCase())

    if (filtered.length === 0) {
      process.stdout.write("No engagements match the filter.\n")
      return
    }

    if (asJson) {
      process.stdout.write(JSON.stringify(filtered, null, 2) + "\n")
      return
    }

    const statusIcon = (s: string) =>
      s === "COMPLETED" ? "✓" : s === "RUNNING" ? "⟳" : s === "FAILED" ? "✗" : s === "PAUSED" ? "⏸" : "○"

    const header = `${"ID".padEnd(16)} ${"Status".padEnd(12)} ${"Target".padEnd(40)} Created`
    const sep = "─".repeat(80)
    process.stdout.write(`Engagements (${filtered.length}):\n${sep}\n${header}\n${sep}\n`)
    for (const e of filtered) {
      const icon = statusIcon(e.status)
      const dateStr = e.createdAt ? new Date(e.createdAt).toLocaleDateString() : ""
      process.stdout.write(`  ${icon} ${e.id.padEnd(14)} ${e.status.padEnd(10)} ${(e.target ?? "").padEnd(40)} ${dateStr}\n`)
    }
    process.stdout.write(`\n${sep}\n`)
    process.stdout.write(`Run \`argus report ${filtered[0]?.id ?? "<id>"}\` for a full report.\n`)
  },
}

export const ArgusFindingsCommand = {
  command: "findings [engagement-id]",
  describe: "List findings from an engagement or the most recent one",
  builder: (yargs: Argv) =>
    yargs
      .positional("engagement-id", { describe: "Engagement ID (optional — uses latest if omitted)", type: "string" })
      .option("severity", { describe: "Filter by severity (info, low, medium, high, critical)", type: "string" })
      .option("status", { describe: "Filter by status (PENDING, CONFIRMED, DISMISSED)", type: "string" })
      .option("json", { describe: "Output as JSON", type: "boolean", default: false }),
  handler: async (argv: Record<string, unknown>) => {
    const { EngagementStore } = await import("./engagement/store")
    const store = new EngagementStore()
    const engId = argv.engagementId as string | undefined
    const filterSev = argv.severity as string | undefined
    const filterStatus = argv.status as string | undefined
    const asJson = argv.json as boolean

    let engagementId = engId
    if (!engagementId) {
      const engagements = store.listEngagements()
      if (engagements.length === 0) {
        process.stdout.write("No engagements found. Run `argus assess <target>` first.\n")
        return
      }
      engagementId = engagements[0].id
    }

    const engagement = store.getEngagement(engagementId)
    if (!engagement) {
      process.stdout.write(`Engagement not found: ${engagementId}\n`)
      return
    }

    let findings = store.getFindings(engagementId)

    const sevMap: Record<string, number> = { info: 0, low: 1, medium: 2, high: 3, critical: 4 }
    if (filterSev) {
      const sev = sevMap[filterSev.toLowerCase()]
      if (sev !== undefined) findings = findings.filter(f => f.severity === sev)
    }
    if (filterStatus) {
      findings = findings.filter(f => f.status?.toUpperCase() === filterStatus.toUpperCase())
    }

    if (findings.length === 0) {
      process.stdout.write(`No findings for ${engagementId}${filterSev ? ` (severity: ${filterSev})` : ""}${filterStatus ? ` (status: ${filterStatus})` : ""}\n`)
      return
    }

    if (asJson) {
      process.stdout.write(JSON.stringify(findings, null, 2) + "\n")
      return
    }

    const sevLabel = (s: number) => ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][s] ?? "UNKNOWN"
    const sevColor = (s: number) => s >= 4 ? "✗" : s >= 3 ? "!" : s >= 2 ? "•" : "·"
    const confLabel = (c: number) => ["INFO", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"][c] ?? "UNKNOWN"

    const header = `${"Severity".padEnd(10)} ${"Finding".padEnd(50)} ${"Tool".padEnd(15)} ${"Confidence"}`
    const sep = "─".repeat(80)
    process.stdout.write(`Findings for ${engagement.target} (${engagementId}): ${findings.length} total\n${sep}\n${header}\n${sep}\n`)
    for (const f of findings) {
      const sev = sevLabel(f.severity)
      const icon = sevColor(f.severity)
      const title = (f.title ?? "").length > 48 ? (f.title ?? "").substring(0, 45) + "..." : (f.title ?? "")
      const conf = confLabel(f.confidence)
      process.stdout.write(`  ${icon} ${sev.padEnd(8)} ${title.padEnd(50)} ${(f.tool ?? "").padEnd(15)} ${conf}\n`)
    }
    process.stdout.write(`\n${sep}\n`)
    process.stdout.write(`Run \`argus verify ${findings[0]?.id ?? "<id>"}\` to verify a finding.\n`)
  },
}

export const ArgusWorkflowsCommand = {
  command: "workflows",
  describe: "List all loaded workflow definitions",
  builder: (yargs: Argv) =>
    yargs.option("json", { describe: "Output as JSON", type: "boolean", default: false }),
  handler: async (argv: Record<string, unknown>) => {
    const { WorkflowRegistry } = await import("./workflows/registry")
    const { join } = await import("path")
    const { fileURLToPath } = await import("url")
    const dir = typeof __dirname !== "undefined" ? __dirname : fileURLToPath(new URL(".", import.meta.url))
    const workflowsDir = join(dir, "./workflows")
    const registry = new WorkflowRegistry(workflowsDir)
    const workflows = registry.loadAll()

    if (workflows.length === 0) {
      process.stdout.write("No workflow definitions found.\n")
      return
    }

    if (argv.json as boolean) {
      process.stdout.write(JSON.stringify(workflows, null, 2) + "\n")
      return
    }

    const sep = "─".repeat(80)
    process.stdout.write(`Workflow Definitions (${workflows.length}):\n${sep}\n`)
    for (const w of workflows) {
      const phases = w.phases.map(p => `    ${p.name} [${p.required_capabilities.join(", ")}] (${p.execution})`).join("\n")
      process.stdout.write(`\n  ${w.name}${w.label ? ` — ${w.label}` : ""}\n${phases}\n`)
    }
    process.stdout.write(`\n${sep}\n`)
  },
}

export const ArgusToolsCommand = {
  command: "tools",
  describe: "List all registered MCP tools and their capabilities",
  handler: async () => {
    const { WorkersBridge } = await import("./bridge/mcp-client")
    const { existsSync } = await import("fs")
    const wp = MCP_WORKER_PATH
    if (!existsSync(wp)) {
      process.stdout.write("MCP worker not found. Run `argus doctor` to check setup.\n")
      return
    }
    const bridge = new WorkersBridge(wp)
    let toolDefs: Awaited<ReturnType<typeof bridge.getTools>> = []
    try {
      await bridge.connect()
      toolDefs = await bridge.getTools()
    } finally {
      await bridge.disconnect()
    }

    // Group tools by category based on capabilities
    const byCap: Record<string, typeof toolDefs> = {}
    for (const t of toolDefs) {
      const cap = (t.capabilities?.[0] ?? "uncategorized") as string
      if (!byCap[cap]) byCap[cap] = []
      byCap[cap].push(t)
    }

    const capLabels: Record<string, string> = {
      web_recon: "Reconnaissance",
      port_scanning: "Port Scanning",
      technology_detection: "Tech Detection",
      content_discovery: "Content Discovery",
      vulnerability_scanning: "Vulnerability Scanning",
      sqli_detection: "SQL Injection",
      xss_detection: "Cross-Site Scripting",
      command_injection: "Command Injection",
      browser_verification: "Browser Verification",
      auth_detection: "Authentication",
      security_analysis: "Security Analysis",
      report_generation: "Reporting",
      sast: "SAST / Code Analysis",
      http_probe: "HTTP Probing",
    }

    let output = `Registered MCP Tools (${toolDefs.length} total)\n${"─".repeat(50)}\n`
    const sortedCaps = Object.keys(byCap).sort()
    for (const cap of sortedCaps) {
      const tools = byCap[cap]
      const label = capLabels[cap] ?? cap.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())
      output += `\n${label} (${tools.length}):\n`
      for (const t of tools) {
        const quality = t.signal_quality ? ` [${t.signal_quality}]` : ""
        output += `  • ${t.name}${quality}\n`
      }
    }
    process.stdout.write(output + "\n")
  },
}

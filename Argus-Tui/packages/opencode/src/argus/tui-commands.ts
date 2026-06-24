/**
 * Argus TUI Slash Commands
 *
 * These commands are registered with the OpenCode keymap/command system
 * so they appear in the TUI's autocomplete when the user types "/".
 *
 * Commands:
 *   /assess    — Run a full assessment against a target
 *   /doctor    — Run health checks
 *   /recon     — Run reconnaissance workflow
 *   /verify    — Browser-verify a finding
 *   /report    — Generate a report for an engagement
 *   /resume    — Resume a paused engagement
 *   /evidence  — Browse captured evidence
 *   /findings  — Show findings for the current engagement
 *   /engagements — List saved engagements
 *   /tools     — Show registered MCP tools and capabilities
 *   /workflows — Show loaded workflow definitions
 *   /config    — Show effective configuration
 *   /scan      — Alias for /assess
 *   /status    — Show system status
 */

import { navigateTo } from "./tui/navigator"
import { MCP_WORKER_PATH } from "./shared/path"
import type { ToolDefinition } from "./bridge/types"

export interface ArgusTuiCommand {
  /** Unique command name (without leading /) */
  name: string
  /** Human-readable title for the palette */
  title: string
  /** Short description for autocomplete */
  description: string
  /** Slash alias(es) */
  slashes: string[]
  /** Whether the command expects a target argument */
  needsTarget: boolean
  /** The handler — receives the full argument string */
  handler: (args: string) => Promise<string>
}

const commands: ArgusTuiCommand[] = [
  {
    name: "assess",
    title: "Run security assessment",
    description: "Run a full autonomous security assessment against a target URL",
    slashes: ["assess", "scan"],
    needsTarget: true,
    handler: async (args: string) => {
      // Parse flags from the argument string
      // e.g., /assess https://target.com --no-cache
      const parts = args.trim().split(/\s+/)
      const target = parts.find(p => !p.startsWith("--"))
      if (!target) return "Usage: /assess <target> [--no-cache] [--refresh-cache]"
      const noCache = parts.includes("--no-cache")
      const refreshCache = parts.includes("--refresh-cache")
      const { assessCommand } = await import("./commands/assess")
      const result = await assessCommand(target, {
        useLLM: true,
        cacheMode: noCache ? "no_cache" : refreshCache ? "refresh" : undefined,
        writeReport: false, // TUI manages its own output — don't write raw markdown to stdout
      })
      if (!result.success) throw new Error(result.error ?? "Assessment failed")
      return `Assessment completed against ${target}${noCache ? " (no cache)" : refreshCache ? " (refresh cache)" : ""}`
    },
  },
  {
    name: "doctor",
    title: "Run health checks",
    description: "Run comprehensive health checks on the Argus runtime",
    slashes: ["doctor", "health"],
    needsTarget: false,
    handler: async () => {
      const { doctorCommand } = await import("./commands/doctor")
      const results = await doctorCommand()
      let output = ""
      let passes = 0, warns = 0, fails = 0
      for (const r of results) {
        const icon = r.status === "PASS" ? "✓" : r.status === "WARN" ? "⚠" : "✗"
        output += `${icon} [${r.name}] ${r.message}\n`
        if (r.status === "PASS") passes++
        else if (r.status === "WARN") warns++
        else fails++
      }
      output += `\n${passes} passed, ${warns} warnings, ${fails} failed`
      return output
    },
  },
  {
    name: "recon",
    title: "Run reconnaissance",
    description: "Run reconnaissance workflow against a target",
    slashes: ["recon"],
    needsTarget: true,
    handler: async (args: string) => {
      const parts = args.trim().split(/\s+/)
      const target = parts.find(p => !p.startsWith("--"))
      if (!target) return "Usage: /recon <target> [--no-cache] [--refresh-cache]"
      const noCache = parts.includes("--no-cache")
      const refreshCache = parts.includes("--refresh-cache")
      const { assessCommand } = await import("./commands/assess")
      const result = await assessCommand(target, {
        useLLM: false,
        cacheMode: noCache ? "no_cache" : refreshCache ? "refresh" : undefined,
        writeReport: false, // TUI manages its own output
      })
      if (!result.success) throw new Error(result.error ?? "Recon failed")
      return `Recon completed against ${target}${noCache ? " (no cache)" : refreshCache ? " (refresh cache)" : ""}`
    },
  },
  {
    name: "status",
    title: "Show system status",
    description: "Show MCP worker status, tool count, and system health",
    slashes: ["status"],
    needsTarget: false,
    handler: async () => {
      const { doctorCommand } = await import("./commands/doctor")
      const results = await doctorCommand()
      const mcpResult = results.find((r) => r.name === "MCP Worker")
      const toolResult = results.find((r) => r.name === "Toolchain")
      const dbResult = results.find((r) => r.name === "Database")
      return [
        "╔══════════════════════════════════════╗",
        "║         ARGUS System Status          ║",
        "╚══════════════════════════════════════╝",
        "",
        `  MCP Worker:  ${mcpResult?.status === "PASS" ? "✓ Connected" : "✗ " + (mcpResult?.message ?? "Unknown")}`,
        `  Tools:       ${toolResult?.message ?? "Unknown"}`,
        `  Database:    ${dbResult?.message ?? "Unknown"}`,
        `  Runtime:     ${process.versions.bun ? `Bun ${process.versions.bun}` : `Node.js ${process.version}`}`,
      ].join("\n")
    },
  },
  {
    name: "findings",
    title: "Show findings",
    description: "Browse findings from the current or most recent engagement",
    slashes: ["findings"],
    needsTarget: false,
    handler: async (args = "") => {
      const { EngagementStore } = await import("./engagement/store")
      const store = new EngagementStore()
      const engagements = store.listEngagements()
      if (engagements.length === 0) return "No engagements found."
      // Accept optional engagement ID (e.g., /findings ENG-001)
      const engId = args.trim().toUpperCase() || engagements[0].id
      const eng = store.getEngagement(engId)
      if (!eng) return `Engagement ${engId} not found.`
      const findings = store.getFindings(engId)
      if (findings.length === 0) return `Engagement ${engId} has no findings yet. Assessment may still be running.`
      navigateTo({ type: "findings", engagementId: engId })
      return `Opened findings for ${engId} (${eng.target}).`
    },
  },
  {
    name: "engagements",
    title: "List engagements",
    description: "List all saved engagements/assessments",
    slashes: ["engagements"],
    needsTarget: false,
    handler: async () => {
      const { EngagementStore } = await import("./engagement/store")
      const store = new EngagementStore()
      const engagements = store.listEngagements()
      if (engagements.length === 0) return "No engagements found."
      navigateTo({ type: "engagements" })
      return "Opened engagements list. Select one with Enter to view details."
    },
  },
  {
    name: "tools",
    title: "Show registered tools",
    description: "Show all registered MCP tools and their capabilities",
    slashes: ["tools"],
    needsTarget: false,
    handler: async () => {
      // Use cached tool list if available — spawning a fresh Python worker every
      // invocation takes 2-5s and kills the running worker if one is mid-scan.
      if (_cachedTools && _cachedTools.length > 0) {
        return formatToolList(_cachedTools)
      }
      const { WorkersBridge } = await import("./bridge/mcp-client")
      const { existsSync } = await import("fs")
      const wp = MCP_WORKER_PATH
      if (!existsSync(wp)) return "MCP worker not found. Run `argus doctor` to check setup."
      const bridge = new WorkersBridge(wp)
      let toolDefs: ToolDefinition[] = []
      try {
        await bridge.connect()
        toolDefs = await bridge.getTools()
        _cachedTools = toolDefs
      } finally {
        await bridge.disconnect()
      }
      return formatToolList(toolDefs)
    },
  },
  {
    name: "workflows",
    title: "Show workflows",
    description: "Show loaded workflow definitions",
    slashes: ["workflows"],
    needsTarget: false,
    handler: async () => {
      const { WorkflowRegistry } = await import("./workflows/registry")
      const { join } = await import("path")
      const { fileURLToPath } = await import("url")
      const dir = typeof __dirname !== "undefined" ? __dirname : fileURLToPath(new URL(".", import.meta.url))
      const workflowsDir = join(dir, "./workflows")
      const registry = new WorkflowRegistry(workflowsDir)
      const workflows = registry.loadAll()
      let output = `Workflows (${workflows.length}):\n${"=".repeat(50)}\n`
      for (const w of workflows) {
        output += `\n  ${w.name}: ${w.label} — ${w.phases.length} phase(s)`
        for (const p of w.phases) {
          output += `\n    ${p.name}: ${p.required_capabilities.join(", ")} (${p.execution})`
        }
      }
      return output
    },
  },
  {
    name: "config",
    title: "Show configuration",
    description: "Show effective Argus configuration",
    slashes: ["config"],
    needsTarget: false,
    handler: async () => {
      const { configCommand } = await import("./commands/config")
      return await configCommand()
    },
  },
  {
    name: "report",
    title: "Generate report",
    description: "Generate a report for an engagement or the most recent one",
    slashes: ["report"],
    needsTarget: false,
    handler: async (args = "") => {
      const { EngagementStore } = await import("./engagement/store")
      const store = new EngagementStore()

      // Parse optional --format flag and engagement ID from args
      // Examples:
      //   /report                          → latest, markdown
      //   /report ENG-001                  → ENG-001, markdown
      //   /report --format json            → latest, json
      //   /report ENG-001 --format sarif   → ENG-001, sarif
      const validFormats = ["markdown", "json", "html", "sarif"] as const
      type ReportFormat = (typeof validFormats)[number]

      let warnings: string[] = []
      let format: ReportFormat = "markdown"
      let engId: string | undefined

      const tokens = args.trim().split(/\s+/).filter(Boolean)
      for (let i = 0; i < tokens.length; i++) {
        if (tokens[i] === "--format" && i + 1 < tokens.length) {
          const fmt = tokens[++i].toLowerCase()
          if (validFormats.includes(fmt as ReportFormat)) {
            format = fmt as ReportFormat
          } else {
            warnings.push(`Unknown format "${fmt}". Valid formats: ${validFormats.join(", ")}. Falling back to "${format}".`)
          }
        } else if (!tokens[i].startsWith("--")) {
          engId = tokens[i].toUpperCase()
        }
      }

      const engagements = store.listEngagements()
      if (engagements.length === 0) return "No engagements found. Run /assess first."

      engId = engId || engagements[0].id
      const eng = store.getEngagement(engId)
      if (!eng) return `Engagement ${engId} not found.`

      // Wire progress to ScanStore so ScanDashboard shows analysis progress.
      // Pass engagementId so analysis_progress events route to the correct
      // engagement in ScanStore rather than mutating whatever is active.
      const { createScanStoreWriter } = await import("./tui/scan-store-writer")
      const onProgress = createScanStoreWriter(engId)

      const { Feature, getFeatureFlags } = await import("./config/feature-flags")
      const useLLM = getFeatureFlags().isEnabled(Feature.LLM_FINDING_ANALYSIS)

      const { reportCommand } = await import("./commands/report")
      const report = await reportCommand(engId, format, store, onProgress, useLLM)
      return warnings.length > 0 ? warnings.join("\n") + "\n\n" + report : report
    },
  },
  {
    name: "help",
    title: "Show help",
    description: "Show all Argus commands with descriptions",
    slashes: ["help", "?"],
    needsTarget: false,
    handler: async () => {
      const all = getArgusTuiCommands()
      // Build a formatted help text grouped by category
      const lines = [
        "**Argus Commands**",
        "",
        // Assessment
        "**Assessment**",
        `  /assess <target>   ${all.find((c) => c.name === "assess")?.description ?? "Run assessment"}`,
        `  /recon <target>    ${all.find((c) => c.name === "recon")?.description ?? "Run reconnaissance"}`,
        "",
        // System
        "**System**",
        `  /doctor            ${all.find((c) => c.name === "doctor")?.description ?? "Health checks"}`,
        `  /status            ${all.find((c) => c.name === "status")?.description ?? "System status"}`,
        `  /config            ${all.find((c) => c.name === "config")?.description ?? "Configuration"}`,
        "",
        // Data
        "**Data**",
        `  /findings          ${all.find((c) => c.name === "findings")?.description ?? "Browse findings"}`,
        `  /engagements       ${all.find((c) => c.name === "engagements")?.description ?? "List engagements"}`,
        `  /open <id>         ${all.find((c) => c.name === "open")?.description ?? "Open engagement or finding"}`,
        `  /report <id>       ${all.find((c) => c.name === "report")?.description ?? "Generate report"} (--format markdown|json|html|sarif)`,
        "",
        // Tools
        "**Tools**",
        `  /tools             ${all.find((c) => c.name === "tools")?.description ?? "Show MCP tools"}`,
        `  /workflows         ${all.find((c) => c.name === "workflows")?.description ?? "Show workflows"}`,
        `  /verify <finding>  ${all.find((c) => c.name === "verify")?.description ?? "Browser verification"}`,
        `  /evidence          ${all.find((c) => c.name === "evidence")?.description ?? "Browse evidence"}`,
        "",
        "**Natural language**",
        '  Type "assess https://target.com" or "find vulnerabilities in https://target.com"',
        "  and Argus will automatically route to the assessment workflow.",
        "",
        "**Navigation**",
        "  /help, /?  Show this help",
        "  /config    Show configuration",
      ]
      return lines.join("\n")
    },
  },
  {
    name: "open",
    title: "Open engagement or finding detail",
    description: "Open an engagement by ID (ENG-xxx) or a finding by ID (FIND-xxx)",
    slashes: ["open"],
    needsTarget: true,
    handler: async (args: string) => {
      const id = args.trim().toLowerCase()
      if (!id) return "Usage: /open ENG-001 or /open FIND-001"
      const { EngagementStore } = await import("./engagement/store")
      const store = new EngagementStore()
      const eng = store.getEngagement(id)
      if (eng) {
        navigateTo({ type: "engagement", engagementId: id })
        return `Opened ${id}.`
      }
      if (id.startsWith("FIND-")) {
        const finding = store.getFinding(id)
        if (!finding) return `Finding ${id} not found.`
        navigateTo({ type: "finding", findingId: id })
        const analysis = store.getValidAnalysis(id)
        const sevLabels = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        const severityLabel = sevLabels[finding.severity] ?? "UNKNOWN"
        if (analysis) {
          const impact = analysis.impact.map((i) => `  • ${i}`).join("\n")
          const remediation = analysis.remediation.map((r) => `  • ${r}`).join("\n")
          return [
            `[${severityLabel}] ${finding.id} — ${finding.title}`,
            `Description: ${finding.description}`,
            ``,
            `AI Analysis:`,
            `${analysis.explanation}`,
            ``,
            `Impact:`,
            impact,
            ``,
            `Remediation:`,
            remediation,
            ``,
            `Generated by: ${analysis.model}`,
          ].join("\n")
        }
        return `[${severityLabel}] ${finding.id} — ${finding.title}\nDescription: ${finding.description}`
      }
      return `No engagement or finding found with ID: ${id}.`
    },
  },
  {
    name: "workspace",
    title: "Open assessment workspace",
    description: "Open the assessment workspace showing active engagements and progress",
    slashes: ["workspace"],
    needsTarget: false,
    handler: async () => {
      const { navigateTo } = await import("./tui/navigator")
      navigateTo({ type: "workspace" })
      return "Opened workspace view."
    },
  },
  {
    name: "verify",
    title: "Verify a finding",
    description: "Re-run browser verification for a specific finding",
    slashes: ["verify"],
    needsTarget: true,
    handler: async (args: string) => {
      const findingId = args.trim()
      if (!findingId) return "Usage: /verify <finding-id>"
      // verifyCommand already resolves the engagement and target URL internally.
      // No need to duplicate the lookup here — just pass the finding ID.
      // The default behavior uses the real store and credentials, which is correct for the TUI.
      const { verifyCommand } = await import("./commands/verify")
      return await verifyCommand(findingId)
    },
  },
  {
    name: "evidence",
    title: "Browse evidence",
    description: "Browse and manage captured evidence for findings",
    slashes: ["evidence"],
    needsTarget: false,
    handler: async (args: string) => {
      const { evidenceCommand } = await import("./commands/evidence")
      const tokens = args.trim().split(/\s+/).filter(Boolean)
      const action = (tokens[0] ?? "list") as "list" | "show" | "prune" | "verify-package"
      return await evidenceCommand(action, tokens.slice(1))
    },
  },
]

export function getArgusTuiCommands(): ArgusTuiCommand[] {
  return commands
}

export function findArgusTuiCommand(slashName: string): ArgusTuiCommand | undefined {
  return commands.find((c) => c.slashes.includes(slashName) || c.name === slashName)
}

/**
 * Module-level cache for /tools command — avoids spawning a fresh Python worker
 * on every invocation.
 *
 * Exported accessors allow tests to prime and inspect the cache without
 * actually spawning a worker process.
 */
let _cachedTools: ToolDefinition[] = []

/**
 * Reset the tools cache to empty. Useful for test teardown between runs.
 */
export function resetToolsCache(): void {
  _cachedTools = []
}

/**
 * Returns a snapshot of the current tools cache.
 */
export function getToolsCache(): readonly ToolDefinition[] {
  return [..._cachedTools]
}

/**
 * Prime the tools cache with data. Useful for tests to avoid spawning a real worker.
 */
export function setToolsCache(tools: ToolDefinition[]): void {
  _cachedTools = tools
}

function formatToolList(toolDefs: ToolDefinition[]): string {
  let output = `Registered MCP Tools (${toolDefs.length}):\n${"=".repeat(50)}\n`
  for (const t of toolDefs) {
    const caps = t.capabilities?.join(", ") ?? ""
    const quality = t.signal_quality ?? ""
    output += `\n  ${t.name}${caps ? ` — ${caps}` : ""}${quality ? ` [${quality}]` : ""}`
  }
  return output
}

/** Format a short help text for CLI usage */
export function formatCliHelp(): string {
  const all = getArgusTuiCommands()
  return [
    "Commands:",
    ...all
      .filter((c) => c.name !== "help")
      .map((c) => {
        const slashes = c.slashes.map((s) => `/${s}`).join(", ")
        return `  ${slashes.padEnd(25)} ${c.description}`
      }),
    "",
    '  "assess https://target.com" - natural language also works',
  ].join("\n")
}

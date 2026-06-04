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

import { assessCommand } from "./commands/assess"
import { doctorCommand } from "./commands/doctor"

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
    handler: async (target: string) => {
      await assessCommand(target, { useLLM: true })
      return `Assessment completed against ${target}`
    },
  },
  {
    name: "doctor",
    title: "Run health checks",
    description: "Run comprehensive health checks on the Argus runtime",
    slashes: ["doctor", "health"],
    needsTarget: false,
    handler: async () => {
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
    handler: async (target: string) => {
      await assessCommand(target, { useLLM: false })
      return `Recon completed against ${target}`
    },
  },
  {
    name: "status",
    title: "Show system status",
    description: "Show MCP worker status, tool count, and system health",
    slashes: ["status"],
    needsTarget: false,
    handler: async () => {
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
        `  Runtime:     Node.js ${process.version}`,
      ].join("\n")
    },
  },
  {
    name: "findings",
    title: "Show findings",
    description: "Browse findings from the current or most recent engagement",
    slashes: ["findings"],
    needsTarget: false,
    handler: async () => {
      const { EngagementStore } = await import("./engagement/store")
      const store = new EngagementStore()
      const engagements = store.listEngagements()
      if (engagements.length === 0) return "No engagements found."
      const latest = engagements[engagements.length - 1]
      const findings = store.getFindings(latest.id)
      if (findings.length === 0) return `No findings for engagement ${latest.id} (${latest.target})`
      let output = `Findings for ${latest.target} (${latest.id}):\n${"=".repeat(50)}\n`
      for (const f of findings) {
        const sev = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][f.severity] ?? "UNKNOWN"
        const conf = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"][f.confidence] ?? "UNKNOWN"
        output += `\n[${sev}] ${f.title} (${conf})\n  ${f.description.slice(0, 200)}${f.description.length > 200 ? "..." : ""}\n`
      }
      return output
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
      let output = `Engagements (${engagements.length}):\n${"=".repeat(50)}\n`
      for (const e of engagements) {
        output += `\n  ${e.id}: ${e.target} [${e.status}] — ${new Date(e.created_at).toLocaleDateString()}`
      }
      return output
    },
  },
  {
    name: "tools",
    title: "Show registered tools",
    description: "Show all registered MCP tools and their capabilities",
    slashes: ["tools"],
    needsTarget: false,
    handler: async () => {
      const { WorkersBridge } = await import("./bridge/mcp-client")
      const { homedir } = await import("os")
      const { join } = await import("path")
      const { existsSync } = await import("fs")
      const { fileURLToPath } = await import("url")
      const dir = typeof __dirname !== "undefined" ? __dirname : fileURLToPath(new URL(".", import.meta.url))
      const wp = join(dir, "../../../../../argus-workers/mcp_server.py")
      if (!existsSync(wp)) return "MCP worker not found. Run `argus doctor` to check setup."
      const bridge = new WorkersBridge(wp)
      await bridge.connect()
      const toolDefs = await bridge.getTools()
      await bridge.disconnect()
      let output = `Registered MCP Tools (${toolDefs.length}):\n${"=".repeat(50)}\n`
      for (const t of toolDefs) {
        const caps = t.capabilities?.join(", ") ?? ""
        const quality = t.signal_quality ?? ""
        output += `\n  ${t.name}${caps ? ` — ${caps}` : ""}${quality ? ` [${quality}]` : ""}`
      }
      return output
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
        `  /report <id>       ${all.find((c) => c.name === "report")?.description ?? "Generate report"}`,
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
]

export function getArgusTuiCommands(): ArgusTuiCommand[] {
  return commands
}

export function findArgusTuiCommand(slashName: string): ArgusTuiCommand | undefined {
  return commands.find((c) => c.slashes.includes(slashName) || c.name === slashName)
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

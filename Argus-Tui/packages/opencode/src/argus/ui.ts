/**
 * Argus — Branded terminal UI utilities.
 * Replaces OpenCode UI branding with Argus identity.
 * Reuses all formatting infrastructure from the OpenCode UI module.
 */
import { EOL } from "os"
import { logo as glyphs } from "./logo"

const wordmark = [
  `    █████╗ ██████╗  ██████╗ ██╗   ██╗███████╗`,
  `   ██╔══██╗██╔══██╗██╔════╝ ██║   ██║██╔════╝`,
  `   ███████║██████╔╝██║  ███╗██║   ██║███████╗`,
  `   ██╔══██║██╔══██╗██║   ██║██║   ██║╚════██║`,
  `   ██║  ██║██║  ██║╚██████╔╝╚██████╔╝███████║`,
  `   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝`,
]

export const Style = {
  TEXT_HIGHLIGHT: "\x1b[96m",
  TEXT_HIGHLIGHT_BOLD: "\x1b[96m\x1b[1m",
  TEXT_DIM: "\x1b[90m",
  TEXT_DIM_BOLD: "\x1b[90m\x1b[1m",
  TEXT_NORMAL: "\x1b[0m",
  TEXT_NORMAL_BOLD: "\x1b[1m",
  TEXT_WARNING: "\x1b[93m",
  TEXT_WARNING_BOLD: "\x1b[93m\x1b[1m",
  TEXT_DANGER: "\x1b[91m",
  TEXT_DANGER_BOLD: "\x1b[91m\x1b[1m",
  TEXT_SUCCESS: "\x1b[92m",
  TEXT_SUCCESS_BOLD: "\x1b[92m\x1b[1m",
  TEXT_INFO: "\x1b[94m",
  TEXT_INFO_BOLD: "\x1b[94m\x1b[1m",
  BOX_H: "\x1b[90m─\x1b[0m",
  BOX_V: "\x1b[90m│\x1b[0m",
  BOX_TL: "\x1b[90m┌\x1b[0m",
  BOX_TR: "\x1b[90m┐\x1b[0m",
  BOX_BL: "\x1b[90m└\x1b[0m",
  BOX_BR: "\x1b[90m┘\x1b[0m",
}

export function println(...message: string[]) {
  print(...message)
  process.stderr.write(EOL)
}

export function print(...message: string[]) {
  blank = false
  process.stderr.write(message.join(" "))
}

let blank = false
export function empty() {
  if (blank) return
  println("" + Style.TEXT_NORMAL)
  blank = true
}

export function logo(pad?: string) {
  if (!process.stdout.isTTY && !process.stderr.isTTY) {
    const result = []
    for (const row of wordmark) {
      if (pad) result.push(pad)
      result.push(row)
      result.push(EOL)
    }
    if (pad) result.push(pad)
    result.push("ARGUS")
    return result.join("").trimEnd()
  }

  const result: string[] = []
  const reset = "\x1b[0m"
  const left = {
    fg: "\x1b[96m",
    shadow: "\x1b[38;5;235m",
    bg: "\x1b[48;5;235m",
  }
  const right = {
    fg: reset,
    shadow: "\x1b[38;5;238m",
    bg: "\x1b[48;5;238m",
  }
  const gap = " "
  const draw = (line: string, fg: string, shadow: string, bg: string) => {
    const parts: string[] = []
    for (const char of line) {
      if (char === "_") {
        parts.push(bg, " ", reset)
        continue
      }
      if (char === "^") {
        parts.push(fg, bg, "▀", reset)
        continue
      }
      if (char === "~") {
        parts.push(shadow, "▀", reset)
        continue
      }
      if (char === " ") {
        parts.push(" ")
        continue
      }
      parts.push(fg, char, reset)
    }
    return parts.join("")
  }
  glyphs.left.forEach((row, index) => {
    if (pad) result.push(pad)
    result.push(draw(row, left.fg, left.shadow, left.bg))
    result.push(gap)
    const other = glyphs.right[index] ?? ""
    result.push(draw(other, right.fg, right.shadow, right.bg))
    result.push(EOL)
  })
  if (pad) result.push(pad)
  result.push(Style.TEXT_DIM + "ARGUS" + Style.TEXT_NORMAL + EOL)
  return result.join("").trimEnd()
}

interface DashboardStats {
  totalTargets: number
  openEngagements: number
  confirmedFindings: number
  recentEngagements: Array<{
    id: string
    target: string
    status: string
    findingCount: number
    updatedAt: number
  }>
}

function bar(value: number, max: number, width: number): string {
  if (max === 0) return Style.TEXT_DIM + "·".repeat(width) + Style.TEXT_NORMAL
  const filled = Math.round((value / max) * width)
  const empty = width - filled
  const fg = value >= 4 ? Style.TEXT_DANGER : value >= 2 ? Style.TEXT_WARNING : Style.TEXT_SUCCESS
  return fg + "█".repeat(filled) + Style.TEXT_DIM + "░".repeat(empty) + Style.TEXT_NORMAL
}

function box(width: number, lines: string[]): string[] {
  const top = Style.BOX_TL + Style.BOX_H.repeat(width - 2) + Style.BOX_TR
  const bottom = Style.BOX_BL + Style.BOX_H.repeat(width - 2) + Style.BOX_BR
  const middle = lines.map((l) => {
    const stripped = l.replace(/\x1b\[[0-9;]*m/g, "")
    const pad = width - 2 - stripped.length - 1
    return Style.BOX_V + " " + l + " ".repeat(Math.max(0, pad)) + Style.BOX_V
  })
  return [top, ...middle, bottom]
}

export function dashboard(stats?: DashboardStats): string {
  const lines: string[] = []
  const W = 62

  // Logo + tagline
  lines.push("")
  lines.push(Style.TEXT_HIGHLIGHT_BOLD + "  ARGUS v5" + Style.TEXT_NORMAL)
  lines.push(Style.TEXT_DIM + "  Autonomous Security Assessment Platform" + Style.TEXT_NORMAL)
  lines.push("")

  // Stats row
  if (stats) {
    const statLine = [
      Style.TEXT_HIGHLIGHT_BOLD + String(stats.totalTargets) + Style.TEXT_NORMAL + Style.TEXT_DIM + " targets" + Style.TEXT_NORMAL,
      Style.TEXT_WARNING_BOLD + String(stats.openEngagements) + Style.TEXT_NORMAL + Style.TEXT_DIM + " active" + Style.TEXT_NORMAL,
      Style.TEXT_DANGER_BOLD + String(stats.confirmedFindings) + Style.TEXT_NORMAL + Style.TEXT_DIM + " findings" + Style.TEXT_NORMAL,
    ].join(Style.TEXT_DIM + "  │  " + Style.TEXT_NORMAL)
    const statBox = box(W, ["  " + statLine])
    lines.push(...statBox)
    lines.push("")
  }

  // Quick actions
  lines.push(Style.TEXT_DIM + "  ─── Quick Actions ───" + Style.TEXT_NORMAL)
  const actions = [
    ["assess <target>", "Run full autonomous security assessment"],
    ["recon <target>",  "Run reconnaissance workflow"],
    ["doctor",          "Run health checks"],
    ["engagements",     "Browse all engagements"],
    ["workspace",       "Open assessment workspace"],
  ]
  for (const [cmd, desc] of actions) {
    lines.push("  " + Style.TEXT_HIGHLIGHT + "$ argus " + cmd + Style.TEXT_NORMAL + Style.TEXT_DIM + "  " + desc + Style.TEXT_NORMAL)
  }
  lines.push("")

  // Recent activity
  if (stats && stats.recentEngagements.length > 0) {
    lines.push(Style.TEXT_DIM + "  ─── Recent Activity ───" + Style.TEXT_NORMAL)
    const rows: string[] = []
    for (const eng of stats.recentEngagements.slice(0, 5)) {
      const statusIcon = eng.status === "COMPLETED" ? Style.TEXT_SUCCESS + "✓" :
                         eng.status === "RUNNING" ? Style.TEXT_HIGHLIGHT + "⟳" :
                         eng.status === "FAILED" ? Style.TEXT_DANGER + "✗" :
                         Style.TEXT_DIM + "○"
      const row = Style.TEXT_DIM + eng.id + Style.TEXT_NORMAL + "  " +
                  Style.TEXT_NORMAL_BOLD + eng.target + Style.TEXT_NORMAL + "  " +
                  statusIcon + " " + Style.TEXT_DIM + eng.status.toLowerCase() + Style.TEXT_NORMAL +
                  Style.TEXT_DIM + "  (" + eng.findingCount + " findings)" + Style.TEXT_NORMAL
      rows.push(row)
    }
    lines.push(...box(W, rows))
    lines.push("")
  } else {
    lines.push(Style.TEXT_DIM + "  No assessments yet. Run " + Style.TEXT_HIGHLIGHT + "argus assess <target>" + Style.TEXT_DIM + " to get started." + Style.TEXT_NORMAL)
    lines.push("")
  }

  // Tip
  lines.push(Style.TEXT_DIM + "  Tip: " + Style.TEXT_NORMAL + "Run " + Style.TEXT_HIGHLIGHT + "argus --help" + Style.TEXT_NORMAL + " to see all commands")
  lines.push(Style.TEXT_DIM + "  " + "─".repeat(W - 2) + Style.TEXT_NORMAL)
  lines.push(Style.TEXT_DIM + "  Run with no arguments to launch the interactive TUI" + Style.TEXT_NORMAL)
  lines.push("")

  return lines.join(EOL)
}

export function error(message: string) {
  if (message.startsWith("Error: ")) {
    message = message.slice("Error: ".length)
  }
  println(Style.TEXT_DANGER_BOLD + "Error: " + Style.TEXT_NORMAL + message)
}

export function markdown(text: string): string {
  return text
}

export * as UI from "./ui"

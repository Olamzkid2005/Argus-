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
    result.push("ARGUS v5 — Autonomous Security Platform")
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
  result.push(Style.TEXT_DIM + "ARGUS v5 — Autonomous Security Platform" + Style.TEXT_NORMAL + EOL)
  return result.join("").trimEnd()
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

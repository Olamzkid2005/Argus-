/**
 * ArgusIntentClassifier — Two-stage intent detection for the Argus TUI.
 *
 * Stage 1: Slash command detection (explicit)
 * Stage 2: Natural language intent classification (regex-based, swappable)
 *
 * Design:
 *   Classifier is isolated behind `classify()` so the regex implementation
 *   can be replaced with an ML-based classifier later without changing
 *   any callers.
 */

import { URL } from "url"

// ── Public types ────────────────────────────────────────────────

export type ClassifiedIntent =
  | { type: "assessment"; target: string; useLLM: boolean }
  | { type: "chat" }
  | { type: "slash_command"; command: string; args: string }

// ── Stage 1: Slash command detection ────────────────────────────

/**
 * Known Argus slash commands.
 * Extended at startup by scanning registered TUI commands.
 */
export const SLASH_COMMANDS = new Set([
  "assess", "scan",
  "doctor", "health",
  "recon",
  "verify",
  "report",
  "resume",
  "evidence",
  "findings",
  "engagements",
  "tools",
  "workflows",
  "config", "status",
  "help",
  "quit", "exit",
])

export function detectSlashCommand(input: string): ClassifiedIntent | null {
  const trimmed = input.trim()
  if (!trimmed.startsWith("/")) return null

  const firstLine = trimmed.split("\n")[0]
  const parts = firstLine.split(/\s+/)
  const cmd = parts[0].slice(1).toLowerCase()

  if (SLASH_COMMANDS.has(cmd)) {
    const args = parts.slice(1).join(" ")
    return { type: "slash_command", command: cmd, args }
  }
  return null
}

// ── Stage 2: Natural language intent classification ─────────────

/**
 * Patterns that trigger assessment routing.
 * These catch explicit assessment requests like:
 *   "assess https://example.com"
 *   "find vulnerabilities in example.com"
 *   "scan juice-shop.herokuapp.com"
 */
const ASSESSMENT_PATTERNS = [
  // Direct command patterns
  /^(?:please\s+)?(?:run\s+)?assess\s+/i,
  /^(?:please\s+)?(?:run\s+)?scan\s+/i,
  /^(?:please\s+)?(?:run\s+)?recon\s+/i,
  /^(?:please\s+)?(?:run\s+)?audit\s+/i,
  // Natural language patterns
  /find\s+vulnerabilit(?:y|ies)\s+(?:in|for|on)\s+/i,
  /test\s+\S+\s+for\s+vulnerabilit/i,
  /check\s+security\s+(?:of|for|on)\s+/i,
  /run\s+assessment\s+(?:on|of|against)\s+/i,
  /perform\s+(?:a\s+)?security\s+assessment\s+(?:on|of|against)\s+/i,
  /what\s+vulnerabilit(?:y|ies)\s+does\s+/i,
  /is\s+\S+\s+vulnerable/i,
  /pentest\s+/i,
  /security\s+audit\s+/i,
]

/**
 * Patterns that should ALWAYS go to LLM chat (never assessment).
 */
const LLM_PASSTHROUGH = [
  /^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b/i,
  /^(?:what\s+(?:can\s+you\s+)?do|help|how\s+(?:do\s+)?(?:you\s+)?work)/i,
  /^(?:who\s+(?:are\s+)?you|what\s+(?:are\s+)?you)/i,
  /^(?:explain|describe|what\s+is|how\s+(?:does|do|can|would))/i,
  /^(?:thanks|thank\s+you|cheers|bye|goodbye)\b/i,
  /^(?:write|create|make|build|implement|code|program|script)\s+/i,
  /^(?:refactor|fix|debug|optimize)\s+/i,
]

/**
 * Extract a valid URL from text.
 * Uses new URL() for validation after normalization.
 */
function extractUrl(text: string): string | null {
  // First try to find a full URL with scheme
  const urlWithScheme = text.match(/https?:\/\/[^\s,;)]+/i)
  if (urlWithScheme) {
    try {
      const parsed = new URL(urlWithScheme[0])
      return parsed.href
    } catch {
      // fall through
    }
  }

  // Try to find a domain-like pattern (e.g. example.com, sub.example.com:8080)
  const domainMatch = text.match(/(?:\w[\w-]*\.)+[a-zA-Z]{2,}(?::\d+)?(?:\/[\w\-./]*)?/)
  if (domainMatch) {
    const raw = domainMatch[0]
    // Filter out things like "hello.world" or "test.file.name" that aren't domains
    const parts = raw.split(".")
    const tld = parts[parts.length - 1]
    if (tld.length < 2) return null // .x or .a aren't valid TLDs
    // Must have at least one dot with a valid-looking TLD
    if (parts.length < 2) return null
    try {
      const normalized = raw.startsWith("http") ? raw : `https://${raw}`
      const parsed = new URL(normalized)
      return parsed.href
    } catch {
      return null
    }
  }

  return null
}

/**
 * Core intent classification.
 * Given raw user input, determine if it's an assessment request or chat.
 */
export function classify(input: string): ClassifiedIntent {
  const trimmed = input.trim()
  if (!trimmed) return { type: "chat" }

  // Stage 1: Check for slash commands first
  const slashResult = detectSlashCommand(trimmed)
  if (slashResult) return slashResult

  // Hard passthrough for explicit chat patterns
  for (const pattern of LLM_PASSTHROUGH) {
    if (pattern.test(trimmed)) return { type: "chat" }
  }

  // Stage 2: Check assessment patterns
  let matchedAssessment = false
  for (const pattern of ASSESSMENT_PATTERNS) {
    if (pattern.test(trimmed)) {
      matchedAssessment = true
      break
    }
  }

  if (matchedAssessment) {
    const target = extractUrl(trimmed)
    if (target) {
      // "recon" and "scan" are deterministic; "assess" uses LLM by default
      const useLLM = /^assess\b/i.test(trimmed) && !/deterministic/i.test(trimmed)
      return { type: "assessment", target, useLLM }
    }
  }

  return { type: "chat" }
}

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
  "open",
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
 *
 * Two modes:
 *   1. EXACT patterns — require pattern match at start of input
 *   2. CATCH-ALL — triggers when input contains BOTH a domain AND security keywords
 */
const ASSESSMENT_PATTERNS = [
  // Direct command patterns (start-anchored)
  /^(?:please\s+)?(?:run\s+)?assess\s+/i,
  /^(?:please\s+)?(?:run\s+)?scan\s+/i,
  /^(?:please\s+)?(?:run\s+)?recon\s+/i,
  /^(?:please\s+)?(?:run\s+)?audit\s+/i,
  // Natural language patterns (start-anchored)
  /find\s+vulnerabilit(?:y|ies)\s+(?:in|for|on)\s+/i,
  /test\s+\S+\s+for\s+vulnerabilit/i,
  /check\s+security\s+(?:of|for|on)\s+/i,
  /run\s+assessment\s+(?:on|of|against)\s+/i,
  /perform\s+(?:a\s+)?security\s+assessment\s+(?:on|of|against)\s+/i,
  /what\s+vulnerabilit(?:y|ies)\s+does\s+/i,
  /is\s+\S+\s+vulnerable/i,
  /pentest\s+/i,
  /security\s+audit\s+/i,
  // Mid-sentence patterns (not start-anchored)
  /can\s+you\s+(?:assess|scan|audit)\s+/i,
  /i\s+(?:need|want|would\s+like)\s+(?:to\s+)?(?:assess|scan|audit|test)\s+/i,
  /could\s+you\s+(?:assess|scan|audit|test)\s+/i,
  /we\s+(?:should|need\s+to)\s+(?:assess|scan|audit|test)\s+/i,
  /please\s+(?:assess|scan|audit|test|check)\s+/i,
]

/**
 * Security keywords used by the catch-all heuristic.
 * If the input contains a domain AND any of these keywords, it's treated as an assessment.
 */
const SECURITY_KEYWORDS = [
  "vulnerability", "vulnerabilities", "vulnerable",
  "assess", "assessment", "assessed",
  "security", "secure",
  "scan", "scanning", "scanner",
  "penetration test", "pentest",
  "audit", "auditing",
  "recon", "reconnaissance",
  "sql injection", "sqli",
  "xss", "cross.site",
  "csrf", "cross.site.request",
  "injection", "exploit", "exploitation",
  "weakness", "weak", "hack", "hacking",
  "check.*security", "security.*check",
  "test.*security", "security.*test",
  "find.*issue", "find.*problem",
]

/**
 * Check if text contains a domain name (for catch-all assessment detection).
 */
function containsDomain(text: string): boolean {
  // ReDoS protection
  if (text.length > 10000) return false
  return /(?:\w[\w-]*\.)+[a-zA-Z]{2,}(?::\d+)?(?:\/[\w\-./]*)?/.test(text)
}

/**
 * Count how many unique security-assessment-related keywords match in text.
 */
function countSecurityKeywords(text: string): number {
  const lower = text.toLowerCase()
  const matched = new Set<string>()
  for (const kw of SECURITY_KEYWORDS) {
    if (kw.includes(".*")) {
      if (new RegExp(kw, "i").test(lower)) matched.add(kw)
    } else if (lower.includes(kw)) {
      matched.add(kw)
    }
  }
  return matched.size
}

/**
 * Check if text contains any security-assessment-related keyword.
 */
function containsSecurityKeyword(text: string): boolean {
  return countSecurityKeywords(text) > 0
}

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

  // Stage 2: Check assessment patterns (exact match first)
  const target = extractUrl(trimmed)

  // Check exact patterns
  for (const pattern of ASSESSMENT_PATTERNS) {
    if (pattern.test(trimmed)) {
      if (target) {
        const useLLM = /^assess\b/i.test(trimmed) && !/deterministic/i.test(trimmed)
        return { type: "assessment", target, useLLM }
      }
      break
    }
  }

  // Stage 3: Catch-all — URL + 2+ security keywords = assessment
  // This catches phrasings that don't match exact patterns but clearly
  // intend an assessment (e.g. "I need to test example.com for vulns").
  // Requiring 2+ keywords reduces false positives from casual chat
  // that happens to mention a domain and a single security term.
  if (target && containsDomain(trimmed) && countSecurityKeywords(trimmed) >= 2) {
    return { type: "assessment", target, useLLM: true }
  }

  return { type: "chat" }
}

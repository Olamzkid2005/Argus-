/**
 * BrowserScope — parsed-origin authorization for every browser request.
 *
 * Playwright has no notion of an authorized target. Once a context carries a
 * logged-in session (cookies, `Authorization` headers injected by the JWT
 * provider or the login flow), any navigation the verifier code performs,
 * including one built from target-controlled text, sends that session to
 * whatever host it names. This module is the browser-side equivalent of the
 * Python workers' `tools/scope_validator.py`: one parser and one decision,
 * made on parsed components (scheme, host, port) and never on strings.
 *
 * Scope entries are typed, matching the Python permission kinds:
 *   - host/port — `example.com`, `example.com:8080`, `*.example.com`:
 *     any scheme and any path on that host, restricted to the stated port;
 *   - origin — `https://example.com`: exactly scheme+host+port for any path.
 *     It does NOT authorize another scheme, another port, or a sibling origin
 *     such as `https://api.example.com`;
 *   - glob — an explicit `*` pattern such as `*example.com*`, kept as a glob
 *     because that is the operator stating intent rather than an incidental
 *     substring test.
 */

const MAX_PORT = 65535
const HOST_PATTERN = /^(\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)$/i

export class BrowserScopeError extends Error {
  readonly target: string

  constructor(target: string, reason: string) {
    super(`Blocked browser request to ${target}: ${reason}`)
    this.name = "BrowserScopeError"
    this.target = target
  }
}

export interface ParsedOrigin {
  scheme: "http" | "https"
  host: string
  port: number
}

export interface ScopeViolation {
  url: string
  reason: string
  /** True when the blocked request would have started a main-frame navigation. */
  navigation: boolean
}

export type ScopeRule =
  | { kind: "origin"; entry: string; origin: ParsedOrigin }
  | { kind: "host"; entry: string; host: string; port: number | null }
  | { kind: "glob"; entry: string; pattern: RegExp }

/**
 * Parse one absolute http(s) URL into the parts authorization compares.
 *
 * Deliberately strict: anything that is not an absolute http(s) URL with a
 * valid host and port is rejected rather than interpreted, so a scheme-less or
 * malformed value can never be matched against an entry by accident.
 */
export function parseOrigin(value: string): ParsedOrigin {
  if (typeof value !== "string") {
    throw new BrowserScopeError(String(value), "target is not a string")
  }
  const text = value.trim()
  if (!text) throw new BrowserScopeError(value, "empty target")
  if (/\s/.test(text)) throw new BrowserScopeError(value, "target contains whitespace")

  let parsed: URL
  try {
    parsed = new URL(text)
  } catch {
    throw new BrowserScopeError(value, "not an absolute URL")
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new BrowserScopeError(value, `unsupported URL scheme ${parsed.protocol}`)
  }
  if (parsed.username || parsed.password) {
    throw new BrowserScopeError(value, "targets carrying credentials are not authorized")
  }

  const host = parsed.hostname.replace(/\.$/, "").toLowerCase()
  if (!host || !HOST_PATTERN.test(host)) {
    throw new BrowserScopeError(value, `invalid host ${host || "(none)"}`)
  }

  const explicit = parsed.port ? Number(parsed.port) : null
  if (explicit !== null && (!Number.isInteger(explicit) || explicit <= 0 || explicit > MAX_PORT)) {
    throw new BrowserScopeError(value, `invalid port ${parsed.port}`)
  }

  return {
    scheme: parsed.protocol === "https:" ? "https" : "http",
    host,
    port: explicit ?? (parsed.protocol === "https:" ? 443 : 80),
  }
}

/** Whether this URL is a network request the scope must decide (http/https). */
export function isScopeableUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim())
}

export function sameOrigin(a: ParsedOrigin, b: ParsedOrigin): boolean {
  return a.scheme === b.scheme && a.host === b.host && a.port === b.port
}

export function originKey(origin: ParsedOrigin): string {
  return `${origin.scheme}://${origin.host}:${origin.port}`
}

/**
 * The scope entries to hand a browser run for its engagement target.
 *
 * Returns the normalized origin, or an empty list when the value is not an
 * http(s) URL (an engagement with no usable target then falls back to pinning
 * the first navigation instead of authorizing a hostname-shaped string).
 */
export function scopeEntriesFor(target?: string | null): string[] {
  if (!target) return []
  try {
    return [originKey(parseOrigin(target))]
  } catch {
    return []
  }
}

function globToRegExp(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+^${}()|\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".")
  return new RegExp(`^${escaped}$`, "i")
}

function hostEntryMatches(ruleHost: string, host: string): boolean {
  if (ruleHost === host) return true
  if (ruleHost.startsWith("*.")) {
    const suffix = ruleHost.slice(1) // ".example.com"
    if (!host.endsWith(suffix)) return false
    const label = host.slice(0, -suffix.length)
    return label.length > 0 && !label.includes(".")
  }
  return false
}

/** Interpret one scope entry, or `null` when it is not a usable entry. */
export function parseScopeRule(entry: string): ScopeRule | null {
  const text = (entry ?? "").trim()
  if (!text) return null

  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
    if (text.includes("*") || text.includes("?")) {
      return { kind: "glob", entry: text, pattern: globToRegExp(text) }
    }
    try {
      return { kind: "origin", entry: text, origin: parseOrigin(text) }
    } catch {
      return null
    }
  }

  // Host form: `example.com`, `example.com:8080`, `*.example.com`. A leading
  // `*.` is a one-label wildcard, not a glob: the rest of the entry must still
  // be a real host (or host:port), so `*.example.com` cannot match
  // `deep.api.example.com` the way a `*` pattern would.
  const wildcardHost = text.startsWith("*.")
  const body = wildcardHost ? text.slice(2) : text
  if (body.includes("*") || body.includes("?")) {
    return { kind: "glob", entry: text, pattern: globToRegExp(text) }
  }

  const parts = body.split(":")
  if (parts.length > 2) return null
  const hostPart = (parts[0] ?? "").replace(/\.$/, "").toLowerCase()
  if (!hostPart || !HOST_PATTERN.test(hostPart)) return null
  const host = wildcardHost ? `*.${hostPart}` : hostPart

  const portPart = parts[1]
  if (portPart !== undefined) {
    if (!/^\d+$/.test(portPart)) return null
    const port = Number(portPart)
    if (port <= 0 || port > MAX_PORT) return null
    return { kind: "host", entry: text, host, port }
  }
  return { kind: "host", entry: text, host, port: null }
}

export function ruleAuthorizes(rule: ScopeRule, target: ParsedOrigin): boolean {
  switch (rule.kind) {
    case "origin":
      return sameOrigin(rule.origin, target)
    case "host":
      if (!hostEntryMatches(rule.host, target.host)) return false
      return rule.port === null || rule.port === target.port
    case "glob":
      return (
        rule.pattern.test(`${target.scheme}://${target.host}`) ||
        rule.pattern.test(`${target.scheme}://${target.host}:${target.port}`) ||
        rule.pattern.test(target.host)
      )
  }
}

export interface ScopeDecision {
  authorized: boolean
  reason: string
  origin: ParsedOrigin | null
}

/**
 * The run's browser authorization.
 *
 * With no explicit entries the first navigation pins the run's own origin and
 * everything after it must be that origin — a run is authorized for its target,
 * not for whatever URL a finding or a redirect chain names. With entries, each
 * request is checked against them, and a pinned origin (from the engagement
 * target) still applies.
 */
export class BrowserScope {
  readonly mode: "enforce" | "warn"
  private rules: ScopeRule[] = []
  private pinned: ParsedOrigin | null = null
  private readonly log: ScopeViolation[] = []
  private readonly invalidEntries: string[] = []

  constructor(allowedTargets: string[] = [], mode: "enforce" | "warn" = "enforce") {
    this.mode = mode
    for (const entry of allowedTargets) {
      const rule = parseScopeRule(entry)
      if (rule) this.rules.push(rule)
      else this.invalidEntries.push(entry)
    }
  }

  get pinnedOrigin(): ParsedOrigin | null {
    return this.pinned
  }

  get entries(): string[] {
    return this.rules.map((rule) => rule.entry)
  }

  get rejectedEntries(): string[] {
    return [...this.invalidEntries]
  }

  get violations(): ScopeViolation[] {
    return [...this.log]
  }

  /** Authorize the run's engagement target; later requests must stay on it. */
  pinOrigin(target: string): ParsedOrigin {
    const origin = parseOrigin(target)
    this.pinned = origin
    return origin
  }

  authorize(value: string): ScopeDecision {
    let origin: ParsedOrigin
    try {
      origin = parseOrigin(value)
    } catch (error) {
      return { authorized: false, reason: (error as Error).message, origin: null }
    }

    if (this.pinned && sameOrigin(this.pinned, origin)) {
      return { authorized: true, reason: "engagement target origin", origin }
    }

    const rule = this.rules.find((candidate) => ruleAuthorizes(candidate, origin))
    if (rule) {
      return { authorized: true, reason: `authorized by ${rule.entry}`, origin }
    }

    return {
      authorized: false,
      reason:
        this.rules.length > 0
          ? "not in the authorized browser scope"
          : "no authorized browser origin for this run",
      origin,
    }
  }

  recordViolation(url: string, reason: string, navigation = false): ScopeViolation {
    const violation: ScopeViolation = { url, reason, navigation }
    this.log.push(violation)
    return violation
  }
}

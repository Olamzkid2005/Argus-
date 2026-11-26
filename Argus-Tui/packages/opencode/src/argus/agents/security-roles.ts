/**
 * Security subagent roster — single source of truth for Argus's cyber roles.
 *
 * `src/agent/agent.ts` builds the permission rulesets from this data, and
 * `src/argus/commands/doctor.ts` renders `describePermissionSurface()` from
 * those same rules, so the doctor can never describe a role differently from
 * the one that is registered.
 *
 * Tool access is derived from the canonical registry
 * (`@/tool/argus-tools.generated`, itself generated from
 * `tool_definitions.TOOLS`): roles name no scanner by hand, so adding a tool
 * to the registry automatically reaches the roles allowed to call it.
 *
 * Per docs/cyber-harness-plan.md (Q-1): `vuln-scan` bash is auto-allowed.
 * `reporter` may write only under evidence/ and reports/ (Q-2).
 */

import { REGISTRY_TOOL_SPECS } from "@/tool/argus-tools.specs.generated"

export type PermissionAction = "allow" | "ask" | "deny"
export type PermissionRule = PermissionAction | Record<string, PermissionAction>

export interface SecurityRole {
  readonly name: "recon" | "vuln-scan" | "verifier" | "reporter"
  /** `all` so the role is selectable with Tab and callable as a subagent. */
  readonly mode: "all"
  /** Description shown in the agent picker; also states the tool policy. */
  readonly description: string
  /** Rules merged on top of the default agent ruleset. */
  readonly permission: Record<string, PermissionRule>
}

/**
 * Render a role's ruleset as `allow: … | ask: … | deny: …`, derived from the
 * rules themselves rather than a hand-written summary. `doctor` prints this,
 * so editing a permission changes the report and drift cannot hide behind a
 * stale prose line.
 */
export function describePermissionSurface(permission: Record<string, PermissionRule>): string {
  const groups: Record<PermissionAction, string[]> = { allow: [], ask: [], deny: [] }
  for (const [tool, rule] of Object.entries(permission)) {
    if (typeof rule === "string") {
      groups[rule].push(tool)
      continue
    }
    // Nested pattern map, e.g. reporter's edit: { "*": "deny", "**/evidence/**": "allow" }.
    for (const action of ["allow", "ask", "deny"] as const) {
      const patterns = Object.keys(rule).filter((pattern) => rule[pattern] === action)
      if (patterns.length > 0) groups[action].push(`${tool}(${patterns.join(", ")})`)
    }
  }
  return (["allow", "ask", "deny"] as const)
    .map((action) => {
      const tools = groups[action].sort()
      return `${action}: ${tools.length > 0 ? tools.join(", ") : "none"}`
    })
    .join(" | ")
}

/**
 * Every *classified* executable registry tool, for the vulnerability scanner.
 *
 * `unclassified` tools (no declared risk tier) are never auto-allowed: an
 * unknown risk level must not silently become low risk. Classifying a tool
 * in the registry is what unlocks it here.
 */
function classifiedToolAllow(): Record<string, PermissionRule> {
  const allow: Record<string, PermissionRule> = {}
  for (const spec of REGISTRY_TOOL_SPECS) {
    if (spec.risk === "unclassified") continue
    allow[spec.id] = "allow"
  }
  return allow
}

/**
 * Verification tools: a deliberately narrower set than the scanner's.
 *
 * The verifier re-runs the minimal request behind a candidate finding — it
 * observes and re-probes, it does not exploit. So unlike vuln-scan it gets:
 * low/medium risk only (no sqlmap/commix-style injectors, no cloud-metadata
 * probing), recon/scan/deep_scan phases only (no post-exploit, no
 * report/analyze engines), and no state-modifying auth or storage tools
 * (register/login create accounts, bucket-upload writes objects).
 */
const VERIFIER_EXCLUDED_TOOLS: ReadonlySet<string> = new Set([
  "register",
  "login",
  "bucket-upload",
])

const VERIFIER_PHASES: ReadonlySet<string> = new Set(["recon", "scan", "deep_scan"])

function verifierToolAllow(): Record<string, PermissionRule> {
  const allow: Record<string, PermissionRule> = {}
  for (const spec of REGISTRY_TOOL_SPECS) {
    if (spec.risk !== "low" && spec.risk !== "medium") continue
    if (!spec.phases.some((p) => VERIFIER_PHASES.has(p))) continue
    if (VERIFIER_EXCLUDED_TOOLS.has(spec.id)) continue
    allow[spec.id] = "allow"
  }
  // The dedicated finding verifier is always in scope for the verifier role.
  const findingVerifier = REGISTRY_TOOL_SPECS.find((s) => s.id === "finding-verifier")
  if (findingVerifier && findingVerifier.risk !== "unclassified") {
    allow[findingVerifier.id] = "allow"
  }
  return allow
}

/**
 * Read-only, low-risk recon-phase tools: the recon role maps the surface
 * with these instead of composing raw bash. Active scanners, port scans and
 * anything above low risk stay out — recon observes, it does not probe.
 */
function reconToolAllow(): Record<string, PermissionRule> {
  const allow: Record<string, PermissionRule> = {}
  for (const spec of REGISTRY_TOOL_SPECS) {
    if (spec.phases.includes("recon") && spec.risk === "low") allow[spec.id] = "allow"
  }
  return allow
}

export const SECURITY_ROLES: readonly SecurityRole[] = [
  {
    name: "recon",
    mode: "all",
    description:
      "Read-only reconnaissance subagent. Maps the in-scope attack surface with grep/glob/read, in-scope page fetches, and the passive recon tools (httpx, katana, whatweb, ...). Runs no state-modifying bash and never edits files.",
    permission: {
      "*": "deny",
      grep: "allow",
      glob: "allow",
      list: "allow",
      read: "allow",
      webfetch: "allow",
      websearch: "allow",
      ...reconToolAllow(),
    },
  },
  {
    name: "vuln-scan",
    mode: "all",
    description:
      "Vulnerability scanning subagent. Calls the native scanner tools (nuclei, nmap, semgrep, ...) like any other tool, or drives scanner CLIs over bash, and reads their output. Bash is auto-allowed by design (plan Q-1); stay strictly inside the engagement scope and log every command.",
    permission: {
      "*": "deny",
      bash: "allow",
      read: "allow",
      grep: "allow",
      glob: "allow",
      list: "allow",
      webfetch: "allow",
      websearch: "allow",
      ...classifiedToolAllow(),
    },
  },
  {
    name: "verifier",
    mode: "all",
    description:
      "Finding verification subagent. Calls the native scanner and verification tools (or re-runs the minimal request or command) behind a candidate finding and reports whether it reproduces. Never marks a finding confirmed without an attached evidence artifact.",
    permission: {
      "*": "deny",
      bash: "allow",
      read: "allow",
      grep: "allow",
      glob: "allow",
      list: "allow",
      webfetch: "allow",
      websearch: "allow",
      ...verifierToolAllow(),
    },
  },
  {
    name: "reporter",
    mode: "all",
    description:
      "Report-writing subagent. Turns verified findings into report sections. Writes only under the engagement evidence directory and reports/; every claim must cite an evidence file.",
    permission: {
      "*": "deny",
      read: "allow",
      grep: "allow",
      glob: "allow",
      list: "allow",
      edit: {
        "*": "deny",
        "**/evidence/**": "allow",
        "**/reports/**": "allow",
      },
    },
  },
]

/**
 * Security subagent roster — single source of truth for Argus's cyber roles.
 *
 * `src/agent/agent.ts` builds the permission rulesets from this data, and
 * `src/argus/commands/doctor.ts` reports the same surface, so the doctor can
 * never describe a role differently from the one that is registered.
 *
 * Per docs/cyber-harness-plan.md (Q-1): `vuln-scan` bash is auto-allowed.
 * `reporter` may write only under evidence/ and reports/ (Q-2).
 */

export type PermissionAction = "allow" | "ask" | "deny"
export type PermissionRule = PermissionAction | Record<string, PermissionAction>

export interface SecurityRole {
  readonly name: "recon" | "vuln-scan" | "verifier" | "reporter"
  /** `all` so the role is selectable with Tab and callable as a subagent. */
  readonly mode: "all"
  /** Description shown in the agent picker; also states the tool policy. */
  readonly description: string
  /** One-line allow/deny surface shown by `doctor`. */
  readonly summary: string
  /** Rules merged on top of the default agent ruleset. */
  readonly permission: Record<string, PermissionRule>
}

export const SECURITY_ROLES: readonly SecurityRole[] = [
  {
    name: "recon",
    mode: "all",
    description:
      "Read-only reconnaissance subagent. Maps the in-scope attack surface with grep/glob/read and fetches in-scope pages. Runs no state-modifying bash and never edits files.",
    summary: "read-only: grep/glob/list/read/webfetch/websearch",
    permission: {
      "*": "deny",
      grep: "allow",
      glob: "allow",
      list: "allow",
      read: "allow",
      webfetch: "allow",
      websearch: "allow",
    },
  },
  {
    name: "vuln-scan",
    mode: "all",
    description:
      "Vulnerability scanning subagent. Drives scanner CLIs (nuclei, nmap, semgrep, ...) and reads their output. Bash is auto-allowed by design (plan Q-1); stay strictly inside the engagement scope and log every command.",
    summary: "bash auto-allow + read-only inspection tools",
    permission: {
      "*": "deny",
      bash: "allow",
      read: "allow",
      grep: "allow",
      glob: "allow",
      list: "allow",
      webfetch: "allow",
      websearch: "allow",
    },
  },
  {
    name: "verifier",
    mode: "all",
    description:
      "Finding verification subagent. Re-runs the minimal request or command behind a candidate finding and reports whether it reproduces. Never marks a finding confirmed without an attached evidence artifact.",
    summary: "bash + read; no edits, evidence required to confirm",
    permission: {
      "*": "deny",
      bash: "allow",
      read: "allow",
      grep: "allow",
      glob: "allow",
      list: "allow",
      webfetch: "allow",
      websearch: "allow",
    },
  },
  {
    name: "reporter",
    mode: "all",
    description:
      "Report-writing subagent. Turns verified findings into report sections. Writes only under the engagement evidence directory and reports/; every claim must cite an evidence file.",
    summary: "writes evidence/** and reports/** only",
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

import type { PhaseExecutionRequest } from "../planner/types"
import type { ApprovalGate } from "./types"

export interface ApprovalResult {
  approved: boolean
  reason?: string
}

/** How one gate decision was reached. */
export type ApprovalSource =
  | "not-required"
  | "auto-approve-env"
  | "deny-destructive-env"
  | "non-tty-skip-destructive"
  | "non-tty-approve"
  | "interactive"
  | "interactive-timeout"
  | "interactive-denied"

/** One recorded gate decision, so a run can be audited after the fact. */
export interface ApprovalDecision {
  /** Gate name (`destructive_tools`, `privilege_escalation`, …) or tool name. */
  gate: string
  kind: "phase" | "tool"
  phase?: string
  target: string
  approved: boolean
  reason: string
  source: ApprovalSource
  at: string
}

/**
 * Set to `1` to make destructive gates refuse instead of auto-approving.
 *
 * `ARGUS_AUTO_APPROVE=1` is required for unattended runs, which meant the
 * protective path — a gate actually blocking a destructive phase or tool —
 * was never exercised by any automated run. With this set, the same unattended
 * run proves the block works: the phase is skipped and the reason is recorded.
 */
const DENY_DESTRUCTIVE_ENV = "ARGUS_DENY_DESTRUCTIVE"

function deniesDestructive(): boolean {
  const raw = process.env[DENY_DESTRUCTIVE_ENV]
  return raw === "1" || raw?.toLowerCase() === "true"
}

export class ApprovalService {
  private gates = new Map<string, ApprovalGate>()

  /**
   * Every gate decision this service has made, in order.
   *
   * With `ARGUS_AUTO_APPROVE=1` the prompts are silent, so this is the only
   * record that a destructive phase or tool was gated at all — and with
   * `ARGUS_DENY_DESTRUCTIVE=1` it is the record that the gate refused.
   */
  readonly decisions: ApprovalDecision[] = []

  constructor() {
    this.registerDefaultGates()
  }

  /** Record one decision and echo it to stderr as an auditable line. */
  private record(decision: Omit<ApprovalDecision, "at">): ApprovalResult {
    const at = new Date().toISOString()
    this.decisions.push({ ...decision, at })
    process.stderr.write(
      `[approval] ${decision.kind}=${decision.gate} approved=${decision.approved} ` +
      `source=${decision.source}${decision.phase ? ` phase=${decision.phase}` : ""} — ${decision.reason}\n`,
    )
    return { approved: decision.approved, reason: decision.reason }
  }

  /** Decisions involving a destructive gate or destructive tool. */
  get destructiveDecisions(): ApprovalDecision[] {
    return this.decisions.filter(
      (d) => d.gate === "destructive_tools" || d.gate === "privilege_escalation" || d.approved === false,
    )
  }

  private registerDefaultGates(): void {
    this.registerGate({
      name: "destructive_tools",
      label: "Destructive Tools",
      require_confirmation: true,
      destructive: true,
      auth_testing: false,
      privilege_escalation: false,
    })
    this.registerGate({
      name: "auth_testing",
      label: "Authentication Testing",
      require_confirmation: false,
      destructive: false,
      auth_testing: true,
      privilege_escalation: false,
    })
    this.registerGate({
      name: "privilege_escalation",
      label: "Privilege Escalation Testing",
      require_confirmation: true,
      destructive: false,
      auth_testing: false,
      privilege_escalation: true,
    })
  }

  registerGate(gate: ApprovalGate): void {
    this.gates.set(gate.name, gate)
  }

  getGate(name: string): ApprovalGate | undefined {
    return this.gates.get(name)
  }

  getRequiredGates(workflowApprovalRequired: Record<string, boolean> | undefined): ApprovalGate[] {
    if (!workflowApprovalRequired) return []
    const gates: ApprovalGate[] = []
    for (const [name, required] of Object.entries(workflowApprovalRequired)) {
      if (!required) continue
      const gate = this.gates.get(name)
      if (gate) {
        gates.push(gate)
      } else {
        // Log a warning — an unknown gate name means the workflow references
        // a gate that was never registered. Without this warning, the phase
        // would silently proceed without the required approval.
        console.warn(`[approval] Unknown gate "${name}" in workflow approval_required — no gate registered for this name`)
      }
    }
    return gates
  }

  needsApproval(phase: PhaseExecutionRequest, requiredGates: ApprovalGate[]): ApprovalGate | null {
    // Match gates by name using the approval_gate field from the phase definition
    if (!phase.approvalGateName) return null
    return requiredGates.find((g) => g.name === phase.approvalGateName) ?? null
  }

  async requestApproval(gate: ApprovalGate, phaseName: string, target: string): Promise<ApprovalResult> {
    if (!gate.require_confirmation) {
      return this.record({
        gate: gate.name,
        kind: "phase",
        phase: phaseName,
        target,
        approved: true,
        reason: "Gate does not require confirmation",
        source: "not-required",
      })
    }

    process.stderr.write(`\n⚠  Approval Required: ${gate.label}\n`)
    process.stderr.write(`   Phase: ${phaseName}\n`)
    process.stderr.write(`   Target: ${target}\n`)
    process.stderr.write(`   This operation may be destructive or modify the target state.\n`)
    process.stderr.write(`   Proceed? [y/N] `)

    const base = { gate: gate.name, kind: "phase" as const, phase: phaseName, target }

    // Explicit refusal, checked before auto-approve so it wins. Lets an
    // unattended run prove the block path (see DENY_DESTRUCTIVE_ENV).
    if (gate.destructive && deniesDestructive()) {
      process.stderr.write(` (${DENY_DESTRUCTIVE_ENV}=1 — refused)\n\n`)
      return this.record({
        ...base,
        approved: false,
        reason: `${DENY_DESTRUCTIVE_ENV}=1 — destructive gate refused`,
        source: "deny-destructive-env",
      })
    }

    // Headless automation: explicit auto-approve via environment variable.
    // Logs an auditable timestamp instead of waiting for human input.
    if (process.env.ARGUS_AUTO_APPROVE === "1") {
      const timestamp = new Date().toISOString()
      process.stderr.write(` (ARGUS_AUTO_APPROVE=1 — auto-approved at ${timestamp})\n\n`)
      return this.record({
        ...base,
        approved: true,
        reason: `Auto-approved at ${timestamp}`,
        source: "auto-approve-env",
      })
    }

    // Non-TTY stdout (TUI mode):
    //   ARGUS_AUTO_APPROVE=1 → auto-approve regardless of destructive flag
    //   Otherwise → auto-skip destructive gates, auto-approve non-destructive
    if (!process.stdout.isTTY) {
      if (gate.destructive) {
        process.stderr.write(" (non-TTY — auto-skip destructive gate)\n\n")
        return this.record({
          ...base,
          approved: false,
          reason: "Non-TTY — destructive gate auto-skipped",
          source: "non-tty-skip-destructive",
        })
      }
      const timestamp = new Date().toISOString()
      process.stderr.write(` (non-TTY — auto-approved at ${timestamp})\n\n`)
      return this.record({
        ...base,
        approved: true,
        reason: `Auto-approved (non-TTY) at ${timestamp}`,
        source: "non-tty-approve",
      })
    }

    const answer = await this.promptConfirmation("Proceed? [y/N] ", "Skipping phase.")
    return this.record({
      ...base,
      approved: answer.approved,
      reason: answer.reason ?? (answer.approved ? "Approved interactively" : "Skipped phase"),
      source: answer.reason === "Confirmation timed out"
        ? "interactive-timeout"
        : answer.approved ? "interactive" : "interactive-denied",
    })
  }

  /**
   * Per-tool destructive confirmation (Task 4.1).
   *
   * Prompt the user before running a tool that is marked `destructive: true`
   * in the tool definitions. This runs AFTER phase-level approval, giving
   * users a second safety prompt before individual destructive tools execute.
   *
   * Respects the same auto-approve and non-TTY policies as phase-level gates:
   *   - ARGUS_AUTO_APPROVE=1 → auto-approved with audit timestamp
   *   - Non-TTY → auto-approved (phase was already approved at this point)
   *   - TTY → interactive prompt
   *
   * @returns { approved: false, reason: "..." } when the user declines or
   *          the tool times out, allowing the caller to skip just this tool
   *          without aborting the entire phase.
   */
  async confirmDestructiveTool(toolName: string, toolLabel: string, target: string): Promise<ApprovalResult> {
    const base = { gate: toolName, kind: "tool" as const, target }

    // Explicit refusal outranks auto-approve, so the tool-level gate can be
    // exercised in an unattended run.
    if (deniesDestructive()) {
      return this.record({
        ...base,
        approved: false,
        reason: `${DENY_DESTRUCTIVE_ENV}=1 — destructive tool refused`,
        source: "deny-destructive-env",
      })
    }

    // Headless automation: auto-approve
    if (process.env.ARGUS_AUTO_APPROVE === "1") {
      const timestamp = new Date().toISOString()
      return this.record({
        ...base,
        approved: true,
        reason: `Auto-approved at ${timestamp}`,
        source: "auto-approve-env",
      })
    }

    // Non-TTY: auto-approve (phase was already approved, this is just an extra safety prompt)
    if (!process.stdout.isTTY) {
      return this.record({
        ...base,
        approved: true,
        reason: "Auto-approved (non-TTY): phase was already approved",
        source: "non-tty-approve",
      })
    }

    process.stderr.write(`\n⚠  Destructive Tool Confirmation\n`)
    process.stderr.write(`   Tool: ${toolLabel} (${toolName})\n`)
    process.stderr.write(`   Target: ${target}\n`)
    process.stderr.write(`   This tool modifies data or system state on the target.\n`)

    const answer = await this.promptConfirmation("Run this tool? [y/N] ", "Skipping destructive tool.")
    return this.record({
      ...base,
      approved: answer.approved,
      reason: answer.reason ?? (answer.approved ? "Approved interactively" : "Skipped destructive tool"),
      source: answer.reason === "Confirmation timed out"
        ? "interactive-timeout"
        : answer.approved ? "interactive" : "interactive-denied",
    })
  }

  /**
   * Shared interactive prompt logic.
   * Reads a single line from stdin with a 30-second timeout.
   */
  private promptConfirmation(prompt: string, denyMessage: string): Promise<ApprovalResult> {
    return new Promise((resolve) => {
      process.stderr.write(`   ${prompt}`)

      const stdin = process.stdin
      stdin.resume()

      const done = (result: ApprovalResult): void => {
        stdin.pause()
        stdin.removeAllListeners("data")
        clearTimeout(timer)
        resolve(result)
      }

      stdin.once("data", (data: Buffer) => {
        const input = data.toString().trim().toLowerCase()
        if (input === "y" || input === "yes") {
          process.stderr.write("\n")
          done({ approved: true })
        } else {
          process.stderr.write(`   ${denyMessage}\n\n`)
          done({ approved: false, reason: "User declined confirmation" })
        }
      })

      // Timeout after 30 seconds
      const timer = setTimeout(() => {
        process.stderr.write("\n   Confirmation timed out.\n\n")
        done({ approved: false, reason: "Confirmation timed out" })
      }, 30000)
    })
  }
}

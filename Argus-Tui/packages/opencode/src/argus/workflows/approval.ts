import type { PhaseExecutionRequest } from "../planner/types"
import type { ApprovalGate } from "./types"

export interface ApprovalResult {
  approved: boolean
  reason?: string
}

export class ApprovalService {
  private gates = new Map<string, ApprovalGate>()

  constructor() {
    this.registerDefaultGates()
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
    if (!gate.require_confirmation) return { approved: true }

    process.stderr.write(`\n⚠  Approval Required: ${gate.label}\n`)
    process.stderr.write(`   Phase: ${phaseName}\n`)
    process.stderr.write(`   Target: ${target}\n`)
    process.stderr.write(`   This operation may be destructive or modify the target state.\n`)
    process.stderr.write(`   Proceed? [y/N] `)

    // Headless automation: explicit auto-approve via environment variable.
    // Logs an auditable timestamp instead of waiting for human input.
    if (process.env.ARGUS_AUTO_APPROVE === "1") {
      const timestamp = new Date().toISOString()
      process.stderr.write(` (ARGUS_AUTO_APPROVE=1 — auto-approved at ${timestamp})\n\n`)
      return { approved: true, reason: `Auto-approved at ${timestamp}` }
    }

    // Non-TTY stdout (TUI mode):
    //   ARGUS_AUTO_APPROVE=1 → auto-approve regardless of destructive flag
    //   Otherwise → auto-skip destructive gates, auto-approve non-destructive
    if (!process.stdout.isTTY) {
      if (gate.destructive && process.env.ARGUS_AUTO_APPROVE !== "1") {
        process.stderr.write(" (non-TTY — auto-skip destructive gate)\n\n")
        return { approved: false, reason: "Non-TTY — destructive gate auto-skipped" }
      }
      const timestamp = new Date().toISOString()
      process.stderr.write(` (non-TTY — ${process.env.ARGUS_AUTO_APPROVE === "1" ? `auto-approved (ARGUS_AUTO_APPROVE=1) at ${timestamp}` : "auto-approved"})\n\n`)
      return { approved: true, reason: process.env.ARGUS_AUTO_APPROVE === "1" ? `Auto-approved at ${timestamp}` : undefined }
    }

    return this.promptConfirmation("Proceed? [y/N] ", "Skipping phase.")
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
    // Headless automation: auto-approve
    if (process.env.ARGUS_AUTO_APPROVE === "1") {
      const timestamp = new Date().toISOString()
      return { approved: true, reason: `Auto-approved at ${timestamp}` }
    }

    // Non-TTY: auto-approve (phase was already approved, this is just an extra safety prompt)
    if (!process.stdout.isTTY) {
      return { approved: true }
    }

    process.stderr.write(`\n⚠  Destructive Tool Confirmation\n`)
    process.stderr.write(`   Tool: ${toolLabel} (${toolName})\n`)
    process.stderr.write(`   Target: ${target}\n`)
    process.stderr.write(`   This tool modifies data or system state on the target.\n`)

    return this.promptConfirmation("Run this tool? [y/N] ", "Skipping destructive tool.")
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

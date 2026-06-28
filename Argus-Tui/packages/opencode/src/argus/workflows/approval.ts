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
    return Object.entries(workflowApprovalRequired)
      .filter(([_, required]) => required)
      .map(([name]) => this.gates.get(name))
      .filter((g): g is ApprovalGate => g !== undefined)
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

    // Non-TTY stdout (TUI mode): auto-approve non-destructive, auto-skip destructive
    if (!process.stdout.isTTY) {
      if (gate.destructive) {
        process.stderr.write(" (non-TTY — auto-skip destructive gate)\n\n")
        return { approved: false, reason: "Non-TTY — destructive gate auto-skipped" }
      }
      process.stderr.write(" (non-TTY — auto-approved)\n\n")
      return { approved: true }
    }

    return new Promise((resolve) => {
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
          process.stderr.write("   Skipping phase.\n\n")
          done({ approved: false, reason: "User declined approval" })
        }
      })

      // Timeout after 30 seconds
      const timer = setTimeout(() => {
        process.stderr.write("\n   Approval timed out.\n\n")
        done({ approved: false, reason: "Approval timed out" })
      }, 30000)
    })
  }
}

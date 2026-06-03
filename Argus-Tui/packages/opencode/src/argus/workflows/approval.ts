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
    const caps = new Set(phase.requiredCapabilities.map((c) => c.toString()))

    for (const gate of requiredGates) {
      if (gate.destructive && caps.has("vulnerability_scanning")) return gate
      if (gate.auth_testing && (caps.has("auth_detection") || caps.has("credential_analysis"))) return gate
      if (gate.privilege_escalation && caps.has("browser_verification")) return gate
    }

    return null
  }

  async requestApproval(gate: ApprovalGate, phaseName: string, target: string): Promise<ApprovalResult> {
    if (!gate.require_confirmation) return { approved: true }

    process.stderr.write(`\n⚠  Approval Required: ${gate.label}\n`)
    process.stderr.write(`   Phase: ${phaseName}\n`)
    process.stderr.write(`   Target: ${target}\n`)
    process.stderr.write(`   This operation may be destructive or modify the target state.\n`)
    process.stderr.write(`   Proceed? [y/N] `)

    return new Promise((resolve) => {
      const stdin = process.stdin
      stdin.resume()
      stdin.once("data", (data: Buffer) => {
        stdin.pause()
        const input = data.toString().trim().toLowerCase()
        if (input === "y" || input === "yes") {
          process.stderr.write("\n")
          resolve({ approved: true })
        } else {
          process.stderr.write("   Skipping phase.\n\n")
          resolve({ approved: false, reason: "User declined approval" })
        }
      })
    })
  }
}

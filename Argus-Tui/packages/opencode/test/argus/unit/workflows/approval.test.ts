import { describe, expect, test } from "bun:test"
import { ApprovalService } from "../../../../src/argus/workflows/approval"
import { Capability } from "../../../../src/argus/planner/capabilities"
import type { PhaseExecutionRequest } from "../../../../src/argus/planner/types"

function makePhase(caps: Capability[]): PhaseExecutionRequest {
  return {
    phaseId: "test-phase",
    workflowName: "test-workflow",
    target: "https://example.com",
    requiredCapabilities: caps,
    config: {},
    previousPhaseResults: [],
  }
}

describe("ApprovalService", () => {
  describe("getRequiredGates", () => {
    test("Returns empty array for undefined input", () => {
      const service = new ApprovalService()
      expect(service.getRequiredGates(undefined)).toEqual([])
    })

    test("Returns empty array for empty object", () => {
      const service = new ApprovalService()
      expect(service.getRequiredGates({})).toEqual([])
    })

    test("Returns gates only for keys with true values", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ destructive_tools: true, auth_testing: false, privilege_escalation: true })
      expect(gates).toHaveLength(2)
      expect(gates[0].name).toBe("destructive_tools")
      expect(gates[1].name).toBe("privilege_escalation")
    })

    test("Skips unknown gate names", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ unknown_gate: true, destructive_tools: true })
      expect(gates).toHaveLength(1)
      expect(gates[0].name).toBe("destructive_tools")
    })
  })

  describe("needsApproval", () => {
    test("Returns destructive gate when phase has VULNERABILITY_SCANNING and gate is destructive", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ destructive_tools: true })
      const phase = makePhase([Capability.VULNERABILITY_SCANNING])
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("destructive_tools")
    })

    test("Returns auth_testing gate when phase has AUTH_DETECTION and gate is auth testing", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ auth_testing: true })
      const phase = makePhase([Capability.AUTH_DETECTION])
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("auth_testing")
    })

    test("Returns auth_testing gate when phase has CREDENTIAL_ANALYSIS and gate is auth testing", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ auth_testing: true })
      const phase = makePhase([Capability.CREDENTIAL_ANALYSIS])
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("auth_testing")
    })

    test("Returns priv-esc gate when phase has BROWSER_VERIFICATION and gate is privilege_escalation", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ privilege_escalation: true })
      const phase = makePhase([Capability.BROWSER_VERIFICATION])
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("privilege_escalation")
    })

    test("Returns null when no gates match", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ auth_testing: true })
      const phase = makePhase([Capability.PORT_SCANNING])
      const result = service.needsApproval(phase, gates)
      expect(result).toBeNull()
    })

    test("Returns null when requiredGates is empty", () => {
      const service = new ApprovalService()
      const phase = makePhase([Capability.VULNERABILITY_SCANNING])
      const result = service.needsApproval(phase, [])
      expect(result).toBeNull()
    })
  })

  describe("requestApproval", () => {
    test("Auto-approves when gate has require_confirmation: false", async () => {
      const service = new ApprovalService()
      const gate = service.getGate("auth_testing")!
      expect(gate.require_confirmation).toBe(false)
      const result = await service.requestApproval(gate, "test", "target")
      expect(result).toEqual({ approved: true })
    })

    test("Returns { approved: false, reason: \"User declined approval\" } for non-confirmed gates", async () => {
      const origStdin = process.stdin
      const origWrite = process.stderr.write
      process.stderr.write = () => true

      const dataCallbacks: Array<(data: Buffer) => void> = []
      const mockStdin = {
        resume: () => {},
        pause: () => {},
        once: (event: string, cb: (data: Buffer) => void) => {
          if (event === "data") dataCallbacks.push(cb)
        },
      } as any

      process.stdin = mockStdin

      try {
        const service = new ApprovalService()
        const gate = service.getGate("destructive_tools")!
        expect(gate.require_confirmation).toBe(true)

        const promise = service.requestApproval(gate, "test-phase", "https://example.com")

        dataCallbacks[0]?.(Buffer.from("n\n"))

        const result = await promise
        expect(result).toEqual({ approved: false, reason: "User declined approval" })
      } finally {
        process.stdin = origStdin
        process.stderr.write = origWrite
      }
    })
  })

  describe("registerGate / getGate", () => {
    test("registerGate adds a new gate, getGate retrieves it, returns undefined for unknown", () => {
      const service = new ApprovalService()
      expect(service.getGate("custom_gate")).toBeUndefined()

      service.registerGate({
        name: "custom_gate",
        label: "Custom Gate",
        require_confirmation: true,
        destructive: false,
        auth_testing: false,
        privilege_escalation: false,
      })

      const gate = service.getGate("custom_gate")
      expect(gate).toBeDefined()
      expect(gate!.label).toBe("Custom Gate")
    })
  })

  describe("Default gates", () => {
    test("Default gates are registered on construction", () => {
      const service = new ApprovalService()
      expect(service.getGate("destructive_tools")).toBeDefined()
      expect(service.getGate("auth_testing")).toBeDefined()
      expect(service.getGate("privilege_escalation")).toBeDefined()
    })
  })
})

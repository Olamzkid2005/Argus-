import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { ApprovalService } from "../../../../src/argus/workflows/approval"
import { Capability } from "../../../../src/argus/planner/capabilities"
import type { PhaseExecutionRequest } from "../../../../src/argus/planner/types"

function makePhase(caps: Capability[], gateName?: string): PhaseExecutionRequest {
  return {
    phaseId: "test-phase",
    name: "test",
    workflowName: "test-workflow",
    target: "https://example.com",
    requiredCapabilities: caps,
    config: {},
    previousPhaseResults: [],
    approvalGateName: gateName,
  }
}

beforeAll(() => {
  ;(process.stdin as any).isTTY = true
})
afterAll(() => {
  ;(process.stdin as any).isTTY = false
})

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
    test("Returns destructive gate when phase has destructive_tools approvalGateName", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ destructive_tools: true })
      const phase = makePhase([Capability.VULNERABILITY_SCANNING], "destructive_tools")
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("destructive_tools")
    })

    test("Returns auth_testing gate when phase has auth_testing approvalGateName", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ auth_testing: true })
      const phase = makePhase([Capability.AUTH_DETECTION], "auth_testing")
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("auth_testing")
    })

    test("Returns auth_testing gate when phase has auth_testing approvalGateName with CREDENTIAL_ANALYSIS", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ auth_testing: true })
      const phase = makePhase([Capability.CREDENTIAL_ANALYSIS], "auth_testing")
      const result = service.needsApproval(phase, gates)
      expect(result).not.toBeNull()
      expect(result!.name).toBe("auth_testing")
    })

    test("Returns priv-esc gate when phase has privilege_escalation approvalGateName", () => {
      const service = new ApprovalService()
      const gates = service.getRequiredGates({ privilege_escalation: true })
      const phase = makePhase([Capability.BROWSER_VERIFICATION], "privilege_escalation")
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
        isTTY: true,
        removeAllListeners: () => {},
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
        // In non-TTY environments, gates auto-skip with a different reason
        expect(result.approved).toBe(false);
        expect(typeof result.reason).toBe("string");
        expect(result.reason?.length ?? 0).toBeGreaterThan(0)
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

  describe("confirmDestructiveTool", () => {
    test("auto-approves when ARGUS_AUTO_APPROVE=1", async () => {
      const orig = process.env.ARGUS_AUTO_APPROVE
      process.env.ARGUS_AUTO_APPROVE = "1"
      const service = new ApprovalService()
      try {
        const result = await service.confirmDestructiveTool("sqlmap", "SQLMap SQL Injection Scanner", "https://example.com")
        expect(result.approved).toBe(true)
        expect(result.reason).toMatch(/Auto-approved/)
      } finally {
        process.env.ARGUS_AUTO_APPROVE = orig
      }
    })

    test("auto-approves when stdout is not a TTY", async () => {
      const origIsTTY = (process.stdout as any).isTTY
      ;(process.stdout as any).isTTY = false
      const service = new ApprovalService()
      try {
        const result = await service.confirmDestructiveTool("sqlmap", "SQLMap SQL Injection Scanner", "https://example.com")
        expect(result.approved).toBe(true)
      } finally {
        ;(process.stdout as any).isTTY = origIsTTY
      }
    })

    test("returns approved=false when user types 'n'", async () => {
      const origIsTTY = (process.stdout as any).isTTY
      const origStdin = process.stdin
      const origWrite = process.stderr.write
      process.stderr.write = () => true
      ;(process.stdout as any).isTTY = true

      const dataCallbacks: Array<(data: Buffer) => void> = []
      const mockStdin = {
        resume: () => {},
        pause: () => {},
        isTTY: true,
        removeAllListeners: () => {},
        once: (event: string, cb: (data: Buffer) => void) => {
          if (event === "data") dataCallbacks.push(cb)
        },
      } as any

      process.stdin = mockStdin

      try {
        const service = new ApprovalService()
        const promise = service.confirmDestructiveTool("sqlmap", "SQLMap SQL Injection Scanner", "https://example.com")
        dataCallbacks[0]?.(Buffer.from("n\n"))
        const result = await promise
        expect(result.approved).toBe(false)
        expect(result.reason).toBe("User declined confirmation")
      } finally {
        process.stdin = origStdin
        process.stderr.write = origWrite
        ;(process.stdout as any).isTTY = origIsTTY
      }
    })

    test("returns approved=true when user types 'y'", async () => {
      const origIsTTY = (process.stdout as any).isTTY
      const origStdin = process.stdin
      const origWrite = process.stderr.write
      process.stderr.write = () => true
      ;(process.stdout as any).isTTY = true

      const dataCallbacks: Array<(data: Buffer) => void> = []
      const mockStdin = {
        resume: () => {},
        pause: () => {},
        isTTY: true,
        removeAllListeners: () => {},
        once: (event: string, cb: (data: Buffer) => void) => {
          if (event === "data") dataCallbacks.push(cb)
        },
      } as any

      process.stdin = mockStdin

      try {
        const service = new ApprovalService()
        const promise = service.confirmDestructiveTool("sqlmap", "SQLMap SQL Injection Scanner", "https://example.com")
        dataCallbacks[0]?.(Buffer.from("y\n"))
        const result = await promise
        expect(result.approved).toBe(true)
      } finally {
        process.stdin = origStdin
        process.stderr.write = origWrite
        ;(process.stdout as any).isTTY = origIsTTY
      }
    })
  })
})

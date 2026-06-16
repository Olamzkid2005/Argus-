import { describe, expect, test, beforeEach } from "bun:test"
import { ToolHealthMonitor } from "../../../src/argus/bridge/tool-health"
import type { ToolHealthRecord } from "../../../src/argus/bridge/tool-health"

describe("ToolHealthMonitor", () => {
  let monitor: ToolHealthMonitor

  beforeEach(() => {
    monitor = new ToolHealthMonitor({ maxConsecutiveFailures: 5, cooldownMs: 100 })
  })

  describe("recordSuccess", () => {
    test("updates consecutiveFailures to 0", () => {
      monitor.recordFailure("nuclei", "timeout")
      monitor.recordFailure("nuclei", "timeout")
      monitor.recordSuccess("nuclei", 150)
      const status = monitor.getToolStatus("nuclei")!
      expect(status.consecutiveFailures).toBe(0)
    })

    test("closes open circuit", () => {
      for (let i = 0; i < 5; i++) monitor.recordFailure("nuclei", "err")
      expect(monitor.isHealthy("nuclei")).toBe(false)
      monitor.recordSuccess("nuclei", 100)
      expect(monitor.isHealthy("nuclei")).toBe(true)
    })

    test("updates avgDurationMs", () => {
      monitor.recordSuccess("nuclei", 100)
      monitor.recordSuccess("nuclei", 200)
      const status = monitor.getToolStatus("nuclei")!
      expect(status.avgDurationMs).toBe(150)
    })
  })

  describe("recordFailure", () => {
    test("increments consecutiveFailures", () => {
      monitor.recordFailure("nuclei", "timeout")
      monitor.recordFailure("nuclei", "connection refused")
      const status = monitor.getToolStatus("nuclei")!
      expect(status.consecutiveFailures).toBe(2)
    })

    test("opens circuit after max consecutive failures", () => {
      for (let i = 0; i < 5; i++) monitor.recordFailure("nuclei", `err ${i}`)
      const status = monitor.getToolStatus("nuclei")!
      expect(status.circuitOpen).toBe(true)
      expect(status.circuitOpenedAt).toBeGreaterThan(0)
    })

    test("does not open circuit below threshold", () => {
      for (let i = 0; i < 4; i++) monitor.recordFailure("nuclei", `err ${i}`)
      const status = monitor.getToolStatus("nuclei")!
      expect(status.circuitOpen).toBe(false)
    })

    test("increments totalFailures and totalCalls", () => {
      monitor.recordFailure("nuclei", "err")
      const status = monitor.getToolStatus("nuclei")!
      expect(status.totalFailures).toBe(1)
      expect(status.totalCalls).toBe(1)
    })
  })

  describe("isHealthy", () => {
    test("returns true for tool with no records", () => {
      expect(monitor.isHealthy("unknown-tool")).toBe(true)
    })

    test("returns true for healthy tool", () => {
      monitor.recordSuccess("nuclei", 50)
      expect(monitor.isHealthy("nuclei")).toBe(true)
    })

    test("returns false when circuit is open", () => {
      for (let i = 0; i < 5; i++) monitor.recordFailure("nuclei", `err ${i}`)
      expect(monitor.isHealthy("nuclei")).toBe(false)
    })

    test("returns true after cooldown elapses", () => {
      const shortCooldown = new ToolHealthMonitor({ maxConsecutiveFailures: 2, cooldownMs: 10 })
      shortCooldown.recordFailure("x", "e1")
      shortCooldown.recordFailure("x", "e2")
      expect(shortCooldown.isHealthy("x")).toBe(false)
      // Wait for cooldown
      return new Promise<void>((resolve) => {
        setTimeout(() => {
          expect(shortCooldown.isHealthy("x")).toBe(true)
          resolve()
        }, 20)
      })
    })
  })

  describe("getStatus", () => {
    test("returns all records", () => {
      monitor.recordSuccess("nuclei", 100)
      monitor.recordFailure("dalfox", "err")
      const statuses = monitor.getStatus()
      expect(statuses).toHaveLength(2)
      const names = statuses.map((r: ToolHealthRecord) => r.toolName).sort()
      expect(names).toEqual(["dalfox", "nuclei"])
    })
  })

  describe("resetAll", () => {
    test("closes all circuits and resets consecutive failures", () => {
      for (let i = 0; i < 5; i++) monitor.recordFailure("nuclei", `err ${i}`)
      for (let i = 0; i < 5; i++) monitor.recordFailure("dalfox", `err ${i}`)
      monitor.resetAll()
      const statuses = monitor.getStatus()
      for (const r of statuses) {
        expect(r.circuitOpen).toBe(false)
        expect(r.consecutiveFailures).toBe(0)
      }
    })
  })
})

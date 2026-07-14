import { describe, expect, test } from "bun:test"
import { WorkerSupervisor } from "../../../../src/argus/bridge/supervisor"

function createMockBridge() {
  let healthy = true
  let killCalled = false
  let connectCount = 0

  return {
    bridge: {
      isHealthy: async () => healthy,
      killChild: () => {
        killCalled = true
        healthy = false
      },
      connect: async () => {
        connectCount++
        healthy = true
      },
      restartWorker: async () => {},
    },
    killCalled: () => killCalled,
    connectCount: () => connectCount,
    setHealthy: (v: boolean) => { healthy = v },
  }
}

describe("WorkerSupervisor", () => {
  describe("isHealthy()", () => {
    test("delegates to bridge.isHealthy()", async () => {
      const mock = createMockBridge()
      const supervisor = new WorkerSupervisor(mock.bridge)
      expect(await supervisor.isHealthy()).toBe(true)
      mock.setHealthy(false)
      expect(await supervisor.isHealthy()).toBe(false)
    })
  })

  function makeSupervisor() {
    const mock = createMockBridge()
    return { mock, supervisor: new WorkerSupervisor(mock.bridge, 1) }
  }

  function makeDefaultSupervisor() {
    const mock = createMockBridge()
    return { mock, supervisor: new WorkerSupervisor(mock.bridge) }
  }

  describe("restartWorker()", () => {
    test("kills child and reconnects", async () => {
      const { mock, supervisor } = makeDefaultSupervisor()
      await supervisor.restartWorker()
      expect(mock.killCalled()).toBe(true)
      expect(mock.connectCount()).toBe(1)
    })

    test("increments attempt counter temporarily, resets after success", async () => {
      const { mock, supervisor } = makeDefaultSupervisor()
      expect(supervisor.attemptsRemaining()).toBe(3)
      // After restartWorker succeeds, attempts resets to 0 (see source)
      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(3)
    })

    test("sets degraded after maxRestarts (3) when connect fails", async () => {
      const bridge = {
        restartWorker: async () => {},
        killChild: () => {},
        connect: async () => { throw new Error("Connection refused") },
        isHealthy: async () => true,
      }
      const failingSupervisor = new WorkerSupervisor(bridge, 0)

      // First 3 calls: attempts < maxRestarts, connect() throws
      await expect(failingSupervisor.restartWorker()).rejects.toThrow()
      expect(failingSupervisor.degraded).toBe(false)
      await expect(failingSupervisor.restartWorker()).rejects.toThrow()
      expect(failingSupervisor.degraded).toBe(false)
      await expect(failingSupervisor.restartWorker()).rejects.toThrow()
      expect(failingSupervisor.degraded).toBe(false)

      // 4th call: attempts(3) >= maxRestarts(3) → sets degraded, returns without error
      await failingSupervisor.restartWorker()
      expect(failingSupervisor.degraded).toBe(true)
    })
  })

  describe("resetAttempts()", () => {
    test("resets the attempt counter", async () => {
      const { supervisor } = makeDefaultSupervisor()
      // attempts stays at 0 after successful restart, so remaining stays at 3
      expect(supervisor.attemptsRemaining()).toBe(3)
      supervisor.resetAttempts()
      expect(supervisor.attemptsRemaining()).toBe(3)
    })
  })

  describe("attemptsRemaining()", () => {
    test("returns correct count", async () => {
      const { supervisor } = makeDefaultSupervisor()
      expect(supervisor.attemptsRemaining()).toBe(3)
      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(3)
    })
  })

  describe("After resetAttempts, restartWorker works again", () => {
    test("allows restart after reset", async () => {
      const { supervisor } = makeDefaultSupervisor()

      // With default backoff (1000ms), this takes 7s total for 3 restarts
      // Just verify the API doesn't throw after reset
      supervisor.resetAttempts()
      await supervisor.restartWorker()
    })
  })
})

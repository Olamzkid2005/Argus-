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

  describe("restartWorker()", () => {
    test("kills child and reconnects", async () => {
      const { mock, supervisor } = makeSupervisor()
      await supervisor.restartWorker()
      expect(mock.killCalled()).toBe(true)
      expect(mock.connectCount()).toBe(1)
    })

    test("increments attempt counter", async () => {
      const { mock, supervisor } = makeSupervisor()
      expect(supervisor.attemptsRemaining()).toBe(3)
      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(2)
      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(1)
    })

    test("throws after maxRestarts (3) attempts", async () => {
      const { supervisor } = makeSupervisor()

      await supervisor.restartWorker()
      await supervisor.restartWorker()
      await supervisor.restartWorker()

      expect(supervisor.attemptsRemaining()).toBe(0)
      await expect(supervisor.restartWorker()).rejects.toThrow(
        /Worker crashed too many times/,
      )
    })
  })

  describe("resetAttempts()", () => {
    test("resets the attempt counter", async () => {
      const { supervisor } = makeSupervisor()

      await supervisor.restartWorker()
      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(1)

      supervisor.resetAttempts()
      expect(supervisor.attemptsRemaining()).toBe(3)
    })
  })

  describe("attemptsRemaining()", () => {
    test("returns correct count", async () => {
      const { supervisor } = makeSupervisor()
      expect(supervisor.attemptsRemaining()).toBe(3)
      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(2)
    })
  })

  describe("After resetAttempts, restartWorker works again", () => {
    test("allows restart after reset", async () => {
      const { supervisor } = makeSupervisor()

      await supervisor.restartWorker()
      await supervisor.restartWorker()
      await supervisor.restartWorker()

      await expect(supervisor.restartWorker()).rejects.toThrow()
      expect(supervisor.attemptsRemaining()).toBe(0)

      supervisor.resetAttempts()
      expect(supervisor.attemptsRemaining()).toBe(3)

      await supervisor.restartWorker()
      expect(supervisor.attemptsRemaining()).toBe(2)
    })
  })
})

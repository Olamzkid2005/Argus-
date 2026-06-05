import { describe, it, expect, mock } from "bun:test"
import { ChainedScenario } from "../../../../../src/argus/browser/verifiers/chained-scenario"
import { Confidence } from "../../../../../src/argus/shared/types"

const passingScenario = {
  name: "passing",
  description: "Always passes",
  setup: mock(() => Promise.resolve()),
  execute: mock(() => Promise.resolve()),
  verify: mock(() => Promise.resolve({ passed: true, confidence: Confidence.HIGH, evidence: [], summary: "Passed" })),
  collectEvidence: mock(() => Promise.resolve({
    packageId: "p1",
    findingId: "f1",
    artifacts: [{ path: "test.txt", type: "screenshot" as const }],
    packageHash: "hash123",
    createdAt: new Date().toISOString(),
  })),
  cleanup: mock(() => Promise.resolve()),
}

const failingScenario = {
  name: "failing",
  description: "Always fails",
  setup: mock(() => Promise.resolve()),
  execute: mock(() => Promise.resolve()),
  verify: mock(() => Promise.resolve({ passed: false, confidence: Confidence.INFORMATIONAL, evidence: [], summary: "Failed" })),
  collectEvidence: mock(() => Promise.resolve({
    packageId: "p2",
    findingId: "f2",
    artifacts: [{ path: "fail.txt", type: "log" as const }],
    packageHash: "hash456",
    createdAt: new Date().toISOString(),
  })),
  cleanup: mock(() => Promise.resolve()),
}

const errorScenario = {
  name: "error",
  description: "Throws error",
  setup: mock(() => { throw new Error("Setup error") }),
  execute: mock(() => { throw new Error("Execute error") }),
  verify: mock(() => { throw new Error("Verify error") }),
  collectEvidence: mock(() => { throw new Error("Collect error") }),
  cleanup: mock(() => { throw new Error("Cleanup error") }),
}

describe("ChainedScenario", () => {
  it("constructor sets stages, name (joined), and description", () => {
    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
      { scenario: failingScenario, name: "stage2" },
    ])
    expect(chain.name).toBe("stage1→stage2")
    expect(chain.description).toBe("Chained verification: stage1→stage2")
  })

  it("setup() calls setup on all stages", async () => {
    passingScenario.setup.mockReset()
    failingScenario.setup.mockReset()
    passingScenario.setup.mockImplementation(() => Promise.resolve())
    failingScenario.setup.mockImplementation(() => Promise.resolve())

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
      { scenario: failingScenario, name: "stage2" },
    ])
    await chain.setup()
    expect(passingScenario.setup).toHaveBeenCalledTimes(1)
    expect(failingScenario.setup).toHaveBeenCalledTimes(1)
  })

  it("setup() throws when a stage's setup fails, sets chainFailed", async () => {
    errorScenario.setup.mockReset()
    passingScenario.setup.mockReset()
    passingScenario.setup.mockImplementation(() => Promise.resolve())
    errorScenario.setup.mockImplementation(() => { throw new Error("Setup error") })

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
      { scenario: errorScenario, name: "stage2" },
    ])
    await expect(chain.setup()).rejects.toThrow('Setup failed at stage "stage2"')
    const chain2 = new ChainedScenario([
      { scenario: errorScenario, name: "stage1" },
      { scenario: passingScenario, name: "stage2" },
    ])
    await expect(chain2.setup()).rejects.toThrow('Setup failed at stage "stage1"')
  })

  it("execute() calls execute on all stages", async () => {
    passingScenario.execute.mockReset()
    passingScenario.setup.mockReset()
    failingScenario.execute.mockReset()
    failingScenario.setup.mockReset()
    passingScenario.setup.mockImplementation(() => Promise.resolve())
    failingScenario.setup.mockImplementation(() => Promise.resolve())
    passingScenario.execute.mockImplementation(() => Promise.resolve())
    failingScenario.execute.mockImplementation(() => Promise.resolve())

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
      { scenario: failingScenario, name: "stage2" },
    ])
    await chain.setup()
    await chain.execute()
    expect(passingScenario.execute).toHaveBeenCalledTimes(1)
    expect(failingScenario.execute).toHaveBeenCalledTimes(1)
  })

  it("execute() skips remaining if chainFailed", async () => {
    errorScenario.setup.mockReset()
    errorScenario.execute.mockReset()
    passingScenario.setup.mockReset()
    passingScenario.execute.mockReset()
    passingScenario.setup.mockImplementation(() => Promise.resolve())
    passingScenario.execute.mockImplementation(() => Promise.resolve())
    errorScenario.setup.mockImplementation(() => { throw new Error("Setup error") })
    errorScenario.execute.mockImplementation(() => Promise.resolve())

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
      { scenario: errorScenario, name: "stage2" },
    ])
    await expect(chain.setup()).rejects.toThrow()
    passingScenario.execute.mockReset()
    errorScenario.execute.mockReset()
    passingScenario.execute.mockImplementation(() => Promise.resolve())
    errorScenario.execute.mockImplementation(() => Promise.resolve())
    await chain.execute()
    expect(passingScenario.execute).toHaveBeenCalledTimes(0)
    expect(errorScenario.execute).toHaveBeenCalledTimes(0)
  })

  it("execute() throws when a stage's execute fails", async () => {
    errorScenario.setup.mockReset()
    errorScenario.execute.mockReset()
    passingScenario.setup.mockReset()
    passingScenario.execute.mockReset()
    passingScenario.setup.mockImplementation(() => Promise.resolve())
    passingScenario.execute.mockImplementation(() => Promise.resolve())
    errorScenario.setup.mockImplementation(() => Promise.resolve())
    errorScenario.execute.mockImplementation(() => { throw new Error("Execute error") })

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
      { scenario: errorScenario, name: "stage2" },
    ])
    await chain.setup()
    await expect(chain.execute()).rejects.toThrow('Execute failed at stage "stage2"')
  })

  it("verify() returns allPassed=true with HIGH confidence when all pass", async () => {
    passingScenario.verify.mockReset()
    passingScenario.verify.mockImplementation(() => Promise.resolve({ passed: true, confidence: Confidence.HIGH, evidence: [], summary: "Passed" }))

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
    ])
    const result = await chain.verify()
    expect(result.passed).toBe(true)
    expect(result.confidence).toBe(Confidence.HIGH)
  })

  it("verify() returns anyPassed with average confidence when mixed", async () => {
    passingScenario.verify.mockReset()
    failingScenario.verify.mockReset()
    passingScenario.verify.mockImplementation(() => Promise.resolve({ passed: true, confidence: Confidence.HIGH, evidence: [], summary: "Passed" }))
    failingScenario.verify.mockImplementation(() => Promise.resolve({ passed: false, confidence: Confidence.INFORMATIONAL, evidence: [], summary: "Failed" }))

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "pass" },
      { scenario: failingScenario, name: "fail" },
    ])
    const result = await chain.verify()
    expect(result.passed).toBe(true)
    expect(result.confidence).toBe(Math.round((Confidence.HIGH + Confidence.INFORMATIONAL) / 2))
  })

  it("verify() catches failures and adds failed VerifierResult", async () => {
    passingScenario.verify.mockReset()
    passingScenario.verify.mockImplementation(() => { throw new Error("Unexpected error") })

    const chain = new ChainedScenario([
      { scenario: passingScenario, name: "stage1" },
    ])
    const result = await chain.verify()
    expect(result.passed).toBe(false)
    expect(result.confidence).toBe(Confidence.INFORMATIONAL)
    expect(result.summary).toContain('Verification failed at stage "stage1"')
  })

  it("collectEvidence() collects from all stages and tags artifacts", async () => {
    const pScenario = {
      ...passingScenario,
      collectEvidence: mock(() => Promise.resolve({
        packageId: "p1",
        findingId: "f1",
        artifacts: [{ path: "a.txt", type: "screenshot" as const }],
        packageHash: "h1",
        createdAt: new Date().toISOString(),
      })),
    }
    const fScenario = {
      ...failingScenario,
      collectEvidence: mock(() => Promise.resolve({
        packageId: "p2",
        findingId: "f2",
        artifacts: [{ path: "b.txt", type: "log" as const }],
        packageHash: "h2",
        createdAt: new Date().toISOString(),
      })),
    }

    const chain = new ChainedScenario([
      { scenario: pScenario, name: "first" },
      { scenario: fScenario, name: "second" },
    ])
    const pkg = await chain.collectEvidence()
    expect(pkg.artifacts).toHaveLength(2)
    expect(pkg.artifacts[0].path).toBe("first/a.txt")
    expect(pkg.artifacts[1].path).toBe("second/b.txt")
    expect(pkg.packageHash).toBe("")
  })

  it("collectEvidence() skips stages that throw", async () => {
    const goodScenario = {
      ...passingScenario,
      collectEvidence: mock(() => Promise.resolve({
        packageId: "p1",
        findingId: "f1",
        artifacts: [{ path: "good.txt", type: "screenshot" as const }],
        packageHash: "h1",
        createdAt: new Date().toISOString(),
      })),
    }
    const badScenario = {
      ...errorScenario,
      collectEvidence: mock(() => { throw new Error("Boom") }),
    }

    const chain = new ChainedScenario([
      { scenario: goodScenario, name: "good" },
      { scenario: badScenario, name: "bad" },
    ])
    const pkg = await chain.collectEvidence()
    expect(pkg.artifacts).toHaveLength(1)
    expect(pkg.artifacts[0].path).toBe("good/good.txt")
  })

  it("cleanup() calls cleanup on all stages, best-effort", async () => {
    const cleanSpy1 = mock(() => Promise.resolve())
    const cleanSpy2 = mock(() => { throw new Error("Cleanup fail") })
    const s1 = { ...passingScenario, cleanup: cleanSpy1 }
    const s2 = { ...errorScenario, cleanup: cleanSpy2 }

    const chain = new ChainedScenario([
      { scenario: s1, name: "s1" },
      { scenario: s2, name: "s2" },
    ])
    await chain.cleanup()
    expect(cleanSpy1).toHaveBeenCalledTimes(1)
    expect(cleanSpy2).toHaveBeenCalledTimes(1)
  })
})

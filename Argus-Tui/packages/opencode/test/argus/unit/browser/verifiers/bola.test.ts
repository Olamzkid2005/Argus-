import { describe, expect, test, beforeEach } from "bun:test"
import { BOLAVerifier } from "../../../../../src/argus/browser/verifiers/bola"

function makePage(overrides = {}) {
  return {
    content: async () => "<html><body>Dashboard — Welcome user</body></html>",
    goto: async () => {},
    locator: () => ({ innerText: async () => "Dashboard — Welcome user" }),
    url: () => "https://example.com/api/resource/123",
    close: async () => {},
    waitForLoadState: async () => {},
    ...overrides,
  }
}

function mockEngine() {
  let launched = false
  let closed = false
  return {
    launch: async () => { launched = true },
    close: async () => { closed = true },
    createContext: async () => ({
      newPage: async () => makePage(),
      close: async () => {},
    }),
    captureScreenshot: async () => Buffer.from("screenshot"),
    _launched: () => launched,
    _closed: () => closed,
  }
}

describe("BOLAVerifier", () => {
  test("setup calls engine.launch", async () => {
    const engine: any = mockEngine()
    const verifier = new BOLAVerifier(engine, "https://example.com", "/api/resource",
      { username: "userA", password: "pass" },
      { username: "userB", password: "pass" })
    await verifier.setup()
    expect(engine._launched()).toBe(true)
  })

  test("cleanup calls engine.close", async () => {
    const engine: any = mockEngine()
    const verifier = new BOLAVerifier(engine, "https://example.com", "/api/resource",
      { username: "userA", password: "pass" },
      { username: "userB", password: "pass" })
    await verifier.setup()
    await verifier.cleanup()
    expect(engine._closed()).toBe(true)
  })

  test("verify returns passed=true when both users have access", async () => {
    const engine: any = mockEngine()
    const verifier = new BOLAVerifier(engine, "https://example.com", "/api/resource",
      { username: "userA", password: "pass" },
      { username: "userB", password: "pass" })
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    expect(result.passed).toBe(true)
    expect(result.confidence).toBeGreaterThan(0)
    expect(result.summary).toContain("BOLA confirmed")
  })

  test("collectEvidence returns evidence package with logs", async () => {
    const engine: any = mockEngine()
    const verifier = new BOLAVerifier(engine, "https://example.com", "/api/resource",
      { username: "userA", password: "pass" },
      { username: "userB", password: "pass" })
    await verifier.setup()
    await verifier.execute()
    const evidence = await verifier.collectEvidence()
    expect(evidence.logs.length).toBeGreaterThan(0)
    expect(evidence.createdAt).toBeDefined()
  })
})

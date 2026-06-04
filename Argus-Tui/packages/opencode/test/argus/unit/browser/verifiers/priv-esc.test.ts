import { describe, expect, test } from "bun:test"
import { PrivilegeEscalationVerifier } from "../../../../../src/argus/browser/verifiers/priv-esc"

function makePage(overrides: Record<string, unknown> = {}) {
  return {
    content: async () => "<html><body>Dashboard — Welcome</body></html>",
    url: () => "https://example.com/admin",
    goto: async () => ({ status: () => 200 } as any),
    close: async () => {},
    waitForLoadState: async () => {},
    locator: () => ({
      innerText: async () => "Dashboard — Welcome",
      all: async () => [],
      count: async () => 0,
      first: () => ({ isVisible: async () => false, fill: async () => {} }),
      isVisible: async () => false,
      fill: async () => {},
    }),
    screenshot: async () => Buffer.from("screenshot"),
    ...overrides,
  }
}

function mockEngine() {
  let launched = false
  let closed = false
  let contextCreated = false

  return {
    launch: async () => { launched = true },
    close: async () => { closed = true },
    createContext: async () => { contextCreated = true },
    navigate: async () => makePage(),
    captureScreenshot: async () => Buffer.from("priv-esc-shot"),
    _launched: () => launched,
    _closed: () => closed,
    _contextCreated: () => contextCreated,
  }
}

describe("PrivilegeEscalationVerifier", () => {
  test("setup() calls engine.launch()", async () => {
    const engine: any = mockEngine()
    const verifier = new PrivilegeEscalationVerifier(
      engine, "https://example.com", ["/admin", "/config"], { username: "lowuser", password: "lowpass" },
    )
    await verifier.setup()
    expect(engine._launched()).toBe(true)
    expect(engine._contextCreated()).toBe(true)
  })

  test("execute() tests all high-priv endpoints", async () => {
    const engine: any = mockEngine()
    const verifier = new PrivilegeEscalationVerifier(
      engine, "https://example.com", ["/admin", "/config"], { username: "lowuser", password: "lowpass" },
    )
    await verifier.setup()
    await verifier.execute()
    const evidence = await verifier.collectEvidence()
    // Should have requests for both endpoints (+ initial navigate for login)
    const endpointRequests = evidence.requests.filter((r: string) => r.startsWith("GET"))
    expect(endpointRequests.length).toBeGreaterThanOrEqual(2)
  })

  test("verify() returns passed=true when at least one endpoint is accessible", async () => {
    const pageWithAccess = makePage({
      goto: async () => ({ status: () => 200 } as any),
      locator: () => ({
        innerText: async () => "Admin Dashboard — sensitive data",
        all: async () => [],
        count: async () => 0,
        first: () => ({ isVisible: async () => false, fill: async () => {} }),
        isVisible: async () => false,
        fill: async () => {},
      }),
    })
    const engine: any = mockEngine()
    engine.navigate = async () => pageWithAccess

    const verifier = new PrivilegeEscalationVerifier(
      engine, "https://example.com", ["/admin"], { username: "lowuser", password: "lowpass" },
    )
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    expect(result.passed).toBe(true)
  })

  test("verify() returns passed=false when all endpoints return 403", async () => {
    const pageForbidden = makePage({
      goto: async () => ({ status: () => 403 } as any),
      locator: () => ({
        innerText: async () => "403 Forbidden",
        all: async () => [],
        count: async () => 0,
        first: () => ({ isVisible: async () => false, fill: async () => {} }),
        isVisible: async () => false,
        fill: async () => {},
      }),
    })
    const engine: any = mockEngine()
    engine.navigate = async () => pageForbidden

    const verifier = new PrivilegeEscalationVerifier(
      engine, "https://example.com", ["/admin"], { username: "lowuser", password: "lowpass" },
    )
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("enforced")
  })

  test("collectEvidence() returns evidence with logs", async () => {
    const engine: any = mockEngine()
    const verifier = new PrivilegeEscalationVerifier(
      engine, "https://example.com", ["/admin"], { username: "lowuser", password: "lowpass" },
    )
    await verifier.setup()
    await verifier.execute()
    const evidence = await verifier.collectEvidence()
    expect(evidence.logs.length).toBeGreaterThan(0)
    expect(evidence.createdAt).toBeDefined()
  })

  test("cleanup() calls engine.close()", async () => {
    const engine: any = mockEngine()
    const verifier = new PrivilegeEscalationVerifier(
      engine, "https://example.com", ["/admin"], { username: "lowuser", password: "lowpass" },
    )
    await verifier.setup()
    await verifier.cleanup()
    expect(engine._closed()).toBe(true)
  })
})

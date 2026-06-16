import { describe, expect, test } from "bun:test"
import { StoredXSSVerifier } from "../../../../../src/argus/browser/verifiers/xss"

function makePage(overrides: Record<string, unknown> = {}) {
  return {
    content: async () => "<html><body>clean</body></html>",
    url: () => "https://example.com/page",
    goto: async () => ({} as any),
    close: async () => {},
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    locator: () => ({
      all: async () => [],
      first: () => ({ isVisible: async () => false, click: async () => {}, fill: async () => {} }),
      isVisible: async () => false,
      fill: async () => {},
      innerText: async () => "",
      count: async () => 0,
    }),
    evaluate: async () => "",
    screenshot: async () => Buffer.from("screenshot"),
    ...overrides,
  }
}

function makeFieldLocator() {
  return { isVisible: async () => true, fill: async (_v: string) => {} }
}

function makeFormLocator() {
  return {
    locator: () => ({
      all: async () => [makeFieldLocator()],
    }),
  }
}

function mockEngine() {
  let launched = false
  let contextCreated = false
  let closed = false
  let victimContent = "<html><body>clean — no markers</body></html>"

  return {
    launch: async () => { launched = true },
    createContext: async () => { contextCreated = true },
    close: async () => { closed = true },
    navigate: async (url: string) => {
      if (url.includes("victim")) {
        return makePage({
          content: async () => victimContent,
          evaluate: async () => {
            const match = victimContent.match(/<body[^>]*>([\s\S]*)<\/body>/i)
            return match ? match[1] : victimContent
          },
        })
      }
      return makePage({
        locator: (sel: string) => {
          if (sel === "form") return { all: async () => [makeFormLocator()] }
          if (sel === "button[type=submit], input[type=submit]") return { first: () => ({ isVisible: async () => false }) }
          return { all: async () => [] }
        },
      })
    },
    captureScreenshot: async () => Buffer.from("xss-screenshot"),
    _launched: () => launched,
    _contextCreated: () => contextCreated,
    _closed: () => closed,
    _setVictimContent: (c: string) => { victimContent = c },
  }
}

describe("StoredXSSVerifier", () => {
  test("setup() calls engine.launch() and engine.createContext()", async () => {
    const engine: any = mockEngine()
    const verifier = new StoredXSSVerifier(
      engine, "https://example.com/inject", "https://example.com/victim", "<script>alert(1)</script>",
    )
    await verifier.setup()
    expect(engine._launched()).toBe(true)
    expect(engine._contextCreated()).toBe(true)
  })

  test("execute() injects payload into form fields and checks victim view", async () => {
    const engine: any = mockEngine()
    engine._setVictimContent("<html><body>clean</body></html>")
    const verifier = new StoredXSSVerifier(
      engine, "https://example.com/inject", "https://example.com/victim", "<script>alert(1)</script>",
    )
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    // No markers found → passed = false
    expect(result.passed).toBe(false)
  })

  test("verify() returns passed=true when markers found in DOM", async () => {
    const engine: any = mockEngine()
    engine._setVictimContent('<html><body><img src=x onerror=alert(1)></body></html>')
    const verifier = new StoredXSSVerifier(
      engine, "https://example.com/inject", "https://example.com/victim", "<script>alert(1)</script>",
    )
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    expect(result.passed).toBe(true)
    expect(result.confidence).toBeGreaterThan(0)
    expect(result.summary).toContain("confirmed")
  })

  test("verify() returns passed=false when no markers found", async () => {
    const engine: any = mockEngine()
    engine._setVictimContent("<html><body>clean page no xss</body></html>")
    const verifier = new StoredXSSVerifier(
      engine, "https://example.com/inject", "https://example.com/victim", "<script>alert(1)</script>",
    )
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("not detected")
  })

  test("collectEvidence() returns evidence with logs, screenshots, requests, responses", async () => {
    const engine: any = mockEngine()
    const verifier = new StoredXSSVerifier(
      engine, "https://example.com/inject", "https://example.com/victim", "<script>alert(1)</script>",
    )
    await verifier.setup()
    await verifier.execute()
    const evidence = await verifier.collectEvidence()
    expect(evidence.artifacts.length).toBeGreaterThan(0)
    expect(evidence.artifacts.some((a) => a.type === "screenshot")).toBe(true)
    expect(evidence.artifacts.some((a) => a.type === "request")).toBe(true)
    expect(evidence.artifacts.some((a) => a.type === "response")).toBe(true)
    expect(evidence.createdAt).toBeDefined()
  })

  test("cleanup() calls engine.close()", async () => {
    const engine: any = mockEngine()
    const verifier = new StoredXSSVerifier(
      engine, "https://example.com/inject", "https://example.com/victim", "<script>alert(1)</script>",
    )
    await verifier.setup()
    await verifier.cleanup()
    expect(engine._closed()).toBe(true)
  })
})

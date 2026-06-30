import { describe, expect, test, mock } from "bun:test"

// Mock Playwright
mock.module("playwright", () => {
  const mockPage = {
    goto: async (url: string) => ({
      status: () => 200,
      headers: () => ({
        "content-type": "text/html; charset=utf-8",
        "x-frame-options": "DENY",
        "x-content-type-options": "nosniff",
        "strict-transport-security": "max-age=31536000",
        "set-cookie": "session=abc123; HttpOnly; Secure",
        "server": "nginx/1.24.0",
      }),
    } as any),
    content: async () => "<html><body>test page content</body></html>",
    url: () => "https://example.com/page",
    close: async () => {},
    waitForLoadState: async () => {},
    locator: () => ({
      all: async () => [],
      first: () => ({ isVisible: async () => false, click: async () => {}, fill: async () => {} }),
      isVisible: async () => false,
      fill: async () => {},
      innerText: async () => "",
      count: async () => 0,
    }),
  }

  const mockContext = {
    newPage: async () => mockPage,
    close: async () => {},
  }

  const mockBrowser = {
    launch: async () => mockBrowser,
    newContext: async () => mockContext,
    close: async () => {},
  }

  return { chromium: mockBrowser }
})

describe("Browser Observer", () => {
  test("observeUrl returns observation with extracted response headers", async () => {
    const { observeUrl } = await import("../../../../src/argus/browser/observer")
    const { chromium } = await import("playwright")
    const page = await (chromium as any).launch().newContext().newPage()

    const observation = await observeUrl(page, "https://example.com/page")

    expect(observation.url).toBe("https://example.com/page")
    expect(observation.statusCode).toBe(200)
    expect(observation.domSnapshot).toContain("test page content")

    // Verify response headers are extracted
    expect(observation.responseHeaders).toBeDefined()
    expect(Object.keys(observation.responseHeaders).length).toBeGreaterThan(0)
    expect(observation.responseHeaders["content-type"]).toBe("text/html; charset=utf-8")
    expect(observation.responseHeaders["x-frame-options"]).toBe("DENY")
    expect(observation.responseHeaders["x-content-type-options"]).toBe("nosniff")
    expect(observation.responseHeaders["strict-transport-security"]).toContain("max-age")
    expect(observation.responseHeaders["server"]).toBe("nginx/1.24.0")
  })

  test("observeUrl returns observation with timestamp", async () => {
    const { observeUrl } = await import("../../../../src/argus/browser/observer")
    const { chromium } = await import("playwright")
    const page = await (chromium as any).launch().newContext().newPage()

    const observation = await observeUrl(page, "https://example.com/page")

    expect(observation.timestamp).toBeDefined()
    expect(typeof observation.timestamp).toBe("string")
    // Should be a valid ISO date string
    expect(new Date(observation.timestamp).toISOString()).toBe(observation.timestamp)
  })

  test("observeUrl handles missing response gracefully", async () => {
    const { observeUrl } = await import("../../../../src/argus/browser/observer")
    const { chromium } = await import("playwright")
    const page = await (chromium as any).launch().newContext().newPage()

    // Override goto to return null (no response)
    ;(page as any).goto = async () => null

    const observation = await observeUrl(page, "https://example.com/page")
    expect(observation.responseHeaders).toEqual({})
    expect(observation.statusCode).toBe(0)
  })

  test("compareObservations detects no changes for identical snapshots", () => {
    const { compareObservations } = await import("../../../../src/argus/browser/observer")

    const a = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nLine2\nLine3</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }
    const b = { ...a }

    const result = compareObservations(a, b)
    expect(result.changed).toBe(false)
    expect(result.additions).toHaveLength(0)
    expect(result.removals).toHaveLength(0)
  })

  test("compareObservations detects additions in DOM", () => {
    const { compareObservations } = await import("../../../../src/argus/browser/observer")

    const a = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nLine2</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }
    const b = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nLine2\nNewLine</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }

    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions).toContain("NewLine")
    expect(result.removals).toHaveLength(0)
  })

  test("compareObservations detects removals in DOM", () => {
    const { compareObservations } = await import("../../../../src/argus/browser/observer")

    const a = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nLine2\nGoneLine</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }
    const b = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nLine2</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }

    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.removals).toContain("GoneLine")
    expect(result.additions).toHaveLength(0)
  })

  test("compareObservations detects both additions and removals", () => {
    const { compareObservations } = await import("../../../../src/argus/browser/observer")

    const a = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nOldLine</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }
    const b = {
      url: "https://example.com",
      domSnapshot: "<html><body>Line1\nNewLine</body></html>",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }

    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions).toContain("NewLine")
    expect(result.removals).toContain("OldLine")
  })

  test("compareObservations handles empty DOM snapshots", () => {
    const { compareObservations } = await import("../../../../src/argus/browser/observer")

    const a = {
      url: "https://example.com",
      domSnapshot: "",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }
    const b = {
      url: "https://example.com",
      domSnapshot: "",
      responseHeaders: {},
      statusCode: 200,
      timestamp: new Date().toISOString(),
    }

    const result = compareObservations(a, b)
    expect(result.changed).toBe(false)
    expect(result.additions).toHaveLength(0)
    expect(result.removals).toHaveLength(0)
  })

  test("observeUrl header keys are lowercase for consistent access", async () => {
    const { observeUrl } = await import("../../../../src/argus/browser/observer")
    const { chromium } = await import("playwright")
    const page = await (chromium as any).launch().newContext().newPage()

    const observation = await observeUrl(page, "https://example.com/page")

    for (const key of Object.keys(observation.responseHeaders)) {
      expect(key).toBe(key.toLowerCase())
    }
  })
})

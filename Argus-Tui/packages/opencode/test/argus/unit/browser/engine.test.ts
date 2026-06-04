import { describe, expect, test, mock } from "bun:test"

// Mock Playwright to avoid requiring a browser binary
mock.module("playwright", () => {
  const mockPage = {
    goto: async () => ({ status: () => 200 } as any),
    content: async () => "<html><body>test</body></html>",
    url: () => "https://example.com",
    screenshot: async () => Buffer.from("screenshot-data"),
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

describe("PlaywrightEngine", () => {
  test("constructor creates instance", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    expect(engine).toBeDefined()
  })

  test("launch() and close() lifecycle", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    // After launch, browser should be set
    expect((engine as any).browser).toBeDefined()
    await engine.close()
    expect((engine as any).browser).toBeNull()
    expect((engine as any).context).toBeNull()
  })

  test("createContext() requires launch first", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await expect(engine.createContext()).rejects.toThrow("Browser not launched")
  })

  test("createContext() creates context after launch", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    const ctx = await engine.createContext()
    expect(ctx).toBeDefined()
    await engine.close()
  })

  test("captureScreenshot() returns Buffer", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    const ctx = await engine.createContext()
    const page = await ctx.newPage()
    const buffer = await engine.captureScreenshot(page)
    expect(buffer).toBeInstanceOf(Buffer)
    expect(buffer.length).toBeGreaterThan(0)
    await engine.close()
  })
})

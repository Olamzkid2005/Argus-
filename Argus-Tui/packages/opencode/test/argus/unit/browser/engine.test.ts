import { describe, expect, test, mock, beforeEach, afterEach } from "bun:test"
import { tmpdir } from "os"
import { join } from "path"
import { existsSync, mkdirSync, rmSync, readdirSync } from "fs"

// Track whether context was created with recordHar to verify HAR capture
let lastCreateContextOptions: Record<string, unknown> | null = null

// Mock Playwright to avoid requiring a browser binary
mock.module("playwright", () => {
  const mockPage = {
    goto: async () => ({ status: () => 200 } as any),
    content: async () => "<html><body>test</body></html>",
    url: () => "https://example.com",
    screenshot: async () => Buffer.from("screenshot-data"),
    evaluate: async (fn: any, ...args: any[]) => {
      if (typeof fn === "function") return fn(...args)
      return null
    },
    textContent: async () => "Welcome! Dashboard content here.",
    close: async () => {},
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    waitForSelector: async () => {},
    locator: () => ({
      all: async () => [],
      first: () => ({
        isVisible: async () => false,
        click: async () => {},
        fill: async () => {},
        press: async () => {},
      }),
      isVisible: async () => false,
      fill: async () => {},
      press: async () => {},
      innerText: async () => "",
      count: async () => 0,
    }),
    $: async () => null,
  }

  const mockContext = {
    newPage: async () => mockPage,
    close: async () => {},
    addCookies: async () => {},
  }

  const mockBrowser = {
    launch: async (opts?: any) => {
      // Track launch args for stealth verification
      ;(mockBrowser as any)._lastLaunchArgs = opts?.args ?? []
      return mockBrowser
    },
    newContext: async (opts?: any) => {
      lastCreateContextOptions = opts ?? null
      return mockContext
    },
    close: async () => {},
    _lastLaunchArgs: [] as string[],
  }

  return { chromium: mockBrowser }
})

describe("PlaywrightEngine", () => {
  let tempHarDir: string

  beforeEach(() => {
    lastCreateContextOptions = null
    tempHarDir = join(tmpdir(), `argus-test-har-${Date.now()}`)
  })

  afterEach(() => {
    // Clean up temp HAR directory
    if (existsSync(tempHarDir)) {
      rmSync(tempHarDir, { recursive: true, force: true })
    }
  })

  test("constructor creates instance", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    expect(engine).toBeDefined()
  })

  test("launch() and close() lifecycle", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    expect((engine as any).browser).toBeDefined()
    await engine.close()
    expect((engine as any).browser).toBeNull()
    expect((engine as any).context).toBeNull()
  })

  test("launch() uses stealth arguments to avoid bot detection", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    const chromium = (await import("playwright")).chromium as any
    const launchArgs = chromium._lastLaunchArgs
    expect(launchArgs).toContain("--disable-blink-features=AutomationControlled")
    expect(launchArgs).toContain("--no-sandbox")
    expect(launchArgs).toContain("--disable-gpu")
    expect(launchArgs).toContain("--disable-dev-shm-usage")
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

  test("createContext() sets stealth-friendly defaults when no options provided", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    await engine.createContext()
    
    expect(lastCreateContextOptions).not.toBeNull()
    expect(lastCreateContextOptions!.viewport).toEqual({ width: 1280, height: 720 })
    expect(lastCreateContextOptions!.locale).toBe("en-US")
    expect(lastCreateContextOptions!.timezoneId).toBe("America/New_York")
    expect(lastCreateContextOptions!.geolocation).toEqual({ latitude: 40.7128, longitude: -74.006 })
    expect(lastCreateContextOptions!.colorScheme).toBe("light")
    expect(lastCreateContextOptions!.reducedMotion).toBe("no-preference")
    
    // User-Agent should be a realistic modern Chrome string
    const ua = lastCreateContextOptions!.userAgent as string
    expect(ua).toContain("Mozilla/5.0")
    expect(ua).toContain("Chrome/125")
    expect(ua).not.toContain("HeadlessChrome")
    
    await engine.close()
  })

  test("createContext() accepts custom viewport, userAgent, locale, timezone", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    
    await engine.createContext({
      viewport: { width: 1920, height: 1080 },
      userAgent: "Custom-UA/1.0",
      locale: "fr-FR",
      timezoneId: "Europe/Paris",
    })
    
    expect(lastCreateContextOptions!.viewport).toEqual({ width: 1920, height: 1080 })
    expect(lastCreateContextOptions!.userAgent).toBe("Custom-UA/1.0")
    expect(lastCreateContextOptions!.locale).toBe("fr-FR")
    expect(lastCreateContextOptions!.timezoneId).toBe("Europe/Paris")
    
    await engine.close()
  })

  test("createContext() enables HAR capture when harDir is provided", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    
    await engine.createContext({ harDir: tempHarDir })
    
    // HAR should be enabled with embed content
    expect(lastCreateContextOptions!.recordHar).toBeDefined()
    const harConfig = lastCreateContextOptions!.recordHar as any
    expect(harConfig.path).toContain(tempHarDir)
    expect(harConfig.path).toContain("session-")
    expect(harConfig.path).toEndWith(".har")
    expect(harConfig.content).toBe("embed")
    
    await engine.close()
  })

  test("createContext() creates HAR directory when it doesn't exist", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    
    // harDir doesn't exist yet
    expect(existsSync(tempHarDir)).toBe(false)
    
    await engine.createContext({ harDir: tempHarDir })
    
    // Directory should be created
    expect(existsSync(tempHarDir)).toBe(true)
    
    await engine.close()
  })

  test("getHarPath() returns null when HAR not enabled", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    await engine.createContext()
    
    expect(engine.getHarPath()).toBeNull()
    
    await engine.close()
  })

  test("getHarPath() returns HAR path when HAR is enabled", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    await engine.createContext({ harDir: tempHarDir })
    
    const harPath = engine.getHarPath()
    expect(harPath).not.toBeNull()
    expect(harPath).toContain(tempHarDir)
    expect(harPath).toEndWith(".har")
    
    await engine.close()
  })

  test("observe() returns observation with correct shape", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    const ctx = await engine.createContext()
    const page = await ctx.newPage()
    
    const observation = await engine.observe(page)
    
    expect(observation).toHaveProperty("url")
    expect(observation).toHaveProperty("domSnapshot")
    expect(observation).toHaveProperty("responseHeaders")
    expect(observation).toHaveProperty("statusCode")
    expect(observation).toHaveProperty("timestamp")
    expect(observation.url).toBe("https://example.com")
    expect(observation.statusCode).toBe(200)
    
    await engine.close()
  })

  test("observe() accepts custom statusCode", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    const ctx = await engine.createContext()
    const page = await ctx.newPage()
    
    const observation = await engine.observe(page, 403)
    expect(observation.statusCode).toBe(403)
    
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

  test("navigate() throws when no context exists", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await expect(engine.navigate("https://example.com")).rejects.toThrow("No browser context")
  })

  test("close() is safe to call multiple times", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.close()  // No error when not launched
    await engine.close()  // Second close is also safe
  })

  test("full lifecycle: launch → createContext with HAR → navigate → observe → close", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    
    await engine.launch()    await engine.createContext({ harDir: tempHarDir })

    // HAR path should be set
    expect(engine.getHarPath()).toContain(tempHarDir)
    
    await engine.close()
    expect((engine as any).browser).toBeNull()
    expect((engine as any).context).toBeNull()
  })
})

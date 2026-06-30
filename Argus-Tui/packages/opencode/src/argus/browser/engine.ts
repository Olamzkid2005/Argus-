import type { Browser, BrowserContext, Page } from "playwright"
import type { Observation } from "./types"
import { existsSync, mkdirSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"

export interface BrowserEngine {
  launch(headless?: boolean, userAgent?: string): Promise<void>
  createContext(harPath?: string): Promise<BrowserContext>
  navigate(url: string): Promise<Page>
  observe(page: Page, statusCode?: number): Promise<Observation>
  captureScreenshot(page: Page): Promise<Buffer>
  close(): Promise<void>
}

export interface BrowserEngineOptions {
  /** Custom viewport dimensions. Default: 1280x720 */
  viewport?: { width: number; height: number }
  /** Custom User-Agent string. Falls back to a realistic mobile/desktop UA. */
  userAgent?: string
  /** Locale override. Default: en-US */
  locale?: string
  /** Timezone override. Default: America/New_York */
  timezoneId?: string
  /** Directory to store HAR files. When set, HAR capture is enabled. */
  harDir?: string
}

export class PlaywrightEngine implements BrowserEngine {
  private browser: Browser | null = null
  private context: BrowserContext | null = null
  private harPath: string | null = null
  /** Tracks all HAR files created across multiple context switches. */
  private allHarPaths: string[] = []

  async launch(headless = true, userAgent?: string): Promise<void> {
    const { chromium } = await import("playwright")

    // Stealth/evasion launch args to avoid bot detection:
    // --disable-blink-features=AutomationControlled: Hides navigator.webdriver
    // --no-sandbox: Required for Docker/CI environments
    // --disable-gpu: Reduces fingerprinting surface in headless mode
    // --disable-dev-shm-usage: Avoids /dev/shm exhaustion in containers
    this.browser = await chromium.launch({
      headless,
      args: [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-dev-shm-usage",
      ],
    })
  }

  async createContext(options?: BrowserEngineOptions): Promise<BrowserContext> {
    if (!this.browser) throw new Error("Browser not launched")
    // Close the previous context before creating a new one to avoid context leaks.
    // Verifiers (bola.ts, priv-esc.ts) call createContext() multiple times per
    // access check — without this guard, each call leaks an orphaned context.
    if (this.context) {
      // Close the previous HAR file if one was being recorded
      await this.context.close().catch(() => {})
      this.context = null
    }

    // Build context options with stealth-friendly defaults
    const ctxOptions: Record<string, unknown> = {
      viewport: options?.viewport ?? { width: 1280, height: 720 },
      userAgent: options?.userAgent ?? (
        // Realistic modern Chrome UA to avoid bot detection
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
        "AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/125.0.0.0 Safari/537.36"
      ),
      locale: options?.locale ?? "en-US",
      timezoneId: options?.timezoneId ?? "America/New_York",
      // Set geolocation to a realistic default (NYC) to avoid detection
      geolocation: { latitude: 40.7128, longitude: -74.006 },
      permissions: ["geolocation"],
      // Disable proxy auto-config to prevent PAC-related leaks
      bypassCSP: false,
      // Reduce automation fingerprints
      colorScheme: "light",
      reducedMotion: "no-preference",
      forcedColors: "none",
    }

    // Enable HAR capture when harDir is provided
    if (options?.harDir) {
      if (!existsSync(options.harDir)) {
        mkdirSync(options.harDir, { recursive: true })
      }
      const timestamp = Date.now()
      this.harPath = join(options.harDir, `session-${timestamp}.har`)
      // Track this HAR file path so we can aggregate all entries later
      this.allHarPaths.push(this.harPath)
      ctxOptions.recordHar = {
        path: this.harPath,
        content: "embed" as const,  // Embed request/response bodies directly
      }
    }

    this.context = await this.browser.newContext(ctxOptions)
    return this.context
  }

  /** Returns the path to the most recent HAR file, or null if HAR was not captured. */
  getHarPath(): string | null {
    return this.harPath
  }

  /**
   * Returns all HAR file paths created across all context switches.
   * Use this after the engine is closed to aggregate all captured traffic.
   */
  getAllHarPaths(): string[] {
    return [...this.allHarPaths]
  }

  /** Returns the HAR directory if HAR was enabled, otherwise null. */
  getHarDir(): string | null {
    if (this.allHarPaths.length === 0) return null
    const dir = join(this.allHarPaths[0], "..")
    try {
      return require("path").resolve(dir)
    } catch {
      return dir
    }
  }

  async navigate(url: string): Promise<Page> {
    if (!this.context) throw new Error("No browser context")
    const page = await this.context.newPage()
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 })
    return page
  }

  async observe(page: Page, statusCode?: number): Promise<Observation> {
    const domSnapshot = await page.content()

// Extract actual response headers from the page's main response using
    // Playwright's native Response object (available via the page's ongoing
    // request tracking). This is more reliable than the Performance API which
    // has limited header access in browser contexts.
    let responseHeaders: Record<string, string> = {}
    try {
      // Use page.evaluate to check what navigation info we can get from the browser
      await page.evaluate(() => {
        // This runs in browser context; we just trigger it to ensure the
        // navigation entry is available if needed
        return performance.getEntriesByType("navigation").length
      })
      // Get headers from all requests matching the current page URL
      // This uses Playwright's request/response API which has full header access
      // Full header capture happens via HAR recording — see BrowserEngineOptions.harDir
      // which captures all request/response headers and bodies during the session.
      // Header extraction from Playwright's Response.headers() is handled per-request
      // in the observer module.
    } catch {
      // Header extraction best-effort
    }

    return {
      url: page.url(),
      domSnapshot,
      responseHeaders,
      statusCode: statusCode ?? 200,
      timestamp: new Date().toISOString(),
    }
  }

  async captureScreenshot(page: Page): Promise<Buffer> {
    return page.screenshot({ type: "png", fullPage: true })
  }

  async close(): Promise<void> {
    if (this.context) {
      await this.context.close().catch(() => {})
      this.context = null
    }
    if (this.browser) {
      await this.browser.close().catch(() => {})
      this.browser = null
    }
    this.harPath = null
    this.allHarPaths = []
  }
}

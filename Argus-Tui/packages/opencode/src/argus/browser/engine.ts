import type { Browser, BrowserContext, Page } from "playwright"
import type { Observation } from "./types"
import { existsSync, mkdirSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"

// ── Stealth: Realistic viewport size pool ──
// Common desktop viewport sizes collected from real user analytics.
// Randomly selected per context to avoid a fixed viewport fingerprint.
const VIEWPORT_POOL: Array<{ width: number; height: number }> = [
  { width: 1920, height: 1080 },  // Full HD (most common)
  { width: 1366, height: 768 },   // Common laptop
  { width: 1536, height: 864 },   // Common desktop
  { width: 1440, height: 900 },   // MacBook Pro
  { width: 1280, height: 720 },   // HD
  { width: 1600, height: 900 },   // Common external monitor
  { width: 1680, height: 1050 },  // Older desktop
  { width: 1280, height: 800 },   // Common laptop
  { width: 1920, height: 1200 },  // High-res laptop
  { width: 2560, height: 1440 },  // QHD
]

/** Pick a random realistic viewport from the pool. */
function randomViewport(): { width: number; height: number } {
  const idx = Math.floor(Math.random() * VIEWPORT_POOL.length)
  return VIEWPORT_POOL[idx]
}

/** Small random jitter (±2px) on viewport to avoid exact fingerprint matches. */
function jitterViewport(vp: { width: number; height: number }): { width: number; height: number } {
  const jitter = (n: number) => n + Math.floor(Math.random() * 5) - 2  // ±2px
  return { width: jitter(vp.width), height: jitter(vp.height) }
}

export interface BrowserEngine {
  launch(headless?: boolean, userAgent?: string): Promise<void>
  createContext(options?: BrowserEngineOptions): Promise<BrowserContext>
  navigate(url: string): Promise<Page>
  observe(page: Page, statusCode?: number): Promise<Observation>
  captureScreenshot(page: Page): Promise<Buffer>
  close(): Promise<void>
}

export interface BrowserEngineOptions {
  /** Custom viewport dimensions. Default: randomly selected from realistic pool */
  viewport?: { width: number; height: number }
  /** Custom User-Agent string. Falls back to a realistic mobile/desktop UA. */
  userAgent?: string
  /** Locale override. Default: en-US */
  locale?: string
  /** Timezone override. Default: America/New_York */
  timezoneId?: string
  /** Directory to store HAR files. When set, HAR capture is enabled. */
  harDir?: string
  /** Disable random viewport jitter. Default: false */
  disableViewportJitter?: boolean
  /** Disable mouse movement simulation. Default: false */
  disableMouseSimulation?: boolean
  /** Disable WebGL/Canvas fingerprint spoofing. Default: false */
  disableFingerprintSpoofing?: boolean
}

export class PlaywrightEngine implements BrowserEngine {
  private browser: Browser | null = null
  private context: BrowserContext | null = null
  private harPath: string | null = null
  /** Tracks all HAR files created across multiple context switches. */
  private allHarPaths: string[] = []
  /** Stores response headers for each page's main navigation. */
  private navigationResponseHeaders = new WeakMap<Page, Record<string, string>>()
  /** Stores stealth options from the last createContext() call. */
  private _stealthOptions: { disableMouseSimulation?: boolean } = {}

  async launch(headless = true, userAgent?: string): Promise<void> {
    const { chromium } = await import("playwright")

    // Gap 7.5: Comprehensive stealth/evasion to avoid WAF and bot detection:
    // --disable-blink-features=AutomationControlled: Hides navigator.webdriver
    // --no-sandbox: Required for Docker/CI environments
    // --disable-gpu: Reduces fingerprinting surface in headless mode
    // --disable-dev-shm-usage: Avoids /dev/shm exhaustion in containers
    // --disable-client-side-phishing-detection: Reduces detection surface
    // --disable-component-update: Prevents update checks that reveal automation
    // --disable-background-networking: Reduces unexpected network requests
    // --disable-sync: Prevents sync traffic that can identify browser as automated
    // --disable-features=IsolateOrigins,site-per-process: Reduces isolation fingerprints
    this.browser = await chromium.launch({
      headless,
      args: [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-client-side-phishing-detection",
        "--disable-component-update",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-features=IsolateOrigins,site-per-process",
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

    // ── Stealth: Store options for use in other methods (e.g. navigate) ──
    this._stealthOptions = {
      disableMouseSimulation: options?.disableMouseSimulation ?? false,
    }

    // ── Stealth: Random viewport from pool with slight jitter ──
    const baseViewport = options?.viewport ?? randomViewport()
    const viewport = options?.disableViewportJitter ? baseViewport : jitterViewport(baseViewport)

    // Build context options with stealth-friendly defaults
    const ctxOptions: Record<string, unknown> = {
      viewport,
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

    // ── Stealth: Apply comprehensive patches to remove automation fingerprints ──
    // Removes navigator.webdriver property, overrides navigator.plugins length,
    // patches Chrome runtime objects, spoofs WebGL vendor/renderer strings,
    // and adds canvas fingerprint randomization.
    // Skip entirely if the caller explicitly disabled fingerprint spoofing.
    if (!options?.disableFingerprintSpoofing) {
      await this.context.addInitScript(() => {
        // 1. Remove the webdriver property that Playwright sets
        Object.defineProperty(navigator, "webdriver", {
          get: () => undefined,
        })

        // 2. Override navigator.plugins to report a realistic length (typically 5 in Chrome)
        Object.defineProperty(navigator, "plugins", {
          get: () => [1, 2, 3, 4, 5] as unknown as PluginArray,
        })

        // 3. Override navigator.languages to match the locale setting
        Object.defineProperty(navigator, "languages", {
          get: () => ["en-US", "en"],
        })

        // 4. Override navigator.hardwareConcurrency to report a realistic CPU core count
        //    (Playwright's default of 1 or the actual high core count is a fingerprint)
        Object.defineProperty(navigator, "hardwareConcurrency", {
          get: () => Math.min(16, navigator.hardwareConcurrency || 4),
          configurable: true,
        })

        // 5. Remove the chrome.runtime object that is only present in extensions
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const win = window as any
        if (win.chrome) {
          win.chrome.runtime = undefined
        }

        // 6. Override navigator.deviceMemory to report a realistic RAM value (4-8 GB)
        //    This prevents sites from detecting unusual memory configurations
        const memoryValues = [4, 8]
        Object.defineProperty(navigator, "deviceMemory", {
          get: () => memoryValues[Math.floor(Math.random() * memoryValues.length)],
          configurable: true,
        })

        // 7. WebGL vendor/renderer spoofing — override WebGLRenderingContext
        //    getParameter to return realistic GPU strings instead of the default
        //    "SwiftShader" or "Google" renderer that Playwright exposes.
        const getParameterProxyHandler = {
          apply: function (target: any, thisArg: any, args: any[]) {
            const param = args[0]
            // WebGLRenderingContext.UNMASKED_VENDOR_WEBGL = 37445
            // WebGLRenderingContext.UNMASKED_RENDERER_WEBGL = 37446
            if (param === 37445) {
              return "Intel Inc."
            }
            if (param === 37446) {
              // Return a realistic Intel GPU renderer string
              const renderers = [
                "Intel(R) UHD Graphics 620",
                "Intel(R) Iris(R) Xe Graphics",
                "Intel(R) UHD Graphics 630",
                "Intel(R) Iris Plus Graphics 655",
              ]
              return renderers[Math.floor(Math.random() * renderers.length)]
            }
            return Reflect.apply(target, thisArg, args)
          },
        }

        // Try to patch the WebGL context's getParameter
        try {
          const canvas = document.createElement("canvas")
          const gl = canvas.getContext("webgl") as any
          if (gl && gl.getParameter) {
            gl.getParameter = new Proxy(gl.getParameter, getParameterProxyHandler)
          }
          // Also patch the experimental-webgl context
          const gl2 = canvas.getContext("webgl2") as any
          if (gl2 && gl2.getParameter) {
            gl2.getParameter = new Proxy(gl2.getParameter, getParameterProxyHandler)
          }
        } catch {
          // WebGL patching is best-effort
        }

        // 8. Canvas fingerprint randomization: add subtle noise to canvas
        //    toDataURL and toBlob results. This prevents canvas fingerprinting
        //    from uniquely identifying the browser instance.
        try {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const originalToDataURL = (HTMLCanvasElement.prototype as any).toDataURL
          if (originalToDataURL) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            ;(HTMLCanvasElement.prototype as any).toDataURL = function (...args: any[]) {
              const dataUrl = originalToDataURL.apply(this, args)
              // Only add noise ~20% of the time to avoid suspicious patterns
              if (Math.random() < 0.2 && dataUrl.startsWith("data:image/png")) {
                // Slightly modify one pixel of the PNG base64 data near the end
                // to produce a unique-but-subtle fingerprint mutation
                const idx = Math.floor(dataUrl.length * 0.95) + Math.floor(Math.random() * 16)
                if (idx < dataUrl.length) {
                  const char = dataUrl[idx]
                  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
                  const altChar = alphabet[Math.floor(Math.random() * alphabet.length)]
                  if (altChar !== char) {
                    return dataUrl.substring(0, idx) + altChar + dataUrl.substring(idx + 1)
                  }
                }
              }
              return dataUrl
            }
          }
        } catch {
          // Canvas noise is best-effort
        }
      })
    }

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

  /**
   * Simulate human-like mouse movement using bezier curves.
   * Moves the mouse along a curved path from a random starting position
   * to a target position, with realistic acceleration/deceleration.
   *
   * @param page - The page to move the mouse on.
   * @param targetX - Target X coordinate.
   * @param targetY - Target Y coordinate.
   * @param steps - Number of movement steps (default 10-20 random).
   */
  async simulateMouseMove(
    page: Page,
    targetX: number,
    targetY: number,
    steps?: number,
  ): Promise<void> {
    const numSteps = steps ?? 10 + Math.floor(Math.random() * 10)  // 10-19 steps

    // Pick a random starting position (somewhere around center-left of viewport)
    const startX = 50 + Math.random() * 200
    const startY = 100 + Math.random() * 400

    // Generate two random control points for the bezier curve to create
    // realistic curved mouse paths (humans don't move in straight lines)
    const cp1x = startX + (targetX - startX) * 0.3 + (Math.random() - 0.5) * 100
    const cp1y = startY + (targetY - startY) * 0.2 + (Math.random() - 0.5) * 80
    const cp2x = startX + (targetX - startX) * 0.7 + (Math.random() - 0.5) * 100
    const cp2y = startY + (targetY - startY) * 0.8 + (Math.random() - 0.5) * 80

    // Move in steps along the cubic bezier curve
    for (let i = 0; i < numSteps; i++) {
      const t = (i + 1) / numSteps
      // Cubic bezier: B(t) = (1-t)³·P0 + 3(1-t)²·t·P1 + 3(1-t)·t²·P2 + t³·P3
      const x =
        (1 - t) ** 3 * startX +
        3 * (1 - t) ** 2 * t * cp1x +
        3 * (1 - t) * t ** 2 * cp2x +
        t ** 3 * targetX
      const y =
        (1 - t) ** 3 * startY +
        3 * (1 - t) ** 2 * t * cp1y +
        3 * (1 - t) * t ** 2 * cp2y +
        t ** 3 * targetY

      await page.mouse.move(x, y)

      // Variable delay between moves (10-40ms) to simulate varying human speed
      await page.waitForTimeout(10 + Math.random() * 30)
    }
  }

  async navigate(url: string): Promise<Page> {
    if (!this.context) throw new Error("No browser context")
    const page: Page = await this.context.newPage()
    const response = await page.goto(url, { waitUntil: "networkidle", timeout: 30000 })
    // Store the response headers for this page so observe() can access them.
    // This is the only reliable way to get response headers in Playwright —
    // the Performance API in the browser context does not expose headers.
    if (response) {
      this.navigationResponseHeaders.set(page, response.headers())
    }

    // ── Stealth: After navigation, simulate a brief human-like mouse movement ──
    try {
      // Move to a position slightly in from the current scroll position.
      // Skip if the caller explicitly disabled mouse simulation.
      if (!this._stealthOptions.disableMouseSimulation) {
        const vp = page.viewportSize()
        if (vp) {
          await this.simulateMouseMove(
            page,
            Math.floor(vp.width * 0.3 + Math.random() * vp.width * 0.4),
            Math.floor(vp.height * 0.3 + Math.random() * vp.height * 0.4),
            5 + Math.floor(Math.random() * 8),
          )
        }
      }
    } catch {
      // Mouse simulation is best-effort
    }

    return page
  }

  async observe(page: Page, statusCode?: number): Promise<Observation> {
    const domSnapshot = await page.content()

// Extract actual response headers from the page's main response using
    // Playwright's native Response object (available via the page's ongoing
    // request tracking). This is more reliable than the Performance API which
    // has limited header access in browser contexts.
    // Extract response headers from the page's main navigation.
    // We stored these in navigate() using Playwright's Response.headers() API,
    // which has full access to all HTTP response headers. Fall back to empty
    // object if the page wasn't navigated through this engine.
    let responseHeaders: Record<string, string> = {}
    try {
      const storedHeaders = this.navigationResponseHeaders.get(page)
      if (storedHeaders) {
        responseHeaders = storedHeaders
      }
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

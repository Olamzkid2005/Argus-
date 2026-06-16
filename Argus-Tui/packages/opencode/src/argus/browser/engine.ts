import type { Browser, BrowserContext, Page } from "playwright"
import type { Observation } from "./types"

export interface BrowserEngine {
  launch(headless?: boolean): Promise<void>
  createContext(): Promise<BrowserContext>
  navigate(url: string): Promise<Page>
  observe(page: Page, statusCode?: number): Promise<Observation>
  captureScreenshot(page: Page): Promise<Buffer>
  close(): Promise<void>
}

export class PlaywrightEngine implements BrowserEngine {
  private browser: Browser | null = null
  private context: BrowserContext | null = null

  async launch(headless = true): Promise<void> {
    const { chromium } = await import("playwright")
    this.browser = await chromium.launch({ headless })
  }

  async createContext(): Promise<BrowserContext> {
    if (!this.browser) throw new Error("Browser not launched")
    this.context = await this.browser.newContext()
    return this.context
  }

  async navigate(url: string): Promise<Page> {
    if (!this.context) throw new Error("No browser context")
    const page = await this.context.newPage()
    await page.goto(url, { waitUntil: "networkidle" })
    return page
  }

  async observe(page: Page, statusCode?: number): Promise<Observation> {
    const domSnapshot = await page.content()

    return {
      url: page.url(),
      domSnapshot,
      responseHeaders: {},
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
  }
}

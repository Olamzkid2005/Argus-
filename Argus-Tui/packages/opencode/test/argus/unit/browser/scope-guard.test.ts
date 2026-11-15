/**
 * Browser scope guard: parsed-origin authorization for Playwright requests.
 *
 * Stage 3.2 item 2. A browser context carries the run's session (cookies,
 * injected `Authorization` headers), so every request it makes has to be
 * authorized: the navigation itself, subresources, iframes, popups, XHR and
 * redirect hops. Out-of-scope requests are aborted before the browser attaches
 * session data to them.
 */

import { describe, expect, test, mock, beforeEach } from "bun:test"

interface RoutedRequest {
  url: string
  navigation?: boolean
  headers?: Record<string, string>
}

const state = {
  goto: [] as string[],
  aborted: [] as string[],
  continued: [] as string[],
  routeHandler: null as ((route: any) => Promise<void>) | null,
}

function makeRoute(request: RoutedRequest) {
  return {
    request: () => ({
      url: () => request.url,
      isNavigationRequest: () => request.navigation ?? false,
      headers: () => request.headers ?? {},
    }),
    continue: async () => {
      state.continued.push(request.url)
    },
    abort: async (code?: string) => {
      state.aborted.push(`${request.url}|${code ?? ""}`)
    },
  }
}

mock.module("playwright", () => {
  const mockPage = {
    goto: async (url: string) => {
      state.goto.push(url)
      return { status: () => 200, headers: () => ({}) }
    },
    content: async () => "<html></html>",
    url: () => "https://example.com",
    screenshot: async () => Buffer.from("screenshot"),
    evaluate: async () => null,
    waitForTimeout: async () => {},
    viewportSize: () => ({ width: 1280, height: 800 }),
    mouse: { move: async () => {} },
  }

  const mockContext = {
    newPage: async () => mockPage,
    close: async () => {},
    addCookies: async () => {},
    setExtraHTTPHeaders: async () => {},
    addInitScript: async () => {},
    route: async (_pattern: string, handler: (route: any) => Promise<void>) => {
      state.routeHandler = handler
    },
  }

  const mockBrowser = {
    launch: async () => mockBrowser,
    newContext: async () => mockContext,
    close: async () => {},
  }

  return { chromium: mockBrowser }
})

beforeEach(() => {
  state.goto = []
  state.aborted = []
  state.continued = []
  state.routeHandler = null
})

describe("parseOrigin", () => {
  test("normalizes scheme defaults and host case", async () => {
    const { parseOrigin } = await import("../../../../src/argus/browser/scope-guard")
    expect(parseOrigin("https://EXAMPLE.com./path")).toEqual({
      scheme: "https",
      host: "example.com",
      port: 443,
    })
    expect(parseOrigin("http://example.com").port).toBe(80)
    expect(parseOrigin("https://example.com:8443/x").port).toBe(8443)
  })

  test("rejects anything that is not an absolute http(s) URL", async () => {
    const { parseOrigin } = await import("../../../../src/argus/browser/scope-guard")
    for (const bad of [
      "",
      "   ",
      "example.com/path",
      "not a url",
      "//example.com/x",
      "javascript:alert(1)",
      "file:///etc/passwd",
      "ftp://example.com/",
      "https://user:pass@example.com/",
      "https://example.com:99999/",
    ]) {
      expect(() => parseOrigin(bad)).toThrow()
    }
  })
})

describe("BrowserScope", () => {
  test("an origin entry does not authorize another scheme, port or sibling origin", async () => {
    const { BrowserScope } = await import("../../../../src/argus/browser/scope-guard")
    const scope = new BrowserScope(["https://example.com"])

    expect(scope.authorize("https://example.com/dashboard").authorized).toBe(true)
    expect(scope.authorize("http://example.com/dashboard").authorized).toBe(false)
    expect(scope.authorize("https://example.com:8443/dashboard").authorized).toBe(false)
    expect(scope.authorize("https://api.example.com/dashboard").authorized).toBe(false)
    expect(scope.authorize("https://example.com.evil.test/").authorized).toBe(false)
  })

  test("a host/port entry covers any scheme and path but not another port", async () => {
    const { BrowserScope } = await import("../../../../src/argus/browser/scope-guard")
    const scope = new BrowserScope(["example.com:8080"])

    expect(scope.authorize("http://example.com:8080/any/path").authorized).toBe(true)
    expect(scope.authorize("https://example.com:8080/").authorized).toBe(true)
    expect(scope.authorize("http://example.com:9090/any/path").authorized).toBe(false)
  })

  test("a wildcard entry matches exactly one label", async () => {
    const { BrowserScope } = await import("../../../../src/argus/browser/scope-guard")
    const scope = new BrowserScope(["*.example.com"])

    expect(scope.authorize("https://api.example.com/v1").authorized).toBe(true)
    expect(scope.authorize("https://deep.api.example.com/v1").authorized).toBe(false)
  })

  test("with no entries nothing is authorized until the run's origin is pinned", async () => {
    const { BrowserScope } = await import("../../../../src/argus/browser/scope-guard")
    const scope = new BrowserScope()

    expect(scope.authorize("https://example.com/").authorized).toBe(false)

    scope.pinOrigin("https://example.com/login")

    expect(scope.authorize("https://example.com/dashboard").authorized).toBe(true)
    expect(scope.authorize("https://example.com:8443/").authorized).toBe(false)
    expect(scope.authorize("https://evil.test/").authorized).toBe(false)
  })

  test("an unusable entry is recorded, not silently ignored", async () => {
    const { BrowserScope } = await import("../../../../src/argus/browser/scope-guard")
    const scope = new BrowserScope(["not a rule", "https://example.com"])

    expect(scope.rejectedEntries).toEqual(["not a rule"])
    expect(scope.entries).toEqual(["https://example.com"])
  })
})

describe("PlaywrightEngine scope enforcement", () => {
  test("navigate() refuses an out-of-scope URL without issuing a request", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const { BrowserScopeError } = await import("../../../../src/argus/browser/scope-guard")
    const engine = new PlaywrightEngine({ allowedTargets: ["https://example.com"] })
    await engine.launch()
    await engine.createContext()

    await expect(engine.navigate("https://evil.test/steal")).rejects.toThrow(BrowserScopeError)

    expect(state.goto).toEqual([])
    expect(engine.scopeViolations.some((v) => v.url === "https://evil.test/steal")).toBe(true)
    await engine.close()
  })

  test("navigate() allows the engagement origin", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine({ allowedTargets: ["https://example.com"] })
    await engine.launch()
    await engine.createContext()

    await engine.navigate("https://example.com/dashboard")

    expect(state.goto).toEqual(["https://example.com/dashboard"])
    await engine.close()
  })

  test("with no configured entries the first navigation pins the run's origin", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine()
    await engine.launch()
    await engine.createContext()

    await engine.navigate("https://example.com/login")
    await expect(engine.navigate("https://api.example.com/v1")).rejects.toThrow()
    expect(state.goto).toEqual(["https://example.com/login"])
    await engine.close()
  })

  test("the context guard aborts out-of-scope subresources before session headers are sent", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine({ allowedTargets: ["https://example.com"] })
    await engine.launch()
    await engine.createContext()
    expect(state.routeHandler).not.toBeNull()

    // What a session-bearing page request looks like: the request would carry
    // the run's cookie and bearer header. It must never be continued.
    await state.routeHandler!(
      makeRoute({
        url: "https://cdn.evil.test/steal.js",
        headers: { cookie: "session=abc", authorization: "Bearer secret" },
      }),
    )

    expect(state.aborted).toEqual(["https://cdn.evil.test/steal.js|blockedbyclient"])
    expect(state.continued).toEqual([])
    expect(
      engine.scopeViolations.some(
        (v) => v.url === "https://cdn.evil.test/steal.js" && !v.navigation,
      ),
    ).toBe(true)
    await engine.close()
  })

  test("the guard continues in-scope requests and local data: URLs", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine({ allowedTargets: ["https://example.com"] })
    await engine.launch()
    await engine.createContext()

    await state.routeHandler!(makeRoute({ url: "https://example.com/app.js" }))
    await state.routeHandler!(makeRoute({ url: "data:text/javascript,void(0)" }))

    expect(state.continued).toEqual(["https://example.com/app.js", "data:text/javascript,void(0)"])
    expect(state.aborted).toEqual([])
    await engine.close()
  })

  test("the guard aborts an out-of-scope main-frame redirect hop", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine({ allowedTargets: ["https://example.com"] })
    await engine.launch()
    await engine.createContext()

    await state.routeHandler!(
      makeRoute({ url: "https://evil.test/landing", navigation: true }),
    )

    expect(state.aborted).toHaveLength(1)
    expect(engine.scopeViolations.at(-1)).toMatchObject({
      url: "https://evil.test/landing",
      navigation: true,
    })
    await engine.close()
  })

  test("warn mode records the violation but lets the request through", async () => {
    const { PlaywrightEngine } = await import("../../../../src/argus/browser/engine")
    const engine = new PlaywrightEngine({
      allowedTargets: ["https://example.com"],
      mode: "warn",
    })
    await engine.launch()
    await engine.createContext()

    await state.routeHandler!(makeRoute({ url: "https://cdn.evil.test/x.js" }))

    expect(state.aborted).toEqual([])
    expect(state.continued).toEqual(["https://cdn.evil.test/x.js"])
    expect(engine.scopeViolations).toHaveLength(1)
    await engine.close()
  })
})

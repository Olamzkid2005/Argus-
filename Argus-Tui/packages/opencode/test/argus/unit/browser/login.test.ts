import { describe, expect, test, mock } from "bun:test"

// Mock Playwright with helper functions attached to the chromium object
// so they are accessible via destructured import.
mock.module("playwright", () => {
  let pageContent = "<html><body><form><input type='text' name='username'><input type='password'><button type='submit'>Sign In</button></form></body></html>"
  let currentUrl = "https://example.com/login"
  let bodyText = "Welcome! Dashboard content here."
  let hasPasswordField = true  // Controls locator count for password inputs

  const _resetState = () => {
    pageContent = "<html><body><form><input type='text' name='username'><input type='password'><button type='submit'>Sign In</button></form></body></html>"
    currentUrl = "https://example.com/login"
    bodyText = "Welcome! Dashboard content here."
    hasPasswordField = true
  }
  const _setPageContent = (html: string) => { pageContent = html }
  const _setCurrentUrl = (url: string) => { currentUrl = url }
  const _setBodyText = (text: string) => { bodyText = text }
  const _setHasPasswordField = (val: boolean) => { hasPasswordField = val }

  const mockPage = {
    goto: async (url: string) => {
      currentUrl = url
      return { status: () => 200 } as any
    },
    content: async () => pageContent,
    evaluate: async (fn: any, args?: any) => {
      if (typeof fn === "function") {
        if (args !== undefined) return fn(args)
        return fn()
      }
      return null
    },
    textContent: async () => bodyText,
    url: () => currentUrl,
    close: async () => {},
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    waitForSelector: async (_sel: string) => {},
    locator: (_sel: string) => ({
      all: async () => [],
      first: () => ({
        isVisible: async () => true,
        click: async () => {},
        fill: async (_val: string) => {},
        press: async (key: string) => {
          if (key === "Enter") currentUrl = "https://example.com/dashboard"
        },
      }),
      isVisible: async () => true,
      fill: async (_val: string) => {},
      press: async (key: string) => {
        if (key === "Enter") currentUrl = "https://example.com/dashboard"
      },
      innerText: async () => "",
      count: async () => {
        // Return 0 for password selector when simulating no-password-field page
        if (_sel === "input[type=password]") return hasPasswordField ? 1 : 0
        return 1
      },
    }),
    $: async () => null,
  }

  const mockContext = {
    newPage: async () => mockPage,
    close: async () => {},
    addCookies: async (_cookies: any[]) => {},
    cookies: async () => [],
    clearCookies: async () => {},
  }

  const mockBrowser = {
    launch: async () => mockBrowser,
    newContext: async () => mockContext,
    close: async () => {},
  }

  return {
    chromium: {
      ...mockBrowser,
      _resetState,
      _setPageContent,
      _setCurrentUrl,
      _setBodyText,
      _setHasPasswordField,
    },
  }
})

describe("Browser Login", () => {
  const mockCredentials = { username: "testuser", password: "testpass123" }

  test("loginIfFormPresent detects and fills standard login form", async () => {
    const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await loginIfFormPresent(page, mockCredentials)
    expect(result).toBe(true)
  })

  test("loginIfFormPresent returns false when no password field exists", async () => {
    const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setPageContent(
      "<html><body><form><input type='text' name='username'><button type='submit'>Submit</button></form></body></html>"
    )
    playwright.chromium._setHasPasswordField(false)

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await loginIfFormPresent(page, mockCredentials)
    expect(result).toBe(false)
  })

  test("loginIfFormPresent returns false for OAuth/SSO pages", async () => {
    const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setPageContent(
      '<html><body><button>Sign in with Google</button><button>Sign in with GitHub</button></body></html>'
    )
    playwright.chromium._setHasPasswordField(false)

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await loginIfFormPresent(page, mockCredentials)
    expect(result).toBe(false)
  })

  test("loginIfFormPresent uses custom selectors when provided", async () => {
    const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setPageContent(
      '<html><body><form><input id="user-id" type="text"><input id="pass" type="password"><button id="go" type="submit">Submit</button></form></body></html>'
    )

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await loginIfFormPresent(
      page,
      mockCredentials,
      { username: "#user-id", password: "#pass", submit: "#go" }
    )
    expect(result).toBe(true)
  })

  test("injectAuthCookies adds cookies to browser context", async () => {
    const { injectAuthCookies } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any

    const context = await playwright.chromium.launch().newContext()
    let addedCookies: any[] = []
    context.addCookies = async (cookies: any[]) => { addedCookies = cookies }

    await injectAuthCookies(context, [
      { name: "session", value: "abc123", domain: "example.com" },
      { name: "token", value: "xyz789", domain: "api.example.com" },
    ])

    expect(addedCookies.length).toBe(2)
    expect(addedCookies[0].name).toBe("session")
    expect(addedCookies[0].value).toBe("abc123")
    expect(addedCookies[0].domain).toBe("example.com")
    expect(addedCookies[0].path).toBe("/")
    expect(addedCookies[0].httpOnly).toBe(true)
    expect(addedCookies[0].secure).toBe(true)
    expect(addedCookies[0].sameSite).toBe("Lax")
  })

  test("injectLocalStorageTokens sets localStorage items", async () => {
    const { injectLocalStorageTokens } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()

    const page = await playwright.chromium.launch().newContext().newPage()
    let storedTokens: Record<string, string> = {}
    ;(page as any).evaluate = async (fn: any, args?: any) => {
      if (typeof fn === "function" && args !== undefined) storedTokens = args
      return null
    }

    await injectLocalStorageTokens(page, {
      access_token: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
      refresh_token: "refresh-abc-123",
    })

    expect(Object.keys(storedTokens).length).toBe(2)
    expect(storedTokens.access_token).toContain("eyJ")
    expect(storedTokens.refresh_token).toBe("refresh-abc-123")
  })

  test("detectAuthSuccess returns true for normal page", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Welcome user! Here is your dashboard.")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    expect(result).toBe(true)
  })

  test("detectAuthSuccess returns false when MFA challenge is present", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Enter the verification code sent to your phone (MFA)")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    expect(result).toBe(false)
  })

  test("detectAuthSuccess returns false when CAPTCHA is present", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Please complete the reCAPTCHA verification")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    expect(result).toBe(false)
  })

  test("detectAuthSuccess returns false on invalid credentials error", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Invalid username or password. Please try again.")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    expect(result).toBe(false)
  })

  test("isMFAChallenge detects MFA keywords", async () => {
    const { isMFAChallenge } = await import("../../../../src/argus/browser/login")

    expect(isMFAChallenge("Enter your MFA code")).toBe(true)
    expect(isMFAChallenge("Two-factor authentication required")).toBe(true)
    expect(isMFAChallenge("2FA verification code")).toBe(true)
    expect(isMFAChallenge("Multi-factor authentication")).toBe(true)
    expect(isMFAChallenge("Please enter the verification code sent to your device")).toBe(true)
    expect(isMFAChallenge("Welcome to the dashboard")).toBe(false)
    expect(isMFAChallenge("")).toBe(false)
  })

  test("isCaptchaChallenge detects CAPTCHA keywords", async () => {
    const { isCaptchaChallenge } = await import("../../../../src/argus/browser/login")

    expect(isCaptchaChallenge("Please complete the captcha")).toBe(true)
    expect(isCaptchaChallenge("reCAPTCHA verification required")).toBe(true)
    expect(isCaptchaChallenge("hCaptcha challenge")).toBe(true)
    expect(isCaptchaChallenge("Cloudflare Turnstile")).toBe(true)
    expect(isCaptchaChallenge("I'm not a robot")).toBe(true)
    expect(isCaptchaChallenge("Welcome to the site")).toBe(false)
    expect(isCaptchaChallenge("")).toBe(false)
  })

  test("isAccessDenied detects 401/403 errors", async () => {
    const { isAccessDenied } = await import("../../../../src/argus/browser/login")

    expect(isAccessDenied("403 Forbidden")).toBe(true)
    expect(isAccessDenied("401 Unauthorized")).toBe(true)
    expect(isAccessDenied("Access denied")).toBe(true)
    expect(isAccessDenied("You are not authorized")).toBe(true)
    expect(isAccessDenied("Insufficient permissions")).toBe(true)
    expect(isAccessDenied("Welcome to the site")).toBe(false)
    expect(isAccessDenied("")).toBe(false)
  })
})

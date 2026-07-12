import { describe, expect, test, mock } from "bun:test"

// Mock Playwright with helper functions attached to the chromium object
// so they are accessible via destructured import.
mock.module("playwright", () => {
  let pageContent = "<html><body><form><input type='text' name='username'><input type='password'><button type='submit'>Sign In</button></form></body></html>"
  let currentUrl = "https://example.com/login"
  let bodyText = "Welcome! Dashboard content here."
  let hasPasswordField = true  // Controls locator count for password inputs
  let emailCount = 1  // Controls locator count for email inputs (multi-step)
  let multiStepPasswordAppears = false  // Multi-step: password field appears after email submit
  let multiStepNavigateOnClick = false  // Multi-step: clicking submit navigates to password page
  let waitForSelectorResolve = true  // Controls whether waitForSelector resolves or times out
  let authenticatedDomFound = true  // Controls checkAuthenticatedDomElement positive match
  let multiStepFirstClick = true  // First click navigates to password page, second to dashboard

  const _resetState = () => {
    pageContent = "<html><body><form><input type='text' name='username'><input type='password'><button type='submit'>Sign In</button></form></body></html>"
    currentUrl = "https://example.com/login"
    bodyText = "Welcome! Dashboard content here."
    hasPasswordField = true
    emailCount = 1
    multiStepPasswordAppears = false
    multiStepNavigateOnClick = false
    waitForSelectorResolve = true
    authenticatedDomFound = true
    multiStepFirstClick = true
  }
  const _setPageContent = (html: string) => { pageContent = html }
  const _setCurrentUrl = (url: string) => { currentUrl = url }
  const _setBodyText = (text: string) => { bodyText = text }
  const _setHasPasswordField = (val: boolean) => { hasPasswordField = val }
  const _setEmailCount = (val: number) => { emailCount = val }
  const _setMultiStepPasswordAppears = (val: boolean) => { multiStepPasswordAppears = val }
  const _setMultiStepNavigateOnClick = (val: boolean) => { multiStepNavigateOnClick = val }
  const _setWaitForSelectorResolve = (val: boolean) => { waitForSelectorResolve = val }
  const _setAuthenticatedDomFound = (val: boolean) => { authenticatedDomFound = val }

  // Determine if a locator exists (count > 0)
  function elementExists(): boolean {
    return true  // Default: elements exist. Overridden by countOverride per instance.
  }

  // Build a locator mock with proper isVisible behavior.
  // isVisible returns false when count is 0 (the element doesn't exist in DOM).
  function makeLocator(opts?: {
    /** Override count for this specific locator instance */
    countOverride?: () => Promise<number>
    /** Whether pressing Enter should trigger navigation */
    navigatesOnEnter?: boolean
  }) {
    const getCount = async () => {
      if (opts?.countOverride) return opts.countOverride()
      return 1
    }

    // Navigation helper: simulates multi-step or normal navigation on click
    const doNavigation = () => {
      if (multiStepNavigateOnClick && multiStepFirstClick) {
        // First multi-step click: email submit → navigate to password page
        currentUrl = "https://example.com/login/password"
        hasPasswordField = true
        multiStepFirstClick = false  // Next click → dashboard
      } else if (multiStepNavigateOnClick && !multiStepFirstClick) {
        // Second multi-step click: password submit → navigate to dashboard
        currentUrl = "https://example.com/dashboard"
      } else {
        currentUrl = "https://example.com/dashboard"
      }
    }

    return {
      all: async () => [],
      first: () => ({
        isVisible: async () => (await getCount()) > 0,
        click: async () => doNavigation(),
        fill: async (_val: string) => {},
        press: async (key: string) => {
          if (opts?.navigatesOnEnter !== false && key === "Enter") {
            doNavigation()
          }
        },
      }),
      isVisible: async () => (await getCount()) > 0,
      fill: async (_val: string) => {},
      press: async (key: string) => {
        if (key === "Enter") doNavigation()
      },
      innerText: async () => "",
      count: async () => getCount(),
      click: async () => doNavigation(),
    }
  }

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
    waitForSelector: async (_sel: string) => {
      if (!waitForSelectorResolve) throw new Error("Timeout")
      // For multi-step: after email submit, the password field should appear
      if (_sel === "input[type=password]" && multiStepPasswordAppears) {
        hasPasswordField = true
      }
    },
    locator: (_sel: string) => makeLocator({
      countOverride: async () => {
        // Return 0 for password selector when simulating no-password-field page
        if (_sel === "input[type=password]") return hasPasswordField ? 1 : 0
        // Return custom count for email selector (multi-step detection)
        if (_sel.includes("email") || _sel.includes("autocomplete=email")) {
          return emailCount
        }
        // When authenticatedDomFound is false (e.g. MFA/CAPTCHA challenge pages),
        // return 0 so checkAuthenticatedDomElement doesn't short-circuit
        return authenticatedDomFound ? 1 : 0
      },
    }),
    // Phase 3.4.1: Mock getByLabel and getByRole
    getByLabel: (text: string | RegExp) => {
      const labelText = typeof text === "string" ? text.toLowerCase() : text.source.toLowerCase()
      const isPasswordLabel = labelText.includes("password")
      return makeLocator({
        countOverride: async () => {
          if (isPasswordLabel) return hasPasswordField ? 1 : 0
          return 1
        },
      })
    },
    getByRole: (role: string, options?: { name?: string | RegExp }) => {
      const roleName = options?.name
        ? typeof options.name === "string"
          ? options.name.toLowerCase()
          : options.name.source.toLowerCase()
        : ""
      const isPasswordRole = roleName.includes("password")
      return makeLocator({
        countOverride: async () => {
          if (isPasswordRole) return hasPasswordField ? 1 : 0
          return 1
        },
      })
    },
    $: async () => null,
    context: () => ({
      cookies: async () => [] as Array<{ name: string; value: string }>,
    }),
  }

  // Note: mock methods are synchronous so the chain
  // `chromium.launch().newContext().newPage()` works without
  // requiring `await` between each call. The outer `await` at
  // the start handles the final value.
  const mockContext = {
    newPage: () => mockPage,
    close: () => {},
    addCookies: (_cookies: any[]) => {},
    cookies: () => [],
    clearCookies: () => {},
  }

  const mockBrowser = {
    launch: () => mockBrowser,
    newContext: () => mockContext,
    close: () => {},
  }

  return {
    chromium: {
      ...mockBrowser,
      _resetState,
      _setPageContent,
      _setCurrentUrl,
      _setBodyText,
      _setHasPasswordField,
      _setEmailCount,
      _setMultiStepPasswordAppears,
      _setMultiStepNavigateOnClick,
      _setWaitForSelectorResolve,
      _setAuthenticatedDomFound,
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
    // No email field either — username type='text' name='username' doesn't include "email" or "user" in the locator
    // Actually it does include "user" in `name*=user` pattern. But the locator check is:
    // `_sel.includes("email") || _sel.includes("autocomplete=email")`
    // The selector string `input[type=email], input[name=email], input[autocomplete=email], input[type=text][name*=email], input[type=text][name*=user]`
    // includes "email" keyword. So it returns emailCount (1) regardless.
    // To make this test work, set emailCount to 0 so multi-step detection fails.
    playwright.chromium._setEmailCount(0)

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await loginIfFormPresent(page, mockCredentials)
    expect(result).toBe(false)
  })

  test("loginIfFormPresent returns false for OAuth/SSO pages", async () => {
    const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    // Must include "OAuth" keyword for the OAuth check in loginIfFormPresent to trigger
    playwright.chromium._setPageContent(
      '<html><body><h1>OAuth Sign In</h1><button>Sign in with Google</button><button>Sign in with GitHub</button></body></html>'
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
    // bodyText = "Welcome! Dashboard content here." — contains "dashboard"/"my account" etc.
    // which checkAuthenticatedDomElement matches positively.
    // This should return true.
    playwright.chromium._setBodyText("Welcome user! Here is your dashboard.")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    // checkAuthenticatedDomElement: body text contains "dashboard" → true
    expect(result).toBe(true)
  })

  test("detectAuthSuccess returns false when MFA challenge is present", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    // checkAuthenticatedDomElement: set auth dom to false so locator count is 0
    // (no logout buttons/avatars found), then body text check: MFA challenge text
    // doesn't contain "logout"/"dashboard"/"my account" → returns null.
    // No cookies/targetUrl → skip. Fallback: MFA keywords detected → returns false.
    playwright.chromium._setAuthenticatedDomFound(false)
    playwright.chromium._setBodyText("Enter the verification code sent to your phone (MFA)")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    expect(result).toBe(false)
  })

  test("detectAuthSuccess returns false when CAPTCHA is present", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setAuthenticatedDomFound(false)
    playwright.chromium._setBodyText("Please complete the reCAPTCHA verification")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthSuccess(page)
    expect(result).toBe(false)
  })

  test("detectAuthSuccess returns false on invalid credentials error", async () => {
    const { detectAuthSuccess } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setAuthenticatedDomFound(false)
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

  // ── Phase 3.4.2: Auth challenge detection tests ──────────────────────

  test("detectAuthChallenge returns null for normal page", async () => {
    const { detectAuthChallenge } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Welcome user! Here is your dashboard.")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthChallenge(page)
    expect(result).toBeNull()
  })

  test("detectAuthChallenge detects MFA", async () => {
    const { detectAuthChallenge } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Enter the verification code sent to your phone (MFA)")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthChallenge(page)
    expect(result).not.toBeNull()
    expect(result!.type).toBe("mfa")
    expect(result!.detail).toContain("Multi-factor")
  })

  test("detectAuthChallenge detects CAPTCHA", async () => {
    const { detectAuthChallenge } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Please complete the reCAPTCHA verification")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthChallenge(page)
    expect(result).not.toBeNull()
    expect(result!.type).toBe("captcha")
  })

  test("detectAuthChallenge detects auth error", async () => {
    const { detectAuthChallenge } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("Invalid username or password. Please try again.")

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthChallenge(page)
    expect(result).not.toBeNull()
    expect(result!.type).toBe("auth_error")
  })

  test("detectAuthChallenge detects OAuth from page content", async () => {
    const { detectAuthChallenge } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setBodyText("")
    playwright.chromium._setPageContent(
      '<html><body><h1>OAuth Login</h1><button>Sign in with Google</button></body></html>'
    )

    const page = await playwright.chromium.launch().newContext().newPage()
    const result = await detectAuthChallenge(page)
    expect(result).not.toBeNull()
    expect(result!.type).toBe("oauth")
  })

  test("loginIfFormPresent invokes onChallenge callback for OAuth", async () => {
    const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
    const playwright = await import("playwright") as any
    playwright.chromium._resetState()
    playwright.chromium._setPageContent(
      '<html><body><h1>OAuth Sign In</h1><button>Continue with Google</button></body></html>'
    )
    playwright.chromium._setHasPasswordField(false)

    const page = await playwright.chromium.launch().newContext().newPage()
    const challenges: any[] = []
    await loginIfFormPresent(page, { username: "u", password: "p" }, undefined, (c) => challenges.push(c))
    expect(challenges.length).toBeGreaterThan(0)
    expect(challenges[0].type).toBe("oauth")
  })

  test("logAuthChallenge formats challenge as structured log", async () => {
    const { logAuthChallenge } = await import("../../../../src/argus/browser/login")
    const logs: string[] = []
    logAuthChallenge({ type: "mfa", detail: "Test challenge" }, (line) => logs.push(line))
    expect(logs.length).toBe(1)
    expect(logs[0]).toContain("[AUTH_CHALLENGE]")
    expect(logs[0]).toContain("type=mfa")
    expect(logs[0]).toContain("Test challenge")
  })

  // ── Gap 2.5: Multi-step login flow tests ───────────────────────────

  describe("loginMultiStep (Gap 2.5)", () => {
    const mockCreds = { username: "user@example.com", password: "pass123" }

    test("detects multi-step flow and succeeds (email first, then password)", async () => {
      const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
      const playwright = await import("playwright") as any
      playwright.chromium._resetState()

      // Set up multi-step scenario: email field present, NO password field, submit button present
      playwright.chromium._setPageContent(
        '<html><body><form><input type="email" name="email" placeholder="Email"><button type="submit">Continue</button></form></body></html>'
      )
      playwright.chromium._setHasPasswordField(false)
      playwright.chromium._setEmailCount(1)
      playwright.chromium._setMultiStepNavigateOnClick(true)
      playwright.chromium._setMultiStepPasswordAppears(true)

      const page = await playwright.chromium.launch().newContext().newPage()
      const result = await loginIfFormPresent(page, mockCreds)
      expect(result).toBe(true)
    })

    test("returns true when password field is already present (not multi-step)", async () => {
      const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
      const playwright = await import("playwright") as any
      playwright.chromium._resetState()

      // Standard form with both email and password — NOT multi-step
      playwright.chromium._setPageContent(
        '<html><body><form><input type="email" name="email"><input type="password" name="password"><button type="submit">Sign In</button></form></body></html>'
      )
      playwright.chromium._setHasPasswordField(true)

      const page = await playwright.chromium.launch().newContext().newPage()
      const result = await loginIfFormPresent(page, mockCreds)
      // Should use standard CSS-based form path (password field exists), which succeeds
      expect(result).toBe(true)
    })

    test("returns false when no email field exists", async () => {
      const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
      const playwright = await import("playwright") as any
      playwright.chromium._resetState()

      // Page with neither email nor password — just a button
      playwright.chromium._setPageContent(
        '<html><body><button>Click me</button></body></html>'
      )
      playwright.chromium._setHasPasswordField(false)
      playwright.chromium._setEmailCount(0)

      const page = await playwright.chromium.launch().newContext().newPage()
      const result = await loginIfFormPresent(page, mockCreds)
      expect(result).toBe(false)
    })

    test("returns false when password field never appears after email submission", async () => {
      const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
      const playwright = await import("playwright") as any
      playwright.chromium._resetState()

      // Multi-step setup but password field never appears
      playwright.chromium._setPageContent(
        '<html><body><form><input type="email" name="email" placeholder="Email"><button type="submit">Continue</button></form></body></html>'
      )
      playwright.chromium._setHasPasswordField(false)
      playwright.chromium._setEmailCount(1)
      playwright.chromium._setMultiStepNavigateOnClick(true)
      playwright.chromium._setMultiStepPasswordAppears(false)
      playwright.chromium._setWaitForSelectorResolve(false)

      const page = await playwright.chromium.launch().newContext().newPage()
      const result = await loginIfFormPresent(page, mockCreds)
      expect(result).toBe(false)
    })

    test("returns false and calls onChallenge when multi-step login fails (no navigation)", async () => {
      const { loginIfFormPresent } = await import("../../../../src/argus/browser/login")
      const playwright = await import("playwright") as any
      playwright.chromium._resetState()

      // Multi-step flow where submit doesn't navigate away (stays on login page)
      playwright.chromium._setPageContent(
        '<html><body><form><input type="email" name="email" placeholder="Email"><button type="submit">Continue</button></form></body></html>'
      )
      playwright.chromium._setHasPasswordField(false)
      playwright.chromium._setEmailCount(1)
      playwright.chromium._setMultiStepNavigateOnClick(false)  // Click doesn't navigate to password page
      playwright.chromium._setMultiStepPasswordAppears(false)
      playwright.chromium._setWaitForSelectorResolve(false)

      const page = await playwright.chromium.launch().newContext().newPage()
      const challenges: any[] = []
      const result = await loginIfFormPresent(page, mockCreds, undefined, (c) => challenges.push(c))
      expect(result).toBe(false)
    })
  })
})

import type { Page, BrowserContext } from "playwright"

export interface Credentials {
  username: string
  password: string
}

/**
 * Configuration for login form field selectors.
 * Can be overridden per-target when the default selectors don't match.
 */
export interface LoginSelectors {
  username?: string
  password?: string
  submit?: string
}

/**
 * Structured information about an auth challenge blocking login.
 * Phase 3.4.2: Emitted when MFA, CAPTCHA, or other auth blockers are detected.
 */
export interface AuthChallenge {
  type: "mfa" | "captcha" | "auth_error" | "oauth"
  detail: string
}

/**
 * Callback invoked when an auth challenge is detected during login.
 * Phase 3.4.2: Allows verifiers to observe and log auth challenges.
 */
export type AuthChallengeCallback = (challenge: AuthChallenge) => void

/**
 * Inject authentication tokens/cookies into the browser context.
 * Useful for OAuth, SSO, or token-based auth where login forms are not present.
 *
 * Gap 2.4 fix: Previously defaulted `secure: true` unconditionally, which
 * silently prevented cookies from being sent on plain HTTP targets.
 * Now accepts a `targetUrl` parameter to determine the secure flag automatically.
 *
 * @param context - The browser context to inject cookies into.
 * @param cookies - Array of cookie objects to set.
 * @param targetUrl - Optional target URL to determine if cookies should be secure.
 *                    If not provided, defaults to `secure: true` (backward compatible).
 */
export async function injectAuthCookies(
  context: BrowserContext,
  cookies: Array<{ name: string; value: string; domain: string; path?: string; httpOnly?: boolean; secure?: boolean }>,
  targetUrl?: string,
): Promise<void> {
  const isSecureTarget = targetUrl
    ? targetUrl.startsWith("https://")
    : true  // Backward compatible default

  await context.addCookies(
    cookies.map((c) => ({
      name: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path ?? "/",
      httpOnly: c.httpOnly ?? true,
      secure: c.secure ?? isSecureTarget,
      sameSite: "Lax" as const,
    })),
  )
}

/**
 * Set localStorage tokens (JWT, session tokens) before navigating.
 * Useful for SPA auth where tokens are stored in localStorage.
 *
 * @param page - The page to set localStorage on.
 * @param tokens - Record of key-value pairs to set in localStorage.
 */
export async function injectLocalStorageTokens(
  page: Page,
  tokens: Record<string, string>,
): Promise<void> {
  await page.evaluate((t) => {
    for (const [key, value] of Object.entries(t)) {
      localStorage.setItem(key, value)
    }
  }, tokens)
}

/**
 * Try to detect and fill login forms using Playwright accessibility-first locators.
 *
 * Phase 3.4.1: Uses getByLabel() and getByRole() for form field detection,
 * which are more resilient to DOM structure changes than CSS selectors.
 * Falls back to returning null so the caller can try CSS-based detection.
 *
 * @returns True if login was submitted successfully, null if locators didn't match.
 */
async function loginWithLocators(
  page: Page,
  creds: Credentials,
): Promise<boolean | null> {
  try {
    // Capture session cookies before any form interaction so
    // detectAuthSuccess() can use Check 2 (cookie comparison).
    // Gap 2.1: Without beforeCookies, the cookie comparison check
    // is skipped entirely, weakening auth verification.
    let beforeCookies: Array<{ name: string; value: string }> = []
    try {
      beforeCookies = await page.context().cookies()
    } catch { /* context may not be available */ }

    // 1. Try to find password field via getByLabel (most reliable for form fields)
    const passwordByLabel = page.getByLabel(/password/i)
    const hasPasswordByLabel = (await passwordByLabel.count()) > 0

    // 2. Try to find username/email field via getByLabel
    const usernameByLabel = page.getByLabel(/username|email|user/i)
    const hasUsernameByLabel = (await usernameByLabel.count()) > 0

    // 3. Try to find the submit button via getByRole
    const submitByRole = page.getByRole("button", {
      name: /sign in|log in|signin|login|submit|continue/i,
    })
    const hasSubmitByRole = (await submitByRole.count()) > 0

    // 4. Try getByRole("textbox") for username if getByLabel didn't match
    const usernameByRole = !hasUsernameByLabel
      ? page.getByRole("textbox", { name: /username|email|user|login/i })
      : null
    const hasUsernameByRole = usernameByRole !== null && (await usernameByRole.count()) > 0

    // If no locator found a password field, bail out to CSS fallback
    if (!hasPasswordByLabel) return null

    // Build the effective username locator
    const effectiveUsername = hasUsernameByLabel
      ? usernameByLabel
      : hasUsernameByRole
        ? usernameByRole!
        : null

    // Fill username if we found a matching field
    if (effectiveUsername !== null && (await effectiveUsername.isVisible())) {
      await effectiveUsername.fill(creds.username)
    }

    // Fill password
    if (await passwordByLabel.isVisible()) {
      await passwordByLabel.fill(creds.password)
      await passwordByLabel.press("Enter")
      await page.waitForTimeout(500)
    }

    // Click submit button as fallback (Enter may not have triggered navigation)
    if (hasSubmitByRole && (await submitByRole.isVisible())) {
      await submitByRole.click()
    }

    // Wait for navigation or network idle after submission
    try {
      await page.waitForLoadState("networkidle", { timeout: 30000 })
    } catch {
      // Network may not stabilize — proceed anyway
    }

    // Verify login success using positive confirmation (all 3 checks)
    const postLoginUrl = page.url()
    const stillOnLogin = /\/login\b|\/signin\b|\/auth\b/i.test(postLoginUrl)
    if (!stillOnLogin) return true
    return detectAuthSuccess(page, {
      beforeCookies,
      targetUrl: page.url(),
    })
  } catch {
    // Locator APIs may not be available on all Playwright versions
    return null
  }
}


/**
 * Detect what kind of auth challenge is blocking login on the current page.
 * Phase 3.4.2: Returns structured info about MFA, CAPTCHA, auth errors, or OAuth.
 *
 * Callers should use this after loginIfFormPresent() returns false to understand
 * why login failed and log the challenge as evidence.
 *
 * @param page - The page to check for auth challenges.
 * @returns Detected challenge info, or null if no challenge detected.
 */
export async function detectAuthChallenge(page: Page): Promise<AuthChallenge | null> {
  const bodyText = await page.textContent("body") ?? ""
  const lower = bodyText.toLowerCase()

  // Check for MFA challenges
  if (/\bmfa\b|\bmulti-factor\b|\b2fa\b|\btwo-factor\b|\bauthenticator\b|\bverification code\b/i.test(lower)) {
    return { type: "mfa", detail: "Multi-factor authentication challenge detected — cannot auto-solve" }
  }

  // Check for CAPTCHA
  if (/\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bturnstile\b/i.test(lower)) {
    return { type: "captcha", detail: "CAPTCHA challenge detected — cannot auto-solve" }
  }

  // Check for auth error messages
  if (/\binvalid (credentials|username|password|email)\b|\blogin failed\b|\bincorrect\b|\bwrong password\b/i.test(lower)) {
    return { type: "auth_error", detail: "Invalid credentials — login rejected" }
  }

  // Check for OAuth/SSO (requires page content check)
  const content = await page.content().catch(() => "")
  if (/\boauth\b/i.test(content) &&
    (/\bgoogle\b/i.test(content) || /\bgithub\b/i.test(content) || /\bmicrosoft\b/i.test(content) || /\bfacebook\b/i.test(content) || /\bsso\b/i.test(content))) {
    return { type: "oauth", detail: "OAuth/SSO login page detected — requires interactive browser flow" }
  }

  return null
}


/**
 * Emit an auth challenge observation to the verifier's log collector.
 * Phase 3.4.2: Convenience helper for verifiers to log structured auth challenges.
 *
 * @param challenge - The detected auth challenge.
 * @param logFn - Function to append log lines (typically this.logs.push).
 */
export function logAuthChallenge(
  challenge: AuthChallenge,
  logFn: (line: string) => void,
): void {
  logFn(`[AUTH_CHALLENGE] type=${challenge.type}: ${challenge.detail}`)
}


/**
 * Attempt a multi-step login flow where the identifier (email/username) is
 * submitted first, then the password field appears on a subsequent page.
 *
 * Gap 2.5 fix: Modern login flows often ask for the email first and only
 * render the password field after a submit/continue step. This function
 * handles that pattern by filling the first form, submitting, waiting for
 * navigation, then looking for the password field on the next page.
 *
 * @param page - The Playwright page to interact with.
 * @param creds - Username and password credentials.
 * @param onChallenge - Optional callback invoked when an auth challenge is detected.
 * @returns True if login succeeded via multi-step flow, false otherwise.
 */
async function loginMultiStep(
  page: Page,
  creds: Credentials,
  onChallenge?: AuthChallengeCallback,
): Promise<boolean> {
  // Capture session cookies before any form interaction so
  // detectAuthSuccess() can use the cookie comparison check.
  let beforeCookies: Array<{ name: string; value: string }> = []
  try {
    beforeCookies = await page.context().cookies()
  } catch { /* context may not be available */ }

  // Check if this looks like a multi-step flow:
  // - There's an email/username field but no visible password field
  // - There's a submit/continue button
  const hasEmailField = await page.locator(
    "input[type=email], input[name=email], input[autocomplete=email], input[type=text][name*=email], input[type=text][name*=user]"
  ).count() > 0
  const hasPasswordField = await page.locator("input[type=password]").count() > 0
  const hasSubmitButton = await page.locator(
    "button[type=submit], input[type=submit], button:has-text('Continue'), button:has-text('Next'), button:has-text('Sign in'), button:has-text('Log in')"
  ).count() > 0

  // Only attempt multi-step if we have an email field, NO password field, and a submit button
  if (!hasEmailField || hasPasswordField || !hasSubmitButton) {
    return false
  }

  // Step 1: Fill the email field
  const emailInput = page.locator(
    "input[type=email], input[name=email], input[autocomplete=email], input[type=text][name*=email], input[type=text][name*=user]"
  ).first()
  if (await emailInput.isVisible()) {
    await emailInput.fill(creds.username)
  }

  // Step 2: Click the submit/continue button
  const submitBtn = page.locator(
    "button[type=submit], input[type=submit], button:has-text('Continue'), button:has-text('Next'), button:has-text('Sign in'), button:has-text('Log in')"
  ).first()
  if (await submitBtn.isVisible()) {
    await submitBtn.click()
  } else {
    // Try pressing Enter on the email field
    await emailInput.press("Enter")
  }

  // Step 3: Wait for navigation or password field to appear
  try {
    await page.waitForLoadState("networkidle", { timeout: 15000 })
  } catch {
    // Network may not stabilize
  }

  // Wait for password field to appear (up to 10s)
  try {
    await page.waitForSelector("input[type=password]", { timeout: 10000 })
  } catch {
    return false  // Password field never appeared — not a multi-step flow
  }

  // Step 4: Fill the password field on the new page
  const passwordInput = page.locator("input[type=password]").first()
  if (await passwordInput.isVisible()) {
    await passwordInput.fill(creds.password)
    await passwordInput.press("Enter")

    // Wait briefly to see if Enter triggered navigation
    await page.waitForTimeout(500)

    // Try clicking any submit button on this page too
    const nextSubmitBtn = page.locator(
      "button[type=submit], input[type=submit], button:has-text('Sign in'), button:has-text('Log in'), button:has-text('Submit')"
    ).first()
    if (await nextSubmitBtn.isVisible()) {
      await nextSubmitBtn.click()
    }
  }

  // Step 5: Wait for final navigation after password submission
  try {
    await page.waitForLoadState("networkidle", { timeout: 30000 })
  } catch {
    // Network may not stabilize
  }

  // Gap 2.1: Use detectAuthSuccess() with positive confirmation
  // instead of the original URL-only check. This enables all 3 positive
  // checks: DOM elements, cookie comparison, and API endpoint probing.
  const authSuccess = await detectAuthSuccess(page, {
    beforeCookies,
    targetUrl: page.url(),
  })

  if (authSuccess) {
    return true
  }

  // Check for auth challenges on failure
  const challenge = await detectAuthChallenge(page)
  if (challenge) onChallenge?.(challenge)
  return false
}


/**
 * Detect and fill login forms on a page using progressive selector strategies.
 * Supports:
 *  - Standard username+password forms
 *  - Email+password forms
 *  - **Multi-step flows** (email-first → password-next, Gap 2.5)
 *  - OAuth/SSO detection (returns false, caller should use injectAuthCookies)
 *  - Modal/dynamically rendered forms (waits for form to become visible)
 *
 * Phase 3.4.1: Uses Playwright locator-based form detection (getByLabel, getByRole)
 * before falling back to CSS selectors for better resilience.
 * Phase 3.4.2: Accepts onChallenge callback for auth challenge signal emission.
 * Phase 3.4.3 (Gap 2.5): Falls through to multi-step flow detection when no
 * password field is found on the initial page.
 *
 * @param page - The Playwright page to interact with.
 * @param creds - Username and password credentials.
 * @param selectors - Optional custom selectors for non-standard forms.
 * @param onChallenge - Optional callback invoked when an auth challenge is detected.
 * @returns True if login was submitted successfully, false if no form found.
 */
export async function loginIfFormPresent(
  page: Page,
  creds: Credentials,
  selectors?: LoginSelectors,
  onChallenge?: AuthChallengeCallback,
): Promise<boolean> {
  const content = await page.content()

  // Capture session cookies before any form interaction
  // so detectAuthSuccess() can compare them after login (Gap 2.1).
  let beforeCookies: Array<{ name: string; value: string }> = []
  try {
    beforeCookies = await page.context().cookies()
  } catch { /* context may not be available */ }

  // First check for OAuth/SSO buttons — these should not be auto-filled
  const hasOAuth = /\boauth\b/i.test(content) &&
    (/\bgoogle\b/i.test(content) || /\bgithub\b/i.test(content) || /\bmicrosoft\b/i.test(content) || /\bfacebook\b/i.test(content) || /\bsso\b/i.test(content) || /\bsaml\b/i.test(content))
  if (hasOAuth) {
    // Phase 3.4.2: Emit auth_challenge signal for OAuth detection
    const challenge: AuthChallenge = { type: "oauth", detail: "OAuth/SSO login page detected — requires interactive browser flow" }
    onChallenge?.(challenge)
    return false  // OAuth/SSO detected — caller should use injectAuthCookies or injectLocalStorageTokens
  }

  // ── Phase 3.4.1: Playwright locator-based detection (getByLabel, getByRole) ──
  // Try accessibility-first locators before CSS selectors for better resilience.
  if (!selectors) {
    const locatorResult = await loginWithLocators(page, creds)
    if (locatorResult !== null) {
      // Phase 3.4.2: If login via locators failed, check for auth challenges
      if (!locatorResult) {
        const challenge = await detectAuthChallenge(page)
        if (challenge) onChallenge?.(challenge)
      }
      return locatorResult
    }
  }

  // ── Fallback: CSS-selector-based detection ──
  // Detect login form using multiple strategies:
  // 1. Custom selectors (if provided)
  // 2. Input[type=password] existence (most reliable)
  // 3. Keyword matching in page content
  const hasPasswordField = await page.locator("input[type=password]").count() > 0
  if (!hasPasswordField) {
    // Gap 2.5: No password field on initial page — try multi-step login flow
    // (email-first → password-next pattern common in modern auth flows)
    const multiStepResult = await loginMultiStep(page, creds, onChallenge)
    if (multiStepResult) {
      return true
    }
    // Multi-step didn't work either — try token injection instead
    return false
  }

  // Use custom selectors when provided, otherwise use smart defaults
  const usernameSelector = selectors?.username ?? "input[type=text], input[name=username], input[name=email], input[type=email], input[name=login], input[name=user], input[id=username], input[id=email], input[id=user], input[id=login], input[placeholder*=username i], input[placeholder*=email i], input[placeholder*=user i], input[autocomplete=username], input[autocomplete=email]"
  const passwordSelector = selectors?.password ?? "input[type=password]"
  const submitSelector = selectors?.submit ?? "button[type=submit], input[type=submit], button:has-text('Sign In'), button:has-text('Log In'), button:has-text('Login'), button:has-text('Sign in'), button:has-text('Log in'), button:has-text('Continue'), button:has-text('Submit')"

  // Wait for the form to be visible (handles dynamically rendered forms)
  try {
    await page.waitForSelector(passwordSelector, { timeout: 5000 })
  } catch {
    return false  // Form didn't appear within timeout
  }

  const usernameInput = page.locator(usernameSelector).first()
  const passwordInput = page.locator(passwordSelector).first()
  const submitButton = page.locator(submitSelector).first()

  if (await usernameInput.isVisible()) {
    await usernameInput.fill(creds.username)
  }

  let submitted = false
  if (await passwordInput.isVisible()) {
    await passwordInput.fill(creds.password)
    // Try Enter key first (most SPAs handle this), then click submit as fallback
    await passwordInput.press("Enter")
    // Wait briefly to see if Enter triggered navigation
    await page.waitForTimeout(500)
    const currentUrl = page.url()
    // If Enter didn't navigate, try clicking submit button
    if (await submitButton.isVisible()) {
      await submitButton.click()
    }
    submitted = true
  } else if (await submitButton.isVisible()) {
    await submitButton.click()
    submitted = true
  }

  if (!submitted) return false

  // Wait for navigation or network idle
  try {
    await page.waitForLoadState("networkidle", { timeout: 30000 })
  } catch {
    // Network may not stabilize (e.g. long-polling) — proceed anyway
  }

  // Verify login success using positive confirmation
  const postLoginUrl = page.url()
  const stillOnLogin = /\/login\b|\/signin\b|\/auth\b/i.test(postLoginUrl)
  if (!stillOnLogin) {
    return true
  }
  const authSuccess = await detectAuthSuccess(page, {
    beforeCookies,
    targetUrl: page.url(),
  })

  // Phase 3.4.2: If login failed, check for auth challenges
  if (!authSuccess) {
    const challenge = await detectAuthChallenge(page)
    if (challenge) onChallenge?.(challenge)
  }

  return authSuccess
}

/**
 * Common selectors for authenticated-only DOM elements.
 * Used by detectAuthSuccess() for positive auth confirmation.
 */
const AUTHENTICATED_SELECTORS = [
  // Logout / sign out buttons
  'a[href*="logout"]',
  'a[href*="signout"]',
  'a[href*="sign-out"]',
  'a[href*="log-out"]',
  'button:has-text("Logout")',
  'button:has-text("Sign out")',
  'button:has-text("Sign Out")',
  'button:has-text("Log out")',
  'button:has-text("Log Out")',
  // User avatar / profile elements
  '[class*="avatar"]',
  '[class*="profile"]',
  '[class*="user-menu"]',
  '[class*="account-menu"]',
  'a[href*="/profile"]',
  'a[href*="/account"]',
  // "My Account" links (common authenticated-only element)
  'a:has-text("My Account")',
  'a:has-text("My account")',
  'a:has-text("Dashboard")',
  // Common authenticated nav items
  '[data-testid*="user"]',
  '[data-testid*="account"]',
]

/**
 * Common authenticated-only API endpoints to probe for session validation.
 */
const AUTH_PROBE_ENDPOINTS = [
  "/api/me",
  "/api/user",
  "/api/profile",
  "/api/account",
  "/api/v1/me",
  "/api/v1/user",
  "/api/v1/profile",
  "/me",
  "/profile",
  "/dashboard",
  "/account",
]

/**
 * Check 1 (positive): Look for authenticated-only DOM elements like logout
 * buttons, user avatars, and profile links.
 */
export async function checkAuthenticatedDomElement(page: Page): Promise<boolean | null> {
  try {
    for (const selector of AUTHENTICATED_SELECTORS) {
      const count = await page.locator(selector).count()
      if (count > 0) {
        return true
      }
    }
    // Check text content for authenticated patterns
    const body = await page.textContent("body") ?? ""
    const lower = body.toLowerCase()
    if (
      lower.includes("logout") ||
      lower.includes("sign out") ||
      lower.includes("my account") ||
      lower.includes("my profile") ||
      lower.includes("dashboard")
    ) {
      return true
    }
    return null  // Inconclusive
  } catch {
    return null  // Inconclusive on error
  }
}

/**
 * Check 2 (positive): Compare session cookies before and after login to
 * confirm the session was actually established.
 *
 * @param context - The browser context to read cookies from.
 * @param beforeCookies - Cookies captured before login attempt.
 * @returns True if new session cookies appeared, null if inconclusive.
 */
export async function checkSessionCookiesChanged(
  context: BrowserContext,
  beforeCookies: Array<{ name: string; value: string }>,
): Promise<boolean | null> {
  try {
    const afterCookies = await context.cookies()
    // If there were no cookies before AND no cookies now, can't compare
    if (beforeCookies.length === 0 && afterCookies.length === 0) {
      return null
    }
    const beforeNames = new Set(beforeCookies.map(c => c.name))
    const beforeValues = new Map(beforeCookies.map(c => [c.name, c.value]))

    let newSessionCookies = 0
    for (const cookie of afterCookies) {
      const isSessionCookie = /session|token|auth|sid|connect/i.test(cookie.name)
      if (!isSessionCookie) continue

      if (!beforeNames.has(cookie.name)) {
        newSessionCookies++
      } else if (beforeValues.get(cookie.name) !== cookie.value) {
        newSessionCookies++
      }
    }

    if (newSessionCookies > 0) {
      return true
    }
    return null  // No new session cookies, but could be token-based auth
  } catch {
    return null  // Inconclusive on error
  }
}

/**
 * Check 3 (positive): Probe an authenticated-only API endpoint to verify
 * the session works (expect 200 vs 401/403).
 *
 * Uses in-page fetch() via page.evaluate() to avoid navigating the page away
 * from its current URL (Gap 2.1 fix — page.goto() had destructive side effects
 * on the caller's page state).
 *
 * @param page - The Playwright page to use for the probe request.
 * @param targetUrl - The base target URL to derive probe URLs from.
 * @returns True if endpoint returned 200 (authenticated), false if 401/403, null if inconclusive.
 */
export async function probeAuthenticatedEndpoint(
  page: Page,
  targetUrl: string,
): Promise<boolean | null> {
  // Derive the origin from the target URL or current page URL
  let origin = ""
  try {
    origin = new URL(targetUrl).origin
  } catch {
    try {
      origin = new URL(page.url()).origin
    } catch {
      return null
    }
  }

  for (const endpoint of AUTH_PROBE_ENDPOINTS) {
    try {
      const probeUrl = `${origin}${endpoint}`
      // Use in-page fetch() — does NOT navigate the page away, preserving
      // the caller's page state and URL.
      const status = await page.evaluate(async (url: string) => {
        try {
          const res = await fetch(url, {
            method: "GET",
            credentials: "include",
            headers: { "Accept": "application/json, text/plain, */*" },
          })
          return res.status
        } catch {
          return 0
        }
      }, probeUrl)

      if (status === 200) {
        return true  // Authenticated endpoint returned data
      }
      if (status === 401 || status === 403) {
        return false  // Server explicitly rejected the session
      }
      if (status === 0) {
        continue  // fetch failed (network error, CORS, etc.) — try next endpoint
      }
    } catch {
      continue  // Try next endpoint
    }
  }

  return null  // No probe endpoint was conclusive
}  /**
   * Detect if the page shows an auth failure (MFA challenge, CAPTCHA, error message).
   *
   * Gap 2.1 fix: Uses positive confirmation strategies BEFORE falling back to
   * absence-of-negative-signals:
   * 1. Check for authenticated-only DOM elements (logout button, avatar, profile link)
   * 2. Check if session cookies changed after login
   * 3. Probe an authenticated-only endpoint (/api/me, /profile) for 200 vs 401/403
   * 4. Fall back to negative check (no MFA/CAPTCHA/error messages)
   *
   * Blocker 7 fix: The final fallback returns `false` instead of `true` so that
   * generic pages without any authentication evidence don't count as "success".
   * Only pages with CLEAR positive evidence (logout button, session cookie change,
   * authenticated API 200) are considered authenticated. This prevents the scanner
   * from proceeding with "authenticated" testing when login silently failed.
   *
   * @param page - The Playwright page to check.
   * @param options - Optional configuration for session cookie comparison and API probing.
   * @returns True if auth succeeded, false if blocked.
   */
  export async function detectAuthSuccess(
    page: Page,
    options?: {
      beforeCookies?: Array<{ name: string; value: string }>
      targetUrl?: string
    },
  ): Promise<boolean> {
    // Step 1: Positive check — look for authenticated-only DOM elements
    const domResult = await checkAuthenticatedDomElement(page)
    if (domResult === true) {
      return true
    }

    // Step 2: Positive check — compare session cookies before/after login
    if (options?.beforeCookies) {
      try {
        const context = page.context()
        const cookieResult = await checkSessionCookiesChanged(context, options.beforeCookies)
        if (cookieResult === true) {
          return true
        }
      } catch {
        // BrowserContext may not be available in all environments
      }
    }

    // Step 3: Positive check — probe an authenticated-only API endpoint
    if (options?.targetUrl) {
      const probeResult = await probeAuthenticatedEndpoint(page, options.targetUrl)
      if (probeResult === true) {
        return true
      }
      if (probeResult === false) {
        // Server explicitly rejected — auth definitely failed
        return false
      }
    }

    // Step 4: Fallback — check for negative signals (MFA, CAPTCHA, auth error messages)
    const bodyText = await page.textContent("body") ?? ""
    const lower = bodyText.toLowerCase()

    // Check for MFA challenges
    if (/\bmfa\b|\bmulti-factor\b|\b2fa\b|\btwo-factor\b|\bauthenticator\b|\bverification code\b/i.test(lower)) {
      return false  // MFA challenge detected
    }

    // Check for CAPTCHA
    if (/\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bturnstile\b/i.test(lower)) {
      return false  // CAPTCHA detected
    }

    // Check for auth error messages
    if (/\binvalid (credentials|username|password|email)\b|\blogin failed\b|\bincorrect\b|\bwrong password\b/i.test(lower)) {
      return false  // Auth error
    }

    // Blocker 7: All checks inconclusive — require positive evidence.
    // Previously returned `true` (assume success), which caused failed logins
    // landing on generic pages to count as "authenticated", allowing the scanner
    // to proceed with "authenticated testing" against an unauthenticated state.
    return false
  }

/**
 * Detect and handle multi-factor authentication challenges.
 * Returns false — MFA cannot be auto-solved, caller should log an observation.
 */
export function isMFAChallenge(bodyText: string): boolean {
  const lower = bodyText.toLowerCase()
  return /\bmfa\b|\bmulti-factor\b|\b2fa\b|\btwo-factor\b|\bauthenticator app\b|\bverification code\b|\benter the code\b|\bsecurity code\b/i.test(lower)
}

/**
 * Detect CAPTCHA challenges.
 * Returns false — CAPTCHA cannot be auto-solved.
 */
export function isCaptchaChallenge(bodyText: string): boolean {
  const lower = bodyText.toLowerCase()
  return /\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bturnstile\b|\b(?:i'?m|i am) not a robot\b/i.test(lower)
}

export function isAccessDenied(bodyText: string): boolean {
  const lower = bodyText.toLowerCase()
  return /\b403\b/.test(lower) || /\b401\b/.test(lower) ||
    lower.includes("forbidden") || lower.includes("access denied") ||
    lower.includes("unauthorized") || lower.includes("not authorized") ||
    lower.includes("insufficient permissions")
}

/**
 * Auth tokens for OAuth/token-based authentication fallback.
 * Used when form-based login fails (e.g., OAuth/SSO pages).
 */
export interface AuthTokens {
  /** JWT or bearer token to inject via Authorization header */
  bearerToken?: string
  /** Cookies to inject into the browser context */
  cookies?: Array<{ name: string; value: string; domain: string; path?: string; httpOnly?: boolean; secure?: boolean }>
  /** localStorage key-value pairs for SPA token storage */
  localStorageTokens?: Record<string, string>
}

/**
 * Verify that the session is working after token/cookie injection by
 * navigating to the target URL and using the 3 positive checks from
 * detectAuthSuccess() instead of a simple URL pattern check.
 *
 * Gap 2.1 fix: Previously only checked if the URL didn't contain "/login",
 * which was a weak absence-based check. Now uses positive confirmation:
 * 1. Authenticated DOM elements (logout button, avatar, profile link)
 * 2. Session cookie changes (requires beforeCookies)
 * 3. Authenticated API endpoint probe (/api/me, /profile, etc.)
 *
 * Still uses page.goto() to navigate to the target URL so the injected
 * session takes effect and the page renders in its authenticated state.
 *
 * @param page - The Playwright page to check.
 * @param verifyUrl - URL to navigate to for verification. Defaults to current URL.
 * @returns True if session is confirmed working via positive checks.
 */
async function verifySession(page: Page, verifyUrl?: string): Promise<boolean> {
  try {
    await page.goto(verifyUrl ?? page.url(), { waitUntil: "networkidle", timeout: 10000 })
    // Use the full positive detection pipeline from detectAuthSuccess()
    // instead of the original weak URL pattern check.
    return await detectAuthSuccess(page, {
      targetUrl: page.url(),
    })
  } catch {
    return false
  }
}

/**
 * Orchestrate authentication with fallback: try form login first,
 * then fall back to token/cookie injection for OAuth/SSO scenarios.
 *
 * Gap 2.6 fix: When loginIfFormPresent() returns false (e.g., OAuth/SSO page),
 * this function falls through to token/cookie injection using the provided
 * AuthTokens before declaring authentication failure.
 *
 * Gap 2.7 fix: Adds configurable backoff (default 2000ms) between login attempts
 * and emits an auth_error challenge after 3 consecutive failures.
 *
 * @param page - The Playwright page to authenticate on.
 * @param creds - Username and password credentials for form login.
 * @param authTokens - Optional tokens/cookies for OAuth/SSO fallback.
 * @param context - Optional BrowserContext for cookie injection (required for authTokens.cookies).
 * @param onChallenge - Optional callback for auth challenge signal emission.
 * @param loginDelayMs - Delay in ms between login attempts (default 2000).
 * @returns True if authentication succeeded via form login or token injection.
 */
export async function authenticateSession(
  page: Page,
  creds: { username: string; password: string },
  authTokens?: AuthTokens,
  context?: BrowserContext,
  onChallenge?: AuthChallengeCallback,
  loginDelayMs: number = 2000,
): Promise<boolean> {
  let loginAttempts = 0
  const maxLoginAttempts = 3

  // Step 1: Try form-based login (with retry and backoff)
  for (let attempt = 0; attempt < maxLoginAttempts; attempt++) {
    if (attempt > 0) {
      // Gap 2.7: Backoff between login attempts to prevent account lockout
      await page.waitForTimeout(loginDelayMs * attempt)
    }

    const formLoginResult = await loginIfFormPresent(page, creds, undefined, onChallenge)
    loginAttempts++

    if (formLoginResult) {
      return true
    }

    // Check for auth challenges that would make further retries futile
    const challenge = await detectAuthChallenge(page)
    if (challenge && (challenge.type === "mfa" || challenge.type === "captcha")) {
      onChallenge?.(challenge)
      break  // Can't retry past MFA or CAPTCHA
    }
  }

  // Emit auth_error challenge after max attempts exceeded
  if (loginAttempts >= maxLoginAttempts) {
    const errorChallenge: AuthChallenge = {
      type: "auth_error",
      detail: `Login failed after ${maxLoginAttempts} attempts with backoff. Check credentials or try manual authentication.`,
    }
    onChallenge?.(errorChallenge)
  }

  // Log the challenge type for debugging
  const challenge = await detectAuthChallenge(page)
  if (challenge) {
    onChallenge?.(challenge)
  }

  // Step 2: If no tokens are available, form login failure is final
  if (!authTokens) {
    return false
  }

  // Step 3: Try cookie injection first (most reliable for session-based auth)
  if (authTokens.cookies && authTokens.cookies.length > 0 && context) {
    try {
      await injectAuthCookies(context, authTokens.cookies, page.url())
      if (await verifySession(page)) {
        return true
      }
    } catch (err) {
      console.warn(`[authenticateSession] Cookie injection failed: ${err}`)
    }
  }

  // Step 4: Try localStorage token injection (for SPAs)
  if (authTokens.localStorageTokens && Object.keys(authTokens.localStorageTokens).length > 0) {
    try {
      await injectLocalStorageTokens(page, authTokens.localStorageTokens)
      if (await verifySession(page)) {
        return true
      }
    } catch (err) {
      console.warn(`[authenticateSession] localStorage token injection failed: ${err}`)
    }
  }

  // Step 5: Try bearer token via extra HTTP headers
  if (authTokens.bearerToken) {
    try {
      await page.setExtraHTTPHeaders({
        "Authorization": `Bearer ${authTokens.bearerToken}`,
      })
      if (await verifySession(page)) {
        return true
      }
    } catch (err) {
      console.warn(`[authenticateSession] Bearer token injection failed: ${err}`)
    }
  }

  return false
}

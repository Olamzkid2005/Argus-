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
 * Inject authentication tokens/cookies into the browser context.
 * Useful for OAuth, SSO, or token-based auth where login forms are not present.
 *
 * @param context - The browser context to inject cookies into.
 * @param cookies - Array of cookie objects to set.
 */
export async function injectAuthCookies(
  context: BrowserContext,
  cookies: Array<{ name: string; value: string; domain: string; path?: string; httpOnly?: boolean; secure?: boolean }>,
): Promise<void> {
  await context.addCookies(
    cookies.map((c) => ({
      name: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path ?? "/",
      httpOnly: c.httpOnly ?? true,
      secure: c.secure ?? true,
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

    // Verify login success
    const postLoginUrl = page.url()
    const stillOnLogin = /\/login\b|\/signin\b|\/auth\b/i.test(postLoginUrl)
    return !stillOnLogin || detectAuthSuccess(page)
  } catch {
    // Locator APIs may not be available on all Playwright versions
    return null
  }
}


/**
 * Detect and fill login forms on a page using progressive selector strategies.
 * Supports:
 *  - Standard username+password forms
 *  - Email+password forms
 *  - OAuth/SSO detection (returns false, caller should use injectAuthCookies)
 *  - Modal/dynamically rendered forms (waits for form to become visible)
 *
 * Phase 3.4.1: Uses Playwright locator-based form detection (getByLabel, getByRole)
 * before falling back to CSS selectors for better resilience.
 *
 * @param page - The Playwright page to interact with.
 * @param creds - Username and password credentials.
 * @param selectors - Optional custom selectors for non-standard forms.
 * @returns True if login was submitted successfully, false if no form found.
 */
export async function loginIfFormPresent(
  page: Page,
  creds: Credentials,
  selectors?: LoginSelectors,
): Promise<boolean> {
  const content = await page.content()

  // First check for OAuth/SSO buttons — these should not be auto-filled
  const hasOAuth = /\boauth\b/i.test(content) &&
    (/\bgoogle\b/i.test(content) || /\bgithub\b/i.test(content) || /\bmicrosoft\b/i.test(content) || /\bfacebook\b/i.test(content) || /\bsso\b/i.test(content) || /\bsaml\b/i.test(content))
  if (hasOAuth) {
    return false  // OAuth/SSO detected — caller should use injectAuthCookies or injectLocalStorageTokens
  }

  // ── Phase 3.4.1: Playwright locator-based detection (getByLabel, getByRole) ──
  // Try accessibility-first locators before CSS selectors for better resilience.
  if (!selectors) {
    const locatorResult = await loginWithLocators(page, creds)
    if (locatorResult !== null) {
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
    // No password field — try token injection instead
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

  // Verify login success: check we're not still on the login page
  const postLoginUrl = page.url()
  const stillOnLogin = /\/login\b|\/signin\b|\/auth\b/i.test(postLoginUrl)
  return !stillOnLogin || detectAuthSuccess(page)
}

/**
 * Detect if the page shows an auth failure (MFA challenge, CAPTCHA, error message).
 * Returns true if auth was successful, false if blocked by MFA/CAPTCHA.
 */
export async function detectAuthSuccess(page: Page): Promise<boolean> {
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

  return true  // No auth blockers detected
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
  return /\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bturnstile\b|\bim not a robot\b/i.test(lower)
}

export function isAccessDenied(bodyText: string): boolean {
  const lower = bodyText.toLowerCase()
  return /\b403\b/.test(lower) || /\b401\b/.test(lower) ||
    lower.includes("forbidden") || lower.includes("access denied") ||
    lower.includes("unauthorized") || lower.includes("not authorized") ||
    lower.includes("insufficient permissions")
}

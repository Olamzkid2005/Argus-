import type { Page } from "playwright"

export interface Credentials {
  username: string
  password: string
}

export async function loginIfFormPresent(page: Page, creds: Credentials): Promise<boolean> {
  const content = await page.content()
  // Use case-insensitive word-boundary regex to avoid:
  // - Misses: "Password", "LOGIN", "Sign In", "Log In"
  // - False positives: CSS classes like "password-field", "login-btn"
  // Word boundary (\b) ensures we match the word, not substrings.
  const hasLoginForm = /\bpassword\b/i.test(content) && (
    /\blogin\b/i.test(content) ||
    /\bsign\s*in\b/i.test(content) ||
    /\blog\s*in\b/i.test(content) ||
    /\busername\b/i.test(content) ||
    /\bemail\b/i.test(content)
  )
  if (!hasLoginForm) return false

  const passwordFields = await page.locator("input[type=password]").count()
  if (passwordFields === 0) return false

  const usernameInput = page.locator("input[type=text], input[name=username], input[name=email], input[type=email]").first()
  const passwordInput = page.locator("input[type=password]").first()
  const submitButton = page.locator("button[type=submit], input[type=submit]").first()

  if (await usernameInput.isVisible()) await usernameInput.fill(creds.username)
  let submitted = false
  if (await passwordInput.isVisible()) {
    await passwordInput.fill(creds.password)
    await passwordInput.press("Enter")
    submitted = true
  } else if (await submitButton.isVisible()) {
    await submitButton.click()
    submitted = true
  }

  if (!submitted) return false

  await page.waitForLoadState("networkidle", { timeout: 30000 })
  return true
}

export function isAccessDenied(bodyText: string): boolean {
  const lower = bodyText.toLowerCase()
  return /\b403\b/.test(lower) || /\b401\b/.test(lower) ||
    lower.includes("forbidden") || lower.includes("access denied") ||
    lower.includes("unauthorized") || lower.includes("not authorized") ||
    lower.includes("insufficient permissions")
}

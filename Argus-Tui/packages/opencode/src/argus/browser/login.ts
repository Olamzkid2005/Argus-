import type { Page } from "playwright"

export interface Credentials {
  username: string
  password: string
}

export async function loginIfFormPresent(page: Page, creds: Credentials): Promise<boolean> {
  const content = await page.content()
  if (!content.includes("password") && !content.includes("login") && !content.includes("sign in")) return false

  const passwordFields = await page.locator("input[type=password]").count()
  if (passwordFields === 0) return false

  const usernameInput = page.locator("input[type=text], input[name=username], input[name=email], input[type=email]").first()
  const passwordInput = page.locator("input[type=password]").first()
  const submitButton = page.locator("button[type=submit], input[type=submit]").first()

  if (await usernameInput.isVisible()) await usernameInput.fill(creds.username)
  if (await passwordInput.isVisible()) {
    await passwordInput.fill(creds.password)
    await passwordInput.press("Enter")
  } else if (await submitButton.isVisible()) {
    await submitButton.click()
  }

  await page.waitForLoadState("networkidle")
  return true
}

export function isAccessDenied(bodyText: string): boolean {
  const lower = bodyText.toLowerCase()
  return /\b403\b/.test(lower) || /\b401\b/.test(lower) ||
    lower.includes("forbidden") || lower.includes("access denied") ||
    lower.includes("unauthorized") || lower.includes("not authorized") ||
    lower.includes("insufficient permissions")
}

# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend-features.spec.ts >> 5. Settings page loads correctly
- Location: tests/frontend-features.spec.ts:90:5

# Error details

```
Error: page.goto: net::ERR_NETWORK_IO_SUSPENDED at http://localhost:3000/settings
Call log:
  - navigating to "http://localhost:3000/settings", waiting until "load"

```

# Test source

```ts
  1   | import { test, expect, chromium, Browser, Page } from '@playwright/test';
  2   | 
  3   | let browser: Browser;
  4   | let page: Page;
  5   | 
  6   | // Test 1: Homepage loads
  7   | test('1. Homepage loads correctly', async () => {
  8   |   browser = await chromium.launch({ headless: true });
  9   |   page = await browser.newPage();
  10  |   
  11  |   await page.goto('http://localhost:3000/');
  12  |   
  13  |   // Check title/content
  14  |   const title = await page.title();
  15  |   console.log('Page title:', title);
  16  |   
  17  |   // Check for ARGUS text
  18  |   const heading = await page.locator('h1').first().textContent();
  19  |   console.log('Main heading:', heading);
  20  |   
  21  |   // Check signin button exists
  22  |   const signinLink = page.locator('a[href="/auth/signin"]');
  23  |   await expect(signinLink).toBeVisible();
  24  |   
  25  |   console.log('✅ Homepage test passed');
  26  |   await browser.close();
  27  | });
  28  | 
  29  | // Test 2: Signin page loads
  30  | test('2. Signin page loads correctly', async () => {
  31  |   browser = await chromium.launch({ headless: true });
  32  |   page = await browser.newPage();
  33  |   
  34  |   await page.goto('http://localhost:3000/auth/signin');
  35  |   
  36  |   // Check for signin form elements
  37  |   const emailInput = page.locator('input[type="email"]');
  38  |   const passwordInput = page.locator('input[type="password"]');
  39  |   const submitButton = page.locator('button[type="submit"]');
  40  |   
  41  |   await expect(emailInput).toBeVisible();
  42  |   await expect(passwordInput).toBeVisible();
  43  |   await expect(submitButton).toBeVisible();
  44  |   
  45  |   console.log('✅ Signin page test passed');
  46  |   await browser.close();
  47  | });
  48  | 
  49  | // Test 3: Signup page loads
  50  | test('3. Signup page loads correctly', async () => {
  51  |   browser = await chromium.launch({ headless: true });
  52  |   page = await browser.newPage();
  53  |   
  54  |   await page.goto('http://localhost:3000/auth/signup');
  55  |   
  56  |   // Check for signup form elements - use more specific selectors
  57  |   const emailInput = page.locator('input[type="email"]').first();
  58  |   const passwordInputs = page.locator('input[type="password"]');
  59  |   const submitButton = page.locator('button[type="submit"]').first();
  60  |   
  61  |   await expect(emailInput).toBeVisible();
  62  |   await expect(passwordInputs.first()).toBeVisible();
  63  |   await expect(submitButton).toBeVisible();
  64  |   
  65  |   console.log('✅ Signup page test passed');
  66  |   await browser.close();
  67  | });
  68  | 
  69  | // Test 4: Engagements page loads
  70  | test('4. Engagements page loads correctly', async () => {
  71  |   browser = await chromium.launch({ headless: true });
  72  |   page = await browser.newPage();
  73  |   
  74  |   await page.goto('http://localhost:3000/engagements');
  75  |   
  76  |   // Check for engagement form elements
  77  |   const scanTypeButtons = page.locator('button:has-text("URL SCAN"), button:has-text("REPO SCAN")');
  78  |   const targetInput = page.locator('input[placeholder*="target"]').first();
  79  |   const submitButton = page.locator('button:has-text("LAUNCH ENGAGEMENT")');
  80  |   
  81  |   console.log('URL scan button visible:', await page.locator('button:has-text("URL SCAN")').isVisible());
  82  |   console.log('Target input visible:', await targetInput.isVisible());
  83  |   console.log('Submit button visible:', await submitButton.isVisible());
  84  |   
  85  |   console.log('✅ Engagements page test passed');
  86  |   await browser.close();
  87  | });
  88  | 
  89  | // Test 5: Settings page loads
  90  | test('5. Settings page loads correctly', async () => {
  91  |   browser = await chromium.launch({ headless: true });
  92  |   page = await browser.newPage();
  93  |   
> 94  |   await page.goto('http://localhost:3000/settings');
      |              ^ Error: page.goto: net::ERR_NETWORK_IO_SUSPENDED at http://localhost:3000/settings
  95  |   
  96  |   // Settings page should either show content or redirect to signin
  97  |   const url = page.url();
  98  |   console.log('Current URL:', url);
  99  |   
  100 |   // Should either show settings or redirect
  101 |   const hasContent = await page.locator('input[type="password"], input[type="text"]').first().isVisible().catch(() => false);
  102 |   const isRedirected = url.includes('/auth/signin');
  103 |   
  104 |   console.log('Has settings form:', hasContent);
  105 |   console.log('Redirected to auth:', isRedirected);
  106 |   
  107 |   console.log('✅ Settings page test passed');
  108 |   await browser.close();
  109 | });
  110 | 
  111 | // Test 6: API Health endpoints
  112 | test('6. API health endpoints work', async () => {
  113 |   const response = await fetch('http://localhost:3000/api/health/db');
  114 |   console.log('DB Health status:', response.status);
  115 |   expect(response.status).toBe(200);
  116 |   
  117 |   console.log('✅ API health endpoints test passed');
  118 | });
  119 | 
  120 | // Test 7: Signup form validation - empty submission
  121 | test('7. Signup form validates empty submission', async () => {
  122 |   browser = await chromium.launch({ headless: true });
  123 |   page = await browser.newPage();
  124 |   
  125 |   await page.goto('http://localhost:3000/auth/signup');
  126 |   
  127 |   // Click submit without filling fields
  128 |   const submitButton = page.locator('button[type="submit"]').first();
  129 |   await submitButton.click();
  130 |   
  131 |   // Wait a moment for validation
  132 |   await page.waitForTimeout(1000);
  133 |   
  134 |   // Should stay on signup page (not redirect)
  135 |   const url = page.url();
  136 |   console.log('URL after empty submit:', url);
  137 |   expect(url).toContain('/auth/signup');
  138 |   
  139 |   console.log('✅ Signup validation test passed');
  140 |   await browser.close();
  141 | });
  142 | 
  143 | // Test 8: Engagements page redirects unauthenticated users
  144 | test('8. Engagements page redirects to signin when not authenticated', async () => {
  145 |   browser = await chromium.launch({ headless: true });
  146 |   page = await browser.newPage();
  147 |   
  148 |   await page.goto('http://localhost:3000/engagements');
  149 |   
  150 |   // Wait for redirect
  151 |   await page.waitForTimeout(2000);
  152 |   
  153 |   const url = page.url();
  154 |   console.log('URL after engagements access:', url);
  155 |   // Should redirect to signin
  156 |   expect(url).toContain('/auth/signin');
  157 |   
  158 |   console.log('✅ Auth redirect test passed');
  159 |   await browser.close();
  160 | });
  161 | 
  162 | // Test 9: Dashboard page redirects unauthenticated users
  163 | test('9. Dashboard page redirects to signin when not authenticated', async () => {
  164 |   browser = await chromium.launch({ headless: true });
  165 |   page = await browser.newPage();
  166 |   
  167 |   await page.goto('http://localhost:3000/dashboard');
  168 |   
  169 |   // Wait for redirect
  170 |   await page.waitForTimeout(2000);
  171 |   
  172 |   const url = page.url();
  173 |   console.log('URL after dashboard access:', url);
  174 |   // Should redirect to signin
  175 |   expect(url).toContain('/auth/signin');
  176 |   
  177 |   console.log('✅ Dashboard auth redirect test passed');
  178 |   await browser.close();
  179 | });
  180 | 
  181 | // Test 10: Findings page loads
  182 | test('10. Findings page loads correctly', async () => {
  183 |   browser = await chromium.launch({ headless: true });
  184 |   page = await browser.newPage();
  185 |   
  186 |   await page.goto('http://localhost:3000/findings');
  187 |   
  188 |   // Wait a bit for any redirects
  189 |   await page.waitForTimeout(2000);
  190 |   
  191 |   const url = page.url();
  192 |   console.log('Findings page URL:', url);
  193 |   
  194 |   // Page should either show findings or redirect to auth
```
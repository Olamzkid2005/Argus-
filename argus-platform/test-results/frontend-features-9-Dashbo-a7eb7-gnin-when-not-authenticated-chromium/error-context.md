# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend-features.spec.ts >> 9. Dashboard page redirects to signin when not authenticated
- Location: tests/frontend-features.spec.ts:163:5

# Error details

```
Error: expect(received).toContain(expected) // indexOf

Expected substring: "/auth/signin"
Received string:    "http://localhost:3000/dashboard"
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e4]:
    - heading "404" [level=1] [ref=e5]
    - heading "This page could not be found." [level=2] [ref=e7]
  - alert [ref=e8]
```

# Test source

```ts
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
  94  |   await page.goto('http://localhost:3000/settings');
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
> 175 |   expect(url).toContain('/auth/signin');
      |               ^ Error: expect(received).toContain(expected) // indexOf
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
  195 |   const isAuthPage = url.includes('/auth/');
  196 |   console.log('Redirected to auth:', isAuthPage);
  197 |   
  198 |   console.log('✅ Findings page test passed');
  199 |   await browser.close();
  200 | });
  201 | 
  202 | // Test 11: Check NextAuth is configured
  203 | test('11. NextAuth is configured correctly', async () => {
  204 |   const response = await fetch('http://localhost:3000/api/auth/providers');
  205 |   const providers = await response.json();
  206 |   console.log('Auth providers:', Object.keys(providers));
  207 |   
  208 |   expect(Object.keys(providers).length).toBeGreaterThan(0);
  209 |   
  210 |   console.log('✅ NextAuth configuration test passed');
  211 | });
  212 | 
  213 | // Test 12: Engagement create API requires auth
  214 | test('12. Engagement create API rejects unauthenticated requests', async () => {
  215 |   const response = await fetch('http://localhost:3000/api/engagement/create', {
  216 |     method: 'POST',
  217 |     headers: { 'Content-Type': 'application/json' },
  218 |     body: JSON.stringify({
  219 |       targetUrl: 'https://example.com',
  220 |       scanType: 'url',
  221 |       authorization: 'AUTHORIZED OPERATIONAL SCAN',
  222 |       authorizedScope: { domains: ['example.com'], ipRanges: [] }
  223 |     })
  224 |   });
  225 |   
  226 |   console.log('Create engagement status:', response.status);
  227 |   expect(response.status).toBe(401);
  228 |   
  229 |   console.log('✅ API auth requirement test passed');
  230 | });
  231 | 
  232 | // Test 13: Signup with credentials works
  233 | test('13. User can signup with email/password', async () => {
  234 |   test.setTimeout(60000);
  235 |   browser = await chromium.launch({ headless: true });
  236 |   page = await browser.newPage();
  237 |   
  238 |   await page.goto('http://localhost:3000/auth/signup');
  239 |   
  240 |   // Fill in signup form - email, name (org name), password, confirm password
  241 |   const emailInput = page.locator('input[type="email"]').first();
  242 |   const passwordInputs = page.locator('input[type="password"]');
  243 |   const nameInputs = page.locator('input[name="name"]');
  244 |   
  245 |   const testEmail = `testuser${Date.now()}@example.com`;
  246 |   const testPassword = 'TestPassword123!';
  247 |   const testOrg = 'Test Organization';
  248 |   
  249 |   await emailInput.fill(testEmail);
  250 |   
  251 |   // Try to find and fill org name or name field
  252 |   if (await nameInputs.count() > 0) {
  253 |     await nameInputs.first().fill(testOrg);
  254 |   }
  255 |   
  256 |   await passwordInputs.first().fill(testPassword);
  257 |   if (await passwordInputs.count() > 1) {
  258 |     await passwordInputs.nth(1).fill(testPassword);
  259 |   }
  260 |   
  261 |   // Submit form
  262 |   await page.locator('button[type="submit"]').first().click();
  263 |   
  264 |   // Wait for response - increased timeout for signup
  265 |   await page.waitForTimeout(5000);
  266 |   
  267 |   const url = page.url();
  268 |   console.log('URL after signup:', url);
  269 |   
  270 |   // Should either succeed or show error
  271 |   const hasError = await page.locator('text=error, text=Error, text=failed').first().isVisible().catch(() => false);
  272 |   console.log('Has error message:', hasError);
  273 |   
  274 |   console.log('✅ Signup test passed');
  275 |   await browser.close();
```
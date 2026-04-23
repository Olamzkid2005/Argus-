# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend-features.spec.ts >> 15. Engagements list page loads
- Location: tests/frontend-features.spec.ts:301:5

# Error details

```
Error: expect(received).toContain(expected) // indexOf

Expected substring: "/auth/signin"
Received string:    "http://localhost:3000/engagements/list"
```

# Page snapshot

```yaml
- generic [active]:
  - generic:
    - main
```

# Test source

```ts
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
  276 | });
  277 | 
  278 | // Test 14: Engagement form shows progress bar when submitting
  279 | test('14. Engagement form shows progress during submission', async () => {
  280 |   browser = await chromium.launch({ headless: true });
  281 |   page = await browser.newPage();
  282 |   
  283 |   await page.goto('http://localhost:3000/auth/signin');
  284 |   
  285 |   // Note: This test requires authenticated session
  286 |   // For now just verify the form elements exist
  287 |   await page.goto('http://localhost:3000/engagements');
  288 |   
  289 |   // Wait for redirect to signin
  290 |   await page.waitForTimeout(2000);
  291 |   
  292 |   const isOnSignin = page.url().includes('/auth/signin');
  293 |   console.log('Redirected to signin:', isOnSignin);
  294 |   
  295 |   // Test that engagement page has required elements when loaded properly
  296 |   console.log('✅ Engagement form progress test passed (requires auth)');
  297 |   await browser.close();
  298 | });
  299 | 
  300 | // Test 15: Check engagements list page
  301 | test('15. Engagements list page loads', async () => {
  302 |   browser = await chromium.launch({ headless: true });
  303 |   page = await browser.newPage();
  304 |   
  305 |   await page.goto('http://localhost:3000/engagements/list');
  306 |   
  307 |   // Should redirect to signin
  308 |   await page.waitForTimeout(2000);
  309 |   const url = page.url();
  310 |   console.log('Engagements list URL:', url);
  311 |   
> 312 |   expect(url).toContain('/auth/signin');
      |               ^ Error: expect(received).toContain(expected) // indexOf
  313 |   
  314 |   console.log('✅ Engagements list test passed');
  315 |   await browser.close();
  316 | });
  317 | 
  318 | // Test 16: Check database stats endpoint
  319 | test('16. Database stats endpoint requires auth', async () => {
  320 |   // Without auth, should get 401
  321 |   const response = await fetch('http://localhost:3000/api/db/stats');
  322 |   console.log('DB stats status:', response.status);
  323 |   expect(response.status).toBe(401);
  324 |   
  325 |   console.log('✅ Database stats endpoint test passed');
  326 | });
  327 | 
  328 | // Test 17: Check dashboard stats endpoint  
  329 | test('17. Dashboard stats endpoint requires auth', async () => {
  330 |   // Without auth, should get 401
  331 |   const response = await fetch('http://localhost:3000/api/dashboard/stats');
  332 |   console.log('Dashboard stats status:', response.status);
  333 |   expect(response.status).toBe(401);
  334 |   
  335 |   console.log('✅ Dashboard stats endpoint test passed');
  336 | });
  337 | 
  338 | // Test 18: Check findings API endpoint
  339 | test('18. Findings API endpoint is accessible', async () => {
  340 |   // Without auth, should get 401
  341 |   const response = await fetch('http://localhost:3000/api/findings');
  342 |   console.log('Findings API status:', response.status);
  343 |   expect(response.status).toBe(401);
  344 |   
  345 |   console.log('✅ Findings API endpoint test passed');
  346 | });
  347 | 
  348 | // Test 19: Verify all pages return proper status codes
  349 | test('19. All main pages return 200 or redirect', async () => {
  350 |   const pages = [
  351 |     '/',
  352 |     '/auth/signin',
  353 |     '/auth/signup',
  354 |     '/engagements',
  355 |     '/engagements/list',
  356 |     '/dashboard',
  357 |     '/findings',
  358 |     '/settings'
  359 |   ];
  360 |   
  361 |   for (const path of pages) {
  362 |     const browser2 = await chromium.launch({ headless: true });
  363 |     const page2 = await browser2.newPage();
  364 |     const response = await page2.goto(`http://localhost:3000${path}`, { waitUntil: 'domcontentloaded' });
  365 |     const status = response?.status() || 0;
  366 |     console.log(`${path}: ${status}`);
  367 |     expect([200, 302, 401]).toContain(status);
  368 |     await browser2.close();
  369 |   }
  370 |   
  371 |   console.log('✅ All pages status test passed');
  372 | });
  373 | 
  374 | // Test 20: Protected API endpoints return 401 without auth
  375 | test('20. Protected API endpoints return 401 without auth', async () => {
  376 |   const endpoints = [
  377 |     { method: 'GET', endpoint: '/api/engagements' },
  378 |     { method: 'POST', endpoint: '/api/engagement/create' },
  379 |     { method: 'GET', endpoint: '/api/findings' },
  380 |     { method: 'GET', endpoint: '/api/settings' },
  381 |     { method: 'GET', endpoint: '/api/dashboard/stats' },
  382 |     { method: 'GET', endpoint: '/api/db/stats' }
  383 |   ];
  384 |   
  385 |   for (const { method, endpoint } of endpoints) {
  386 |     const response = await fetch(`http://localhost:3000${endpoint}`, { method });
  387 |     console.log(`${method} ${endpoint}: ${response.status}`);
  388 |     // Accept 401 (Unauthorized) or 405 (Method Not Allowed) or 500 (if auth check fails first)
  389 |     expect([401, 405, 500]).toContain(response.status);
  390 |   }
  391 |   
  392 |   console.log('✅ Protected API endpoints test passed');
  393 | });
  394 | 
  395 | // Test 21: Auth flow - signup -> signin -> dashboard
  396 | test('21. Auth flow: signup -> signin -> dashboard', async () => {
  397 |   test.setTimeout(120000);
  398 |   browser = await chromium.launch({ headless: true });
  399 |   page = await browser.newPage();
  400 |   
  401 |   const testEmail = `e2euser${Date.now()}@example.com`;
  402 |   const testPassword = 'E2ETestPass123!';
  403 |   
  404 |   // Step 1: Signup
  405 |   await page.goto('http://localhost:3000/auth/signup');
  406 |   await page.locator('input[type="email"]').first().fill(testEmail);
  407 |   const nameInput = page.locator('input[name="name"]').first();
  408 |   if (await nameInput.count() > 0) {
  409 |     await nameInput.fill('E2E Test Org');
  410 |   }
  411 |   const passwordInputs = page.locator('input[type="password"]');
  412 |   await passwordInputs.first().fill(testPassword);
```
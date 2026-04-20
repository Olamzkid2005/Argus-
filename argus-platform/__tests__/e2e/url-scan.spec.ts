import { test, expect } from '@playwright/test';

test.describe('URL Scan Engagement', () => {
  const testUser = {
    email: `urlscan-${Date.now()}@test.com`,
    password: 'TestPass123!',
    orgName: 'URL Scan Test Org',
  };

  test('should signup and create URL scan for security.avnify.com', async ({ page }) => {
    // Step 1: Sign up new user
    console.log('\n=== Creating new user ===');
    await page.goto('http://localhost:3000/auth/signup');
    
    await page.fill('#email', testUser.email);
    await page.fill('#password', testUser.password);
    await page.fill('#passwordConfirm', testUser.password);
    await page.fill('#orgName', testUser.orgName);
    await page.click('button[type="submit"]');
    
    await page.waitForURL(/.*\/auth\/signin.*/, { timeout: 15000 });
    console.log('User created, redirected to signin');

    // Step 2: Sign in
    console.log('\n=== Signing in ===');
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.click('button[type="submit"]');
    
    await page.waitForURL(/.*\/dashboard.*/, { timeout: 15000 });
    console.log('Signed in');

    // Step 3: Create URL scan
    console.log('\n=== Creating URL scan engagement ===');
    const targetUrl = 'https://security.avnify.com/';
    
    await page.goto('http://localhost:3000/engagements');
    await page.waitForLoadState('networkidle');
    
    // Wait for the page to fully load
    await page.waitForTimeout(2000);
    
    // Make sure Web App is selected
    const webAppButton = page.locator('button:has-text("Web App")');
    if (await webAppButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await webAppButton.click();
      await page.waitForTimeout(500);
    }
    
    // Find the target input - try different selectors
    const targetInput = page.locator('input[placeholder*="https"]');
    if (!await targetInput.isVisible().catch(() => false)) {
      // Try generic input
      await page.locator('input[type="text"]').first().fill(targetUrl);
    } else {
      await targetInput.fill(targetUrl);
    }
    
    // Click the start scan button
    await page.click('button:has-text("Start Scan")');
    
    // Wait for result
    await page.waitForTimeout(5000);
    
    const currentUrl = page.url();
    console.log('URL after scan submission:', currentUrl);
    
    // Get any success/error messages
    const bodyText = await page.textContent('body');
    console.log('Page status:', bodyText?.substring(0, 300));
    
    console.log('\n=== URL Scan Engagement Created ===');
    console.log('Target URL:', targetUrl);
  });
});
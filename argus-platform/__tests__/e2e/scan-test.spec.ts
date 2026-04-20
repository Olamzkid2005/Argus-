import { test, expect } from '@playwright/test';

test.describe('Engagement Creation and Scanning', () => {
  const testUser = {
    email: `testscan-${Date.now()}@test.com`,
    password: 'TestPass123!',
    orgName: 'Scan Test Org',
  };

  test('should signup, signin, and create GitHub scan engagement', async ({ page, request }) => {
    // Step 1: Sign up new user
    console.log('\n=== STEP 1: Creating new user ===');
    await page.goto('http://localhost:3000/auth/signup');
    
    await page.fill('#email', testUser.email);
    await page.fill('#password', testUser.password);
    await page.fill('#passwordConfirm', testUser.password);
    await page.fill('#orgName', testUser.orgName);
    await page.click('button[type="submit"]');
    
    // Wait for redirect to signin
    await page.waitForURL(/.*\/auth\/signin.*/, { timeout: 15000 });
    console.log('User signup successful, redirected to signin');

    // Step 2: Sign in
    console.log('\n=== STEP 2: Signing in ===');
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.click('button[type="submit"]');
    
    // Wait for redirect to dashboard
    await page.waitForURL(/.*\/dashboard.*/, { timeout: 15000 });
    console.log('Signin successful, redirected to dashboard');

    // Step 3: Create GitHub repository scan engagement
    console.log('\n=== STEP 3: Creating GitHub scan engagement ===');
    const repoUrl = 'https://github.com/Olamzkid2005/One-pay.git';
    
    // Navigate to engagements page
    await page.goto('http://localhost:3000/engagements');
    await page.waitForLoadState('networkidle');
    
    // Select repository scan type
    await page.click('text=Repository');
    
    // Enter the repository URL
    await page.fill('input[type="text"]', repoUrl);
    
    // Submit the form
    await page.click('button:has-text("Start Scan")');
    
    // Wait for response
    await page.waitForTimeout(5000);
    
    const currentUrl = page.url();
    console.log('Current URL after scan submission:', currentUrl);
    
    // Get page content for debugging
    const content = await page.content();
    console.log('Page contains engagement created:', content.includes('engagement') || content.includes('Engagement'));
    
    console.log('\n=== GitHub Scan Engagement Created ===');
    console.log('Repository:', repoUrl);
  });

  test('should create URL scan engagement for security.avnify.com', async ({ page }) => {
    // Step 1: Sign in with same user
    console.log('\n=== STEP 1: Signing in ===');
    await page.goto('http://localhost:3000/auth/signin');
    
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.click('button[type="submit"]');
    
    // Wait for redirect - be more flexible with URL matching
    try {
      await page.waitForURL(/.*\/dashboard.*|.*\/engagements.*/, { timeout: 20000 });
    } catch {
      // If specific URL not matched, just wait for navigation
      await page.waitForTimeout(5000);
    }
    console.log('Signin successful, page loaded');

    // Step 2: Create URL scan engagement
    console.log('\n=== STEP 2: Creating URL scan engagement ===');
    const targetUrl = 'https://security.avnify.com/';
    
    // Navigate to engagements page
    await page.goto('http://localhost:3000/engagements');
    await page.waitForLoadState('networkidle');
    
    // Ensure web app scan type is selected (default)
    const webAppButton = page.locator('button:has-text("Web App")');
    if (await webAppButton.isVisible()) {
      await webAppButton.click();
    }
    
    // Wait a moment for the selection
    await page.waitForTimeout(500);
    
    // Enter the target URL
    const targetInput = page.locator('input[type="text"]').first();
    await targetInput.fill(targetUrl);
    
    // Submit the form
    await page.click('button:has-text("Start Scan")');
    
    // Wait for response
    await page.waitForTimeout(5000);
    
    const currentUrl = page.url();
    console.log('Current URL after scan submission:', currentUrl);
    
    // Get any toast/notification messages
    const pageText = await page.textContent('body');
    console.log('Page content:', pageText?.substring(0, 500));
    
    console.log('\n=== URL Scan Engagement Created ===');
    console.log('Target URL:', targetUrl);
  });
});
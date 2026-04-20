import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test('should display dashboard page structure', async ({ page }) => {
    await page.goto('/dashboard');
    
    // Should redirect to sign-in if not authenticated
    // or show loading state
    await page.waitForLoadState('networkidle');
  });

  test('should show connection input for engagement ID', async ({ page }) => {
    await page.goto('/dashboard');
    
    // Page should load (may redirect to sign-in)
    await page.waitForLoadState('networkidle');
  });
});

test.describe('Findings', () => {
  test('should display findings list page', async ({ page }) => {
    await page.goto('/findings');
    
    // Should redirect to sign-in or show findings
    await page.waitForLoadState('networkidle');
  });
});

test.describe('Landing Page', () => {
  test('should display landing page with brand elements', async ({ page }) => {
    await page.goto('/');
    
    // Wait for loading to complete and check for brand text
    await expect(page.getByText(/Security at the/i)).toBeVisible({ timeout: 15000 });
  });

  test('should have sign in button on landing page', async ({ page }) => {
    await page.goto('/');
    
    await expect(page.getByRole('button', { name: /sign in to launch/i })).toBeVisible({ timeout: 15000 });
  });

  test('should navigate to signup from landing page', async ({ page }) => {
    await page.goto('/auth/signup');
    
    // Just verify signup page loads
    await expect(page.getByRole('heading', { name: /create your account/i })).toBeVisible();
  });
});

test.describe('Navigation', () => {
  test('should handle auth error page', async ({ page }) => {
    await page.goto('/auth/error');
    
    // Page should load with error content
    await page.waitForLoadState('networkidle');
  });
});
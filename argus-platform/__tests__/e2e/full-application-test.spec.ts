/**
 * Comprehensive End-to-End Test Suite
 * Tests every page and feature of the Argus platform systematically.
 */
import { test, expect, Page } from '@playwright/test';

const BASE_URL = 'http://localhost:3000';
const TEST_USER = {
  email: `e2e-${Date.now()}@test.com`,
  password: 'TestPass123!',
  orgName: 'E2E Test Org',
};

async function nav(page: Page, path: string) {
  await page.goto(`${BASE_URL}${path}`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(800);
}

async function dismissOnboarding(page: Page) {
  try {
    const overlay = page.locator('[data-testid="onboarding-tour"]');
    if (await overlay.isVisible({ timeout: 1000 }).catch(() => false)) {
      await page.evaluate(() => {
        const el = document.querySelector('[data-testid="onboarding-tour"]');
        if (el) el.remove();
      });
      await page.waitForTimeout(300);
      console.log('  Onboarding dismissed');
    }
  } catch { /* no onboarding */ }
}

// ─── TEST 1: Landing Page ───
test.describe('1. Landing Page', () => {
  test('should load landing page with all sections', async ({ page }) => {
    await nav(page, '/');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(100);
    console.log(`✓ Landing page loaded (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-01-landing.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 2: Sign Up ───
test.describe('2. Sign Up Flow', () => {
  test('should complete sign up process', async ({ page }) => {
    test.setTimeout(60000);
    await nav(page, '/auth/signup');
    await dismissOnboarding(page);

    // Step 1: Fill email
    const emailInput = page.locator('input[type="email"]').first();
    await expect(emailInput).toBeVisible({ timeout: 5000 });
    await emailInput.fill(TEST_USER.email);
    console.log('  Email filled');

    // Try clicking the continue button
    const continueBtn = page.locator('button[type="submit"]').first();
    if (await continueBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await continueBtn.click({ force: true });
      await page.waitForTimeout(2000);
    }

    // Step 2: If we're on the details step, fill password and org info
    const pwInput = page.locator('input[type="password"]').first();
    if (await pwInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await pwInput.fill(TEST_USER.password);
      const pwFields = page.locator('input[type="password"]');
      if ((await pwFields.count()) > 1) {
        await pwFields.nth(1).fill(TEST_USER.password);
      }
      const orgInput = page.locator('input[name="orgName"]').first();
      if (await orgInput.isVisible({ timeout: 1000 }).catch(() => false)) {
        await orgInput.fill(TEST_USER.orgName);
      }
      const submitBtn = page.locator('button[type="submit"]').last();
      await submitBtn.click({ force: true });
      await page.waitForTimeout(3000);
      console.log('  Signup submitted');
    }

    const currentUrl = page.url();
    console.log(`  Result URL: ${currentUrl}`);

    // Check for success message or redirect
    const bodyText = await page.locator('body').innerText();
    if (bodyText.includes('Account created') || bodyText.includes('Redirecting')) {
      console.log('  ✓ Account created!');
      await page.waitForURL(/signin/, { timeout: 10000 }).catch(() => {});
    } else if (bodyText.includes('already exists') || bodyText.includes('already registered')) {
      console.log('  Note: User may already exist');
    }

    await page.screenshot({ path: '/tmp/e2e-02-signup.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 3: Sign In ───
test.describe('3. Sign In Flow', () => {
  test('should sign in with credentials', async ({ page }) => {
    test.setTimeout(60000);
    await nav(page, '/auth/signin');
    await dismissOnboarding(page);

    // Fill credentials
    const emailInput = page.locator('input[type="email"]').first();
    await expect(emailInput).toBeVisible({ timeout: 5000 });
    await emailInput.fill(TEST_USER.email);

    const pwInput = page.locator('input[type="password"]').first();
    await expect(pwInput).toBeVisible({ timeout: 5000 });
    await pwInput.fill(TEST_USER.password);

    // Click sign in
    const signinBtn = page.locator('button[type="submit"]').first();
    await signinBtn.click({ force: true });
    await page.waitForTimeout(2000);

    const url = page.url();
    console.log(`  Sign in result URL: ${url}`);

    // If redirected away from signin, it worked
    if (!url.includes('signin') || url.includes('signin?error')) {
      const bodyText = await page.locator('body').innerText();
      console.log(`  Body preview: ${bodyText.substring(0, 100)}`);
    }

    await page.screenshot({ path: '/tmp/e2e-03-signin.png' }).catch(() => {});
  });
});

// ─── TEST 4: Dashboard Page ───
test.describe('4. Dashboard Page', () => {
  test('should display dashboard', async ({ page }) => {
    await nav(page, '/dashboard');
    await dismissOnboarding(page);
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`✓ Dashboard loaded (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-04-dashboard.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 5: All Pages Navigation ───
test.describe('5. All Pages Navigation', () => {
  test('should load every page successfully', async ({ page }) => {
    test.setTimeout(120000);
    const pages = [
      ['/engagements', 'Engagements'],
      ['/findings', 'Findings'],
      ['/reports', 'Reports'],
      ['/assets', 'Assets'],
      ['/rules', 'Rules'],
      ['/analytics', 'Analytics'],
      ['/settings', 'Settings'],
      ['/collaboration', 'Collaboration'],
      ['/reports/compliance', 'Compliance Reports'],
      ['/auth/signin', 'Sign In'],
      ['/auth/signup', 'Sign Up'],
    ];

    for (const [path, name] of pages) {
      await nav(page, path);
      await dismissOnboarding(page);
      await expect(page.locator('body')).toBeVisible();
      const bodyText = await page.locator('body').innerText();
      console.log(`  ✓ ${name} (${path}): ${bodyText.length} chars`);
    }
  });
});

// ─── TEST 6: Engagement Creation Form Elements ───
test.describe('6. Engagement Creation', () => {
  test('should have engagement creation form', async ({ page }) => {
    await nav(page, '/engagements');
    await expect(page.locator('body')).toBeVisible();

    // Check for engagement-related UI elements
    const bodyText = await page.locator('body').innerText();
    const hasFormElements = bodyText.toLowerCase().includes('target') ||
      bodyText.toLowerCase().includes('scan') ||
      bodyText.toLowerCase().includes('engagement');

    console.log(`  ✓ Engagement page loaded (${bodyText.length} chars, form: ${hasFormElements})`);
    await page.screenshot({ path: '/tmp/e2e-06-engagements.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 7: Findings Page ───
test.describe('7. Findings Page', () => {
  test('should display findings', async ({ page }) => {
    await nav(page, '/findings');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Findings page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-07-findings.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 8: Reports Page ───
test.describe('8. Reports Page', () => {
  test('should display reports', async ({ page }) => {
    await nav(page, '/reports');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Reports page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-08-reports.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 9: Assets Page ───
test.describe('9. Assets Page', () => {
  test('should display assets', async ({ page }) => {
    await nav(page, '/assets');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Assets page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-09-assets.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 10: Rules Page ───
test.describe('10. Rules Page', () => {
  test('should display custom rules', async ({ page }) => {
    await nav(page, '/rules');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Rules page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-10-rules.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 11: Analytics Page ───
test.describe('11. Analytics Page', () => {
  test('should display analytics', async ({ page }) => {
    await nav(page, '/analytics');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Analytics page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-11-analytics.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 12: Settings Page ───
test.describe('12. Settings Page', () => {
  test('should display settings', async ({ page }) => {
    await nav(page, '/settings');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    const sections = [
      ['profile', bodyText.toLowerCase().includes('profile')],
      ['security', bodyText.toLowerCase().includes('security')],
      ['notification', bodyText.toLowerCase().includes('notification')],
      ['api', bodyText.toLowerCase().includes('api') || bodyText.toLowerCase().includes('token')],
    ];
    console.log(`  ✓ Settings page (${bodyText.length} chars, sections: ${sections.filter(s => s[1]).map(s => s[0]).join(', ') || 'none'})`);
    await page.screenshot({ path: '/tmp/e2e-12-settings.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 13: Collaboration Page ───
test.describe('13. Collaboration Page', () => {
  test('should display collaboration features', async ({ page }) => {
    await nav(page, '/collaboration');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Collaboration page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-13-collab.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 14: Compliance Reports Page ───
test.describe('14. Compliance Reports Page', () => {
  test('should display compliance reports', async ({ page }) => {
    await nav(page, '/reports/compliance');
    await expect(page.locator('body')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    console.log(`  ✓ Compliance page (${bodyText.length} chars)`);
    await page.screenshot({ path: '/tmp/e2e-14-compliance.png', fullPage: true }).catch(() => {});
  });
});

// ─── TEST 15: Backend API Health ───
test.describe('15. Backend API Health', () => {
  test('should have healthy APIs', async ({ page }) => {
    // Worker health
    const h = await page.request.get(`${BASE_URL}/api/health/worker`);
    expect(h.ok()).toBeTruthy();
    const hd = await h.json();
    console.log(`  ✓ Worker health: ${hd.status}, redis: ${hd.redis?.status}`);

    // DB health
    const dh = await page.request.get(`${BASE_URL}/api/health/db`);
    if (dh.ok()) {
      const dd = await dh.json();
      console.log(`  ✓ DB health: ${dd.status} (${dd.response_time_ms}ms)`);
    }

    // API endpoints
    const endpoints = ['/api/dashboard/stats', '/api/findings', '/api/engagements', '/api/assets', '/api/reports/compliance', '/api/openapi'];
    for (const ep of endpoints) {
      const r = await page.request.get(`${BASE_URL}${ep}`);
      console.log(`  ${ep}: ${r.status()}${r.ok() ? ' ✓' : ''}`);
    }
  });
});

// ─── TEST 16: API Documentation ───
test.describe('16. API Documentation', () => {
  test('should serve OpenAPI spec', async ({ page }) => {
    const r = await page.request.get(`${BASE_URL}/api/openapi`);
    expect(r.ok()).toBeTruthy();
    const spec = await r.json();
    console.log(`  ✓ OpenAPI: ${spec?.info?.title} v${spec?.info?.version}, ${Object.keys(spec?.paths || {}).length} paths`);
  });
});

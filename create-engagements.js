const { chromium } = require('playwright');

// Read credentials from environment (H-v5-02)
const BASE_URL = process.env.ARGUS_URL || 'http://localhost:3000';
const TEST_EMAIL = process.env.TEST_EMAIL || 'admin@argus.local';
const TEST_PASSWORD = process.env.TEST_PASSWORD || 'password';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Login first
    console.log('Logging in...');
    await page.goto(BASE_URL + '/auth/signin', { timeout: 30000 });
    await page.fill('input[name="email"]', TEST_EMAIL);
    await page.fill('input[name="password"]', TEST_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(5000);

    console.log('Logged in, now creating engagement...');

    // Use fetch API directly
    const engagementData = {
      targetUrl: 'http://demo.testfire.net',
      scanType: 'url',
      scanAggressiveness: 'default',
      authorization: 'AUTHORIZED OPERATIONAL SCAN',
      authorizedScope: {
        domains: ['demo.testfire.net'],
        ipRanges: []
      }
    };

    const response = await page.evaluate(async (data) => {
      const result = await fetch('/api/engagement/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return { status: result.status, data: await result.json() };
    }, engagementData);

    console.log('Response status:', response.status);
    console.log('Engagement ID:', response.data.engagement?.id);
    console.log('Full response:', JSON.stringify(response, null, 2));

  } catch (e) {
    console.error('Error:', e.message);
  } finally {
    await browser.close();
  }
}

run();

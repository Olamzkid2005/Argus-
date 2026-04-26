const { chromium } = require('playwright');

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  try {
    // Login first
    console.log('Logging in...');
    await page.goto('http://localhost:3000/auth/signin', { timeout: 30000 });
    await page.fill('input[name="email"]', 'admin@argus.local');
    await page.fill('input[name="password"]', 'password');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(5000);
    
    console.log('Logged in, now creating engagement...');
    
    // Use fetch API directly - this works better
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
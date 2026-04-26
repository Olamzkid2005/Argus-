const { chromium } = require('playwright');

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // First login
  console.log('=== Logging in ===');
  await page.goto('http://localhost:3000/auth/signin', { timeout: 30000 });
  await page.fill('input[name="email"]', 'admin@argus.local');
  await page.fill('input[name="password"]', 'password');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  console.log('Logged in, URL:', page.url());
  
  // Now go to new engagement page
  console.log('=== Going to new engagement page ===');
  await page.goto('http://localhost:3000/engagements/new');
  await page.waitForTimeout(3000);
  
  const pageText = await page.evaluate(() => document.body.innerText);
  console.log('Page text sample (first 1000 chars):');
  console.log(pageText.substring(0, 1000));
  
  // Get form fields
  const inputs = await page.$$('input');
  console.log('\nNumber of inputs:', inputs.length);
  
  // Try to see what forms/buttons are available
  const buttons = await page.$$('button');
  console.log('Number of buttons:', buttons.length);
  
  // Let me see the URL input
  const urlInput = await page.$('input[name="targetUrl"]');
  if (urlInput) {
    console.log('\nFound targetUrl input');
  }
  
  // Use evaluate to get form state
  const formHtml = await page.evaluate(() => {
    const forms = document.querySelectorAll('form');
    return Array.from(forms).map(f => f.innerHTML.substring(0, 500));
  });
  console.log('\nForm HTML:', formHtml);
  
  await browser.close();
}

run();
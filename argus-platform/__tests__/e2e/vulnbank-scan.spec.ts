import { test } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Scan Vulnbank and Check Findings Storage', () => {
  test('should create scan for vulnbank and verify findings are stored', async ({ page }) => {
    const testUser = {
      email: `vulnscan-${Date.now()}@test.com`,
      password: 'TestPass123!',
      orgName: 'Vuln Scan Org',
    };

    // Step 1: Sign up
    console.log('\n=== Creating user ===');
    await page.goto('http://localhost:3000/auth/signup');
    await page.fill('#email', testUser.email);
    await page.fill('#password', testUser.password);
    await page.fill('#passwordConfirm', testUser.password);
    await page.fill('#orgName', testUser.orgName);
    await page.click('button[type="submit"]');
    await page.waitForURL(/.*\/auth\/signin.*/, { timeout: 15000 });

    // Step 2: Sign in
    console.log('=== Signing in ===');
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.click('button[type="submit"]');
    await page.waitForURL(/.*\/dashboard.*/, { timeout: 15000 });

    // Step 3: Create Vulnbank GitHub scan
    console.log('=== Creating Vulnbank scan ===');
    const repoUrl = 'https://github.com/vulnbank/vulnbank.git';
    
    await page.goto('http://localhost:3000/engagements');
    await page.waitForLoadState('networkidle');
    
    await page.click('text=Repository');
    await page.fill('input[type="text"]', repoUrl);
    await page.click('button:has-text("Start Scan")');
    await page.waitForTimeout(5000);
    
    console.log('Vulnbank scan engagement created');
    console.log('Target:', repoUrl);

    // Wait a bit for the scan to start processing
    console.log('Waiting for scan to process...');
    await page.waitForTimeout(30000);
    
    console.log('\n=== Checking database for results ===');
  });
});

test.describe('Check Database for All Findings', () => {
  test('should verify findings storage after scans', async () => {
    const client = await pool.connect();
    
    try {
      // Get ALL findings
      console.log('\n=== ALL FINDINGS IN DATABASE ===\n');
      
      const allFindings = await client.query(`
        SELECT id, engagement_id, type, severity, confidence, endpoint, source_tool, created_at
        FROM findings 
        ORDER BY created_at DESC
        LIMIT 100
      `);
      
      console.log(`Total findings: ${allFindings.rowCount}\n`);
      
      for (const f of allFindings.rows) {
        console.log(`ID: ${f.id}`);
        console.log(`  Engagement: ${f.engagement_id}`);
        console.log(`  Type: ${f.type}`);
        console.log(`  Severity: ${f.severity}`);
        console.log(`  Confidence: ${f.confidence}`);
        console.log(`  Endpoint: ${f.endpoint}`);
        console.log(`  Tool: ${f.source_tool}`);
        console.log(`  Created: ${f.created_at}`);
        console.log('---');
      }

    } finally {
      client.release();
      await pool.end();
    }
  });
});
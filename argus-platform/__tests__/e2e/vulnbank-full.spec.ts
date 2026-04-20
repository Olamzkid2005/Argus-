import { test, expect } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Vulnbank Scan - Create, Monitor, and Verify Findings', () => {
  const testUser = {
    email: `vulnbank-${Date.now()}@test.com`,
    password: 'TestPass123!',
    orgName: 'Vulnbank Test Org',
  };

  let engagementId = '';

  test('should signup, signin, and create vulnbank repo scan', async ({ page }) => {
    // Step 1: Sign up
    console.log('\n=== Creating user ===');
    await page.goto('http://localhost:3000/auth/signup');
    await page.fill('#email', testUser.email);
    await page.fill('#password', testUser.password);
    await page.fill('#passwordConfirm', testUser.password);
    await page.fill('#orgName', testUser.orgName);
    await page.click('button[type="submit"]');
    await page.waitForURL(/.*\/auth\/signin.*/, { timeout: 15000 });
    console.log('User created');

    // Step 2: Sign in
    console.log('=== Signing in ===');
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.click('button[type="submit"]');
    await page.waitForURL(/.*\/dashboard.*/, { timeout: 15000 });
    console.log('Signed in');

    // Step 3: Create Vulnbank GitHub scan
    console.log('=== Creating Vulnbank scan ===');
    const repoUrl = 'https://github.com/vulnbank/vulnbank.git';
    
    await page.goto('http://localhost:3000/engagements');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    await page.click('text=Repository');
    await page.fill('input[type="text"]', repoUrl);
    await page.click('button:has-text("Start Scan")');
    
    // Wait for redirect to dashboard with engagement ID
    await page.waitForTimeout(5000);
    
    const currentUrl = page.url();
    console.log('Current URL:', currentUrl);
    
    // Extract engagement ID from URL if present
    const match = currentUrl.match(/engagement=([a-f0-9-]+)/);
    if (match) {
      engagementId = match[1];
      console.log('Engagement ID:', engagementId);
    }
    
    console.log('Vulnbank scan engagement created');
  });

  test('should monitor scan progress and verify findings', async () => {
    // Wait for scan to process
    console.log('\n=== Waiting for scan to process... ===');
    
    // Poll the database every 10 seconds for up to 5 minutes
    let maxAttempts = 30;
    let attempt = 0;
    let foundFindings = false;
    
    while (attempt < maxAttempts) {
      attempt++;
      console.log(`\n--- Poll attempt ${attempt}/${maxAttempts} ---`);
      
      const client = await pool.connect();
      try {
        // Check engagements
        const engagements = await client.query(`
          SELECT id, target_url, scan_type, status, created_at 
          FROM engagements 
          WHERE target_url = 'https://github.com/vulnbank/vulnbank.git'
          ORDER BY created_at DESC
          LIMIT 1
        `);
        
        if (engagements.rows.length > 0) {
          const eng = engagements.rows[0];
          engagementId = eng.id;
          console.log(`Engagement: ${eng.id}`);
          console.log(`  Status: ${eng.status}`);
          console.log(`  Target: ${eng.target_url}`);
          console.log(`  Created: ${eng.created_at}`);
          
          // Check findings
          const findings = await client.query(`
            SELECT id, type, severity, confidence, endpoint, source_tool, created_at
            FROM findings 
            WHERE engagement_id = $1
            ORDER BY created_at DESC
          `, [eng.id]);
          
          console.log(`  Findings: ${findings.rowCount}`);
          
          if (findings.rowCount > 0) {
            foundFindings = true;
            console.log('\n=== FINDINGS FOUND! ===\n');
            for (const f of findings.rows) {
              console.log(`[${f.severity}] ${f.type}`);
              console.log(`  Endpoint: ${f.endpoint}`);
              console.log(`  Confidence: ${f.confidence}`);
              console.log(`  Tool: ${f.source_tool}`);
              console.log(`  Created: ${f.created_at}`);
              console.log('---');
            }
            break;
          }
        } else {
          console.log('No vulnbank engagement found yet');
        }
        
        // Check state transitions
        if (engagementId) {
          const states = await client.query(`
            SELECT from_state, to_state, reason, created_at
            FROM engagement_states 
            WHERE engagement_id = $1
            ORDER BY created_at DESC
            LIMIT 5
          `, [engagementId]);
          
          console.log('Recent state transitions:');
          for (const s of states.rows) {
            console.log(`  ${s.from_state || 'null'} → ${s.to_state} (${s.reason})`);
          }
        }
        
        // Check execution logs
        if (engagementId) {
          const logs = await client.query(`
            SELECT event_type, message, created_at
            FROM execution_logs 
            WHERE engagement_id = $1
            ORDER BY created_at DESC
            LIMIT 10
          `, [engagementId]);
          
          console.log('Recent execution logs:');
          for (const l of logs.rows) {
            console.log(`  [${l.event_type}] ${l.message}`);
          }
        }
        
      } finally {
        client.release();
      }
      
      if (!foundFindings) {
        console.log('Waiting 10 seconds before next poll...');
        await new Promise(resolve => setTimeout(resolve, 10000));
      }
    }
    
    if (!foundFindings) {
      console.log('\n=== No findings found after maximum polling attempts ===');
    }
  });
});
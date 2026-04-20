import { test } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Fresh Vulnbank Scan', () => {
  const testUser = {
    email: `fresh-${Date.now()}@test.com`,
    password: 'TestPass123!',
    orgName: 'Fresh Test Org',
  };

  test('should create vulnbank scan and wait for results', async ({ page }) => {
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
    await page.waitForTimeout(5000);
    
    const currentUrl = page.url();
    console.log('Current URL:', currentUrl);
    
    const match = currentUrl.match(/engagement=([a-f0-9-]+)/);
    let engagementId = match ? match[1] : '';
    console.log('Engagement ID:', engagementId);

    // Step 4: Poll for scan progress
    console.log('\n=== Polling for scan progress ===');
    
    for (let attempt = 1; attempt <= 60; attempt++) {
      const client = await pool.connect();
      try {
        // Get latest vulnbank engagement
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
          console.log(`\n[${attempt}] Status: ${eng.status}`);
          
          // Check state transitions
          const states = await client.query(`
            SELECT from_state, to_state, reason, created_at
            FROM engagement_states 
            WHERE engagement_id = $1
            ORDER BY created_at DESC
            LIMIT 3
          `, [eng.id]);
          
          for (const s of states.rows) {
            console.log(`  ${s.from_state || 'null'} → ${s.to_state} (${s.reason})`);
          }
          
          // Check execution logs
          const logs = await client.query(`
            SELECT event_type, message, created_at
            FROM execution_logs 
            WHERE engagement_id = $1
            ORDER BY created_at DESC
            LIMIT 5
          `, [eng.id]);
          
          for (const l of logs.rows) {
            console.log(`  [${l.event_type}] ${l.message}`);
          }
          
          // Check findings
          const findings = await client.query(`
            SELECT id, type, severity, confidence, endpoint, source_tool, created_at
            FROM findings 
            WHERE engagement_id = $1
            ORDER BY created_at DESC
          `, [eng.id]);
          
          console.log(`  Findings count: ${findings.rowCount}`);
          
          if (findings.rowCount > 0) {
            console.log('\n=== ALL FINDINGS ===\n');
            for (const f of findings.rows) {
              console.log(`[${f.severity}] ${f.type}`);
              console.log(`  Endpoint: ${f.endpoint}`);
              console.log(`  Confidence: ${f.confidence}`);
              console.log(`  Tool: ${f.source_tool}`);
              console.log('---');
            }
            return; // Exit early if we have findings
          }
          
          // If status is awaiting_approval or complete, check findings one more time
          if (eng.status === 'awaiting_approval' || eng.status === 'complete') {
            if (findings.rowCount === 0) {
              console.log('Scan completed but no findings stored');
            }
          }
        }
        
      } finally {
        client.release();
      }
      
      if (attempt < 60) {
        await new Promise(resolve => setTimeout(resolve, 10000));
      }
    }
    
    console.log('\n=== Polling complete, checking final state ===');
    
    // Final check
    const client = await pool.connect();
    try {
      const engagements = await client.query(`
        SELECT id, target_url, scan_type, status, created_at 
        FROM engagements 
        WHERE target_url = 'https://github.com/vulnbank/vulnbank.git'
        ORDER BY created_at DESC
        LIMIT 1
      `);
      
      if (engagements.rows.length > 0) {
        const eng = engagements.rows[0];
        console.log(`Final Status: ${eng.status}`);
        
        const findings = await client.query(`
          SELECT id, type, severity, confidence, endpoint, source_tool
          FROM findings 
          WHERE engagement_id = $1
          ORDER BY created_at DESC
        `, [eng.id]);
        
        if (findings.rowCount > 0) {
          console.log(`\nTotal Findings: ${findings.rowCount}\n`);
          for (const f of findings.rows) {
            console.log(`[${f.severity}] ${f.type} - ${f.endpoint} (${f.source_tool})`);
          }
        } else {
          console.log('No findings found');
        }
      }
    } finally {
      client.release();
    }
  });
});
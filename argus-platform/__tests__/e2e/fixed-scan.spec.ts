import { test } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Vulnbank Scan - Fixed Worker', () => {
  const testUser = {
    email: `fixtest-${Date.now()}@test.com`,
    password: 'TestPass123!',
    orgName: 'Fix Test Org',
  };

  test('should create vulnbank scan and verify worker processes it', async ({ page }) => {
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
    await page.goto('http://localhost:3000/engagements');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    await page.click('text=Repository');
    await page.fill('input[type="text"]', 'https://github.com/vulnbank/vulnbank.git');
    await page.click('button:has-text("Start Scan")');
    await page.waitForTimeout(5000);
    
    const currentUrl = page.url();
    console.log('Current URL:', currentUrl);
    
    const match = currentUrl.match(/engagement=([a-f0-9-]+)/);
    const engagementId = match ? match[1] : '';
    console.log('Engagement ID:', engagementId);

    // Step 4: Poll for scan progress
    console.log('\n=== Polling for scan progress ===');
    
    for (let attempt = 1; attempt <= 60; attempt++) {
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
          
          if ((findings.rowCount ?? 0) > 0) {
            console.log('\n=== ALL FINDINGS ===\n');
            for (const f of findings.rows) {
              console.log(`[${f.severity}] ${f.type}`);
              console.log(`  Endpoint: ${f.endpoint}`);
              console.log(`  Confidence: ${f.confidence}`);
              console.log(`  Tool: ${f.source_tool}`);
              console.log('---');
            }
            return;
          }
          
          // If scan completed, stop polling
          if (eng.status === 'awaiting_approval' || eng.status === 'complete' || eng.status === 'failed') {
            console.log(`Scan reached state: ${eng.status}`);
            if ((findings.rowCount ?? 0) === 0) {
              console.log('No findings stored - checking why...');
            }
            break;
          }
        }
        
      } finally {
        client.release();
      }
      
      if (attempt < 60) {
        await new Promise(resolve => setTimeout(resolve, 10000));
      }
    }
    
    // Final check
    console.log('\n=== FINAL DATABASE STATE ===');
    const client = await pool.connect();
    try {
      const engagements = await client.query(`
        SELECT id, target_url, status FROM engagements 
        WHERE target_url = 'https://github.com/vulnbank/vulnbank.git'
        ORDER BY created_at DESC LIMIT 1
      `);
      
      if (engagements.rows.length > 0) {
        const eng = engagements.rows[0];
        console.log(`Engagement: ${eng.id}`);
        console.log(`Status: ${eng.status}`);
        
        const findings = await client.query(
          `SELECT id, type, severity, endpoint, source_tool FROM findings WHERE engagement_id = $1`,
          [eng.id]
        );
        
        console.log(`Findings: ${findings.rowCount}`);
        for (const f of findings.rows) {
          console.log(`  [${f.severity}] ${f.type} - ${f.endpoint} (${f.source_tool})`);
        }
      }
    } finally {
      client.release();
    }
  });
});
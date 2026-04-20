import { test, expect } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Scan Results Display', () => {
  test('should display all raw scan data from database', async ({ page }) => {
    // Check findings
    const findingsResult = await pool.query('SELECT * FROM findings');
    console.log('\n=== RAW FINDINGS ===');
    console.log('Total findings:', findingsResult.rowCount);
    
    if (findingsResult.rows.length > 0) {
      console.log('\nSample finding:');
      console.log(JSON.stringify(findingsResult.rows[0], null, 2));
    } else {
      console.log('No findings in database');
    }
    
    // Check engagements
    const engagementsResult = await pool.query(`
      SELECT id, target_url, scan_type, status, created_at 
      FROM engagements 
      ORDER BY created_at DESC
      LIMIT 10
    `);
    console.log('\n=== RAW ENGAGEMENTS ===');
    console.log('Total engagements:', engagementsResult.rowCount);
    for (const eng of engagementsResult.rows) {
      console.log(`- ${eng.id.slice(0,8)}: ${eng.target_url} (${eng.scan_type}, ${eng.status})`);
    }
    
    // Check engagement_states
    const statesResult = await pool.query(`
      SELECT es.*, e.target_url 
      FROM engagement_states es 
      JOIN engagements e ON e.id = es.engagement_id
      ORDER BY es.created_at DESC
      LIMIT 15
    `);
    console.log('\n=== RAW ENGAGEMENT STATES ===');
    console.log('Total state transitions:', statesResult.rowCount);
    for (const s of statesResult.rows) {
      console.log(`- ${s.target_url?.slice(0,30)}: ${s.from_state || 'null'} → ${s.to_state}`);
    }
    
    // Check tool metrics
    const metricsResult = await pool.query('SELECT * FROM tool_metrics ORDER BY created_at DESC LIMIT 10');
    console.log('\n=== RAW TOOL METRICS ===');
    console.log('Total metric entries:', metricsResult.rowCount);
    for (const m of metricsResult.rows) {
      console.log(`- ${m.tool_name}: success=${m.success}, duration=${m.duration_seconds}s`);
    }
    
    // Check execution logs
    const logsResult = await pool.query('SELECT * FROM execution_logs ORDER BY created_at DESC LIMIT 10');
    console.log('\n=== RAW EXECUTION LOGS ===');
    console.log('Total log entries:', logsResult.rowCount);
    for (const l of logsResult.rows) {
      console.log(`- ${l.log_level}: ${l.message?.slice(0,60)}`);
    }
    
    expect(findingsResult.rowCount).toBeGreaterThanOrEqual(0);
    expect(engagementsResult.rowCount).toBeGreaterThan(0);
  });
});
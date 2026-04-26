import { test } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Investigate Awaiting Approval Engagements', () => {
  test('should check why scans are stuck in awaiting_approval', async () => {
    const client = await pool.connect();
    
    try {
      // Get engagements that are awaiting approval
      console.log('\n=== ENGAGEMENTS AWAITING APPROVAL ===\n');
      
      const awaitingEngagements = await client.query(`
        SELECT id, target_url, scan_type, status, created_at, updated_at 
        FROM engagements 
        WHERE status = 'awaiting_approval'
        ORDER BY created_at DESC
      `);
      
      console.log(`Found ${awaitingEngagements.rowCount} engagements awaiting approval:\n`);
      
      for (const eng of awaitingEngagements.rows) {
        console.log(`Engagement ID: ${eng.id}`);
        console.log(`  Target: ${eng.target_url}`);
        console.log(`  Scan Type: ${eng.scan_type}`);
        console.log(`  Status: ${eng.status}`);
        console.log(`  Created: ${eng.created_at}`);
        console.log(`  Updated: ${eng.updated_at}`);
        console.log('');
        
        // Get findings for this engagement
        const findings = await client.query(`
          SELECT id, type, severity, confidence, endpoint, source_tool, verified, created_at
          FROM findings 
          WHERE engagement_id = $1
          ORDER BY created_at DESC
        `, [eng.id]);
        
        console.log(`  Findings count: ${findings.rowCount}`);
        
        if (findings.rows.length > 0) {
          console.log('  Top findings:');
          for (const f of findings.rows.slice(0, 10)) {
            console.log(`    - [${f.severity}] ${f.type} (${f.source_tool}) - ${f.endpoint}`);
          }
        }
        
        // Get state transitions
        const states = await client.query(`
          SELECT from_state, to_state, reason, created_at
          FROM engagement_states 
          WHERE engagement_id = $1
          ORDER BY created_at ASC
        `, [eng.id]);
        
        console.log('\n  State transitions:');
        for (const s of states.rows) {
          console.log(`    ${s.from_state || 'null'} → ${s.to_state} (${s.reason}) at ${s.created_at}`);
        }
        
        // Get execution logs
        const logs = await client.query(`
          SELECT event_type, message, created_at
          FROM execution_logs 
          WHERE engagement_id = $1
          ORDER BY created_at DESC
          LIMIT 10
        `, [eng.id]);
        
        console.log('\n  Recent execution logs:');
        for (const l of logs.rows) {
          console.log(`    [${l.event_type}] ${l.message} at ${l.created_at}`);
        }
        
        console.log('\n---\n');
      }

      // Check loop budgets
      console.log('\n=== LOOP BUDGETS (Scan Limits) ===\n');
      
      const budgets = await client.query(`
        SELECT lb.*, e.target_url, e.scan_type
        FROM loop_budgets lb
        JOIN engagements e ON lb.engagement_id = e.id
        WHERE e.status = 'awaiting_approval'
        ORDER BY e.created_at DESC
      `);
      
      for (const b of budgets.rows) {
        console.log(`Engagement: ${b.target_url}`);
        console.log(`  Max Cycles: ${b.max_cycles}`);
        console.log(`  Current Cycles: ${b.current_cycles}`);
        console.log(`  Max Depth: ${b.max_depth}`);
        console.log(`  Current Depth: ${b.current_depth}`);
        console.log('');
      }

      // Check for any errors
      console.log('\n=== EXECUTION FAILURES ===\n');
      
      const failures = await client.query(`
        SELECT ef.*, e.target_url
        FROM execution_failures ef
        JOIN engagements e ON ef.engagement_id = e.id
        ORDER BY ef.created_at DESC
        LIMIT 10
      `);
      
      if (failures.rows.length > 0) {
        for (const f of failures.rows) {
          console.log(`Engagement: ${f.target_url}`);
          console.log(`  Failure Type: ${f.failure_type}`);
          console.log(`  Tool: ${f.tool_name}`);
          console.log(`  Error: ${f.error_message}`);
          console.log(`  Attempt: ${f.attempt_number}`);
          console.log(`  Created: ${f.created_at}`);
          console.log('');
        }
      } else {
        console.log('No execution failures recorded.\n');
      }

      // Check findings table more closely
      console.log('\n=== FINDINGS BREAKDOWN ===\n');
      
      const findingsBySeverity = await client.query(`
        SELECT severity, COUNT(*) as count
        FROM findings
        GROUP BY severity
        ORDER BY 
          CASE severity 
            WHEN 'CRITICAL' THEN 1 
            WHEN 'HIGH' THEN 2 
            WHEN 'MEDIUM' THEN 3 
            WHEN 'LOW' THEN 4 
            ELSE 5 
          END
      `);
      
      console.log('Findings by severity:');
      for (const f of findingsBySeverity.rows) {
        console.log(`  ${f.severity}: ${f.count}`);
      }
      
      const findingsByTool = await client.query(`
        SELECT source_tool, COUNT(*) as count
        FROM findings
        GROUP BY source_tool
        ORDER BY count DESC
      `);
      
      console.log('\nFindings by tool:');
      for (const f of findingsByTool.rows) {
        console.log(`  ${f.source_tool}: ${f.count}`);
      }

    } finally {
      client.release();
      await pool.end();
    }
  });
});
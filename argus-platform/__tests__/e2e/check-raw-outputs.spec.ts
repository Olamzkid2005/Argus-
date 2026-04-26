import { test } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Investigate Parser Issues', () => {
  test('should check raw outputs and verify findings storage pipeline', async () => {
    const client = await pool.connect();
    
    try {
      // Check raw_outputs table - where parser failures are stored
      console.log('\n=== RAW OUTPUTS (Parser Failures) ===\n');
      
      const rawOutputs = await client.query(`
        SELECT id, engagement_id, tool_name, raw_output, error_message, created_at
        FROM raw_outputs 
        ORDER BY created_at DESC
        LIMIT 10
      `);
      
      console.log(`Found ${rawOutputs.rowCount} raw outputs:\n`);
      
      for (const ro of rawOutputs.rows) {
        console.log(`Engagement ID: ${ro.engagement_id}`);
        console.log(`  Tool: ${ro.tool_name}`);
        console.log(`  Error: ${ro.error_message}`);
        console.log(`  Raw Output (first 500 chars): ${(ro.raw_output || '').substring(0, 500)}`);
        console.log(`  Created: ${ro.created_at}`);
        console.log('');
      }

      // Check the semgrep output format in execution_logs
      console.log('\n=== SEMGREP OUTPUT SAMPLES ===\n');
      
      const semgrepLogs = await client.query(`
        SELECT metadata 
        FROM execution_logs 
        WHERE event_type = 'tool_executed' 
        AND message LIKE '%semgrep%'
        ORDER BY created_at DESC
        LIMIT 5
      `);
      
      for (const log of semgrepLogs.rows) {
        const meta = log.metadata;
        if (meta && meta.stdout) {
          console.log('Semgrep stdout sample (first 1000 chars):');
          console.log(meta.stdout.substring(0, 1000));
          console.log('\n---\n');
        }
      }

      // Check what format semgrep actually outputs
      console.log('\n=== CHECKING SEMGREP INSTALLATION ===\n');
      
      // Get tool metrics to see success/failure ratios
      const toolStats = await client.query(`
        SELECT 
          tool_name,
          COUNT(*) as total_runs,
          SUM(CASE WHEN success = true THEN 1 ELSE 0 END) as successful_runs,
          AVG(duration_ms) as avg_duration_ms
        FROM tool_metrics 
        GROUP BY tool_name
        ORDER BY total_runs DESC
      `);
      
      console.log('Tool Success Rates:');
      for (const t of toolStats.rows) {
        const rate = ((t.successful_runs / t.total_runs) * 100).toFixed(1);
        console.log(`  ${t.tool_name}: ${rate}% success (${t.total_runs} runs, avg ${Math.round(t.avg_duration_ms)}ms)`);
      }

      // Check loop budget to see if scans are hitting limits
      console.log('\n=== LOOP BUDGET ANALYSIS ===\n');
      
      const budgets = await client.query(`
        SELECT 
          e.target_url,
          e.status,
          lb.max_cycles,
          lb.current_cycles,
          lb.max_depth,
          lb.current_depth,
        FROM loop_budgets lb
        JOIN engagements e ON lb.engagement_id = e.id
        ORDER BY e.created_at DESC
        LIMIT 10
      `);
      
      for (const b of budgets.rows) {
        console.log(`Target: ${b.target_url}`);
        console.log(`  Status: ${b.status}`);
        console.log(`  Cycles: ${b.current_cycles}/${b.max_cycles}`);
        console.log(`  Depth: ${b.current_depth}/${b.max_depth}`);
        console.log('');
      }

    } finally {
      client.release();
      await pool.end();
    }
  });
});
import { test } from '@playwright/test';
import { Pool } from 'pg';

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  user: 'argus_user',
  password: 'argus_dev_password_change_in_production',
  database: 'argus_pentest',
});

test.describe('Deep Investigation of Findings Pipeline', () => {
  test('should check actual semgrep outputs and verify storage', async () => {
    const client = await pool.connect();
    
    try {
      // Get execution logs with full metadata including stdout/stderr
      console.log('\n=== FETCHING TOOL EXECUTION METADATA ===\n');
      
      const toolLogs = await client.query(`
        SELECT 
          el.engagement_id,
          el.event_type,
          el.message,
          el.metadata,
          el.created_at,
          e.target_url,
          e.scan_type
        FROM execution_logs el
        JOIN engagements e ON el.engagement_id = e.id
        WHERE el.event_type = 'tool_executed'
        ORDER BY el.created_at DESC
        LIMIT 15
      `);
      
      for (const log of toolLogs.rows) {
        console.log(`\n=== Tool: ${log.message} ===`);
        console.log(`Target: ${log.target_url} (${log.scan_type})`);
        console.log(`Engagement: ${log.engagement_id}`);
        console.log(`Time: ${log.created_at}`);
        
        const meta = log.metadata;
        if (meta) {
          console.log(`\n--- Execution Details ---`);
          console.log(`Success: ${meta.success}`);
          console.log(`Return Code: ${meta.return_code}`);
          console.log(`Duration: ${meta.duration_ms}ms`);
          console.log(`Arguments: ${JSON.stringify(meta.arguments)}`);
          
          if (meta.stdout) {
            console.log(`\n--- STDOUT (first 2000 chars) ---`);
            console.log(meta.stdout.substring(0, 2000));
          }
          
          if (meta.stderr) {
            console.log(`\n--- STDERR (first 1000 chars) ---`);
            console.log(meta.stderr.substring(0, 1000));
          }
        }
        console.log('\n' + '='.repeat(60));
      }

      // Check specifically for successful semgrep runs with findings
      console.log('\n=== SEMGREP RUNS WITH RESULTS ===\n');
      
      const semgrepWithResults = await client.query(`
        SELECT 
          el.metadata,
          e.target_url
        FROM execution_logs el
        JOIN engagements e ON el.engagement_id = e.id
        WHERE el.event_type = 'tool_executed'
        AND el.message LIKE '%semgrep%'
        AND el.metadata->>'success' = 'true'
        ORDER BY el.created_at DESC
        LIMIT 5
      `);
      
      console.log(`Found ${semgrepWithResults.rowCount} successful semgrep runs\n`);
      
      for (const log of semgrepWithResults.rows) {
        const meta = log.metadata;
        console.log(`Target: ${log.target_url}`);
        console.log(`Config: ${meta.arguments ? meta.arguments.join(' ') : 'N/A'}`);
        
        if (meta.stdout) {
          // Try to count JSON results
          const lines = meta.stdout.split('\n').filter((l: string) => l.trim().startsWith('{'));
          console.log(`JSON lines in output: ${lines.length}`);
          
          if (lines.length > 0) {
            try {
              const parsed = JSON.parse(lines[0]);
              console.log(`First result check_id: ${parsed.check_id || 'N/A'}`);
              console.log(`First result path: ${parsed.path || 'N/A'}`);
            } catch (e) {
              console.log(`Could not parse JSON: ${e}`);
            }
          }
        }
        console.log('---');
      }

    } finally {
      client.release();
      await pool.end();
    }
  });
});
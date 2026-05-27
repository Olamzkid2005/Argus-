const { Pool } = require('pg');

// CRITICAL: Read DATABASE_URL from environment only (C-v5-01, M-v5-07).
// Never hardcode database credentials in source files.
const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error('ERROR: DATABASE_URL environment variable is required.');
  console.error('Usage: DATABASE_URL=postgresql://user:password@host:5432/db node check-engagement.js [engagement-id]');
  process.exit(1);
}

const pool = new Pool({ connectionString: databaseUrl });

const engagementId = process.argv[2] || 'd4fa6ead-ce4c-4082-a4fc-6687f00feb00';

async function check() {
  try {
    // Check engagement status
    const eng = await pool.query('SELECT id, target_url, status, created_at, updated_at FROM engagements WHERE id = $1', [engagementId]);

    if (eng.rows.length === 0) {
      console.log('Engagement not found in database');
      await pool.end();
      return;
    }

    const e = eng.rows[0];
    console.log('\nEngagement Details:');
    console.log('  ID:        ' + e.id);
    console.log('  Target:    ' + e.target_url);
    console.log('  Status:    ' + e.status);
    console.log('  Created:   ' + e.created_at);
    console.log('  Updated:   ' + e.updated_at);

    // Check scanner activities
    const activities = await pool.query(
      'SELECT tool_name, activity, status, items_found, created_at FROM scanner_activities WHERE engagement_id = $1 ORDER BY created_at DESC LIMIT 20',
      [engagementId]
    );

    console.log('\nScanner Activities (' + activities.rows.length + ' total):');
    if (activities.rows.length === 0) {
      console.log('  No scanner activities recorded yet');
    } else {
      activities.rows.forEach(a => {
        const statusIcon = a.status === 'completed' ? '[OK]' : a.status === 'failed' ? '[FAIL]' : a.status === 'started' ? '[RUN]' : '[PEND]';
        console.log('  ' + statusIcon + ' [' + a.tool_name + '] ' + a.activity + (a.items_found !== null ? ' (' + a.items_found + ' found)' : ''));
      });
    }

    // Check findings count
    const findings = await pool.query('SELECT COUNT(*) as count, severity FROM findings WHERE engagement_id = $1 GROUP BY severity ORDER BY count DESC', [engagementId]);
    console.log('\nFindings:');
    if (findings.rows.length === 0) {
      console.log('  No findings yet');
    } else {
      findings.rows.forEach(f => console.log('  ' + f.severity + ': ' + f.count));
    }

    await pool.end();
  } catch (e) {
    console.error('Error:', e.message);
    await pool.end();
  }
}

check();

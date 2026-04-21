const { Pool } = require('pg');

const pool = new Pool({
  connectionString: 'postgresql://postgres@localhost:5432/argus_pentest',
});

const engagementId = 'd4fa6ead-ce4c-4082-a4fc-6687f00feb00';

async function check() {
  try {
    // Check engagement status
    const eng = await pool.query('SELECT id, target_url, status, created_at, updated_at FROM engagements WHERE id = $1', [engagementId]);
    
    if (eng.rows.length === 0) {
      console.log('❌ Engagement not found in database');
      await pool.end();
      return;
    }
    
    const e = eng.rows[0];
    console.log('\n📋 Engagement Details:');
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
    
    console.log('\n🔍 Scanner Activities (' + activities.rows.length + ' total):');
    if (activities.rows.length === 0) {
      console.log('  No scanner activities recorded yet');
    } else {
      activities.rows.forEach(a => {
        const icon = a.status === 'completed' ? '✅' : a.status === 'failed' ? '❌' : a.status === 'started' ? '🔄' : '⏳';
        console.log(`  ${icon} [${a.tool_name}] ${a.activity} ${a.items_found !== null ? '(' + a.items_found + ' found)' : ''}`);
      });
    }
    
    // Check findings count
    const findings = await pool.query('SELECT COUNT(*) as count, severity FROM findings WHERE engagement_id = $1 GROUP BY severity ORDER BY count DESC', [engagementId]);
    console.log('\n🐛 Findings:');
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

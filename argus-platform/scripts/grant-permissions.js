const { Pool } = require('pg');

const pool = new Pool({
  connectionString: 'postgresql://postgres@localhost:5432/argus_pentest',
  connectionTimeoutMillis: 5000,
});

async function grantPermissions() {
  const client = await pool.connect();
  try {
    await client.query(`
      GRANT ALL PRIVILEGES ON TABLE custom_rules TO argus_user;
      GRANT ALL PRIVILEGES ON TABLE custom_rule_versions TO argus_user;
      GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO argus_user;
    `);
    console.log('✅ Permissions granted to argus_user');
  } catch (err) {
    console.error('❌ Failed to grant permissions:', err.message);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

grantPermissions();

const bcrypt = require('bcryptjs');
const { Pool } = require('pg');

// CRITICAL: Read DATABASE_URL from environment only (C-v5-01).
// Never hardcode database credentials in source files.
const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error('ERROR: DATABASE_URL environment variable is required.');
  console.error('Usage: DATABASE_URL=postgresql://user:password@host:5432/db node reset-password.js [email] [password]');
  process.exit(1);
}

const pool = new Pool({ connectionString: databaseUrl });

const email = process.argv[2] || 'davidolamijulo2005@gmail.com';
const newPassword = process.argv[3] || 'Olamzkid123';

async function main() {
  const hash = await bcrypt.hash(newPassword, 12);
  console.log('New hash:', hash);

  await pool.query(
    `UPDATE users SET password_hash = $1, failed_login_attempts = 0, locked_until = NULL WHERE email = $2`,
    [hash, email]
  );
  console.log('Password updated successfully for:', email);
  pool.end();
}

main().catch(e => { console.error(e); pool.end(); process.exit(1); });

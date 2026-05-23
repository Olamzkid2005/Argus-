const bcrypt = require('bcryptjs');
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: 'postgresql://argus_user:argus_dev_password_change_in_production@localhost:5432/argus_pentest'
});

async function main() {
  const hash = await bcrypt.hash('Olamzkid123', 12);
  console.log('New hash:', hash);
  
  await pool.query(
    `UPDATE users SET password_hash = $1, failed_login_attempts = 0, locked_until = NULL WHERE email = $2`,
    [hash, 'davidolamijulo2005@gmail.com']
  );
  console.log('Password updated successfully');
  pool.end();
}

main().catch(e => { console.error(e); pool.end(); process.exit(1); });

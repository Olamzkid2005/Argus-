const { Pool } = require('pg');

// Connect as postgres superuser
const pool = new Pool({
  connectionString: 'postgresql://postgres@localhost:5432/argus_pentest',
  connectionTimeoutMillis: 5000,
});

const sql = `
CREATE TABLE IF NOT EXISTS custom_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rule_yaml TEXT NOT NULL,
    severity VARCHAR(50) NOT NULL DEFAULT 'MEDIUM',
    category VARCHAR(100) NOT NULL DEFAULT 'custom',
    tags TEXT[],
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    parent_rule_id UUID REFERENCES custom_rules(id) ON DELETE SET NULL,
    test_results JSONB,
    is_community_shared BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_rule_status CHECK (status IN ('draft', 'active', 'deprecated', 'archived'))
);

CREATE TABLE IF NOT EXISTS custom_rule_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id UUID NOT NULL REFERENCES custom_rules(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    rule_yaml TEXT NOT NULL,
    change_notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(rule_id, version)
);

CREATE INDEX IF NOT EXISTS idx_custom_rules_org_id ON custom_rules(org_id);
CREATE INDEX IF NOT EXISTS idx_custom_rules_status ON custom_rules(status);
CREATE INDEX IF NOT EXISTS idx_custom_rules_category ON custom_rules(category);
CREATE INDEX IF NOT EXISTS idx_custom_rule_versions_rule_id ON custom_rule_versions(rule_id);
`;

async function migrate() {
  const client = await pool.connect();
  try {
    await client.query(sql);
    console.log('✅ custom_rules and custom_rule_versions tables created successfully');
  } catch (err) {
    console.error('❌ Migration failed:', err.message);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

migrate();

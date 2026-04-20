-- User Settings Migration
-- Add user_settings table for API key storage

-- Create user_settings table if it doesn't exist
CREATE TABLE IF NOT EXISTS user_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email VARCHAR(255) NOT NULL,
    key VARCHAR(100) NOT NULL,
    value TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_email, key)
);

-- Add foreign key constraint (optional - only if users table exists)
-- ALTER TABLE user_settings 
-- ADD CONSTRAINT fk_user_email 
-- FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_settings_email ON user_settings(user_email);

-- Grant permissions (adjust for your setup)
GRANT ALL PRIVILEGES ON user_settings TO argus_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO argus_user;

-- Insert test settings for development
-- INSERT INTO user_settings (user_email, key, value) 
-- VALUES ('test@example.com', 'openai_api_key', 'sk-test-key')
-- ON CONFLICT (user_email, key) DO NOTHING;

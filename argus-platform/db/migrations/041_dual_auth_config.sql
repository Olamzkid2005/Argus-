-- Migration 041: Dual Auth Config
-- Persists the second account configuration for dual-auth BOLA/BOPLA testing.
-- Previously only passed through the Redis job queue (lost on restart),
-- now stored alongside the primary auth_config for durability.

ALTER TABLE engagements
ADD COLUMN IF NOT EXISTS dual_auth_config JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN engagements.dual_auth_config IS
'Secondary authentication config for dual-account BOLA/BOPLA scanning.
Same schema as auth_config: {type: "form"|"bearer"|"cookie", username, password, token, cookie, login_url}.
Only used when auth_config is also set.';

# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# git
- Push to GitHub after every step or fix is completed, not batched at the end. Confidence: 1.0

# cli
- Use `/opt/local/lib/postgresql15/bin/psql` with `-U argus_user` for PostgreSQL commands. Confidence: 0.65
- Use `browser-use-direct` CLI commands (open, state, close) for browser-based testing instead of curl. Confidence: 0.75

# logging
- Log all errors to console (both server-side and browser console) with timestamps, stack traces, and exact source location so failures are immediately visible and traceable. Confidence: 1.0

# exploration
- When exploring a large codebase with subagents, run them sequentially one at a time instead of in parallel to avoid token limit issues. Confidence: 0.70

# api-design
- When renaming public API methods, add backward-compatible wrapper functions so existing consumers don't break. Confidence: 1.0

# workflow
See [workflow/taste.md](workflow/taste.md)
# testing
- When performing browser-based QA testing, also check browser console logs and Celery worker logs for errors, not just the UI. Confidence: 0.70

# workflow
- When asked to check configuration via the frontend/UI settings page, use browser-based testing to verify through the UI rather than bypassing to check config files directly. Confidence: 0.70

# llm
- LLM/OpenRouter API keys are configured through the frontend Settings page and stored in Redis — do not look for them in .env.local. Confidence: 0.80

# code-audit
- When auditing dedup/diff logic, check for double-counting: findings matched via both primary fingerprint AND fallback fingerprint get counted in both branches, inflating metrics. Confidence: 0.70
- When auditing SQL UPDATE/DELETE operations on shared rows (e.g., mark_fixed), check for missing FOR UPDATE locks — concurrent tasks can race and corrupt audit trails. Confidence: 0.70
- When auditing database-persist operations (store_diff_in_profile), verify the target column exists in the schema — silent no-ops waste every write. Confidence: 0.70
- When auditing threat-feed matching logic, trace the full type-resolution path (raw type → normalized family → threat indicator key) to verify keys actually match — convoluted double-resolution may work accidentally but silently miss new types. Confidence: 0.70

# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# git
- Push to GitHub after every step has been completed, not batched at the end. Confidence: 0.85

# cli
- Use `/opt/local/lib/postgresql15/bin/psql` with `-U argus_user` for PostgreSQL commands. Confidence: 0.65
- Use `browser-use-direct` CLI commands (open, state, close) for browser-based testing instead of curl. Confidence: 0.75

# logging
- Log all errors to console (both server-side and browser console) with timestamps, stack traces, and exact source location so failures are immediately visible and traceable. Confidence: 0.70

# exploration
- When exploring a large codebase with subagents, run them sequentially one at a time instead of in parallel to avoid token limit issues. Confidence: 0.70

# api-design
- When renaming public API methods, add backward-compatible wrapper functions so existing consumers don't break. Confidence: 0.70

# workflow
- After writing code, review it for errors, fix any found, then repeat the review-fix loop at least twice. Confidence: 0.65
- Write an implementation plan to docs/ before starting to code, and wait for user approval before proceeding. Confidence: 0.60

# testing
- When performing browser-based QA testing, also check browser console logs and Celery worker logs for errors, not just the UI. Confidence: 0.70

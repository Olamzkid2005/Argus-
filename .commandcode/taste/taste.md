# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# git
- Push to GitHub after every step has been completed, not batched at the end. Confidence: 0.85

# cli
- Use `/opt/local/lib/postgresql15/bin/psql` with `-U argus_user` for PostgreSQL commands. Confidence: 0.65
- Use `browser-use-direct` CLI commands (open, state, close) for browser-based testing instead of curl. Confidence: 0.75

# exploration
- When exploring a large codebase with subagents, run them sequentially one at a time instead of in parallel to avoid token limit issues. Confidence: 0.70

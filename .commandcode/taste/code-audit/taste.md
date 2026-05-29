# code-audit
- When auditing dedup/diff logic, check for double-counting: findings matched via both primary fingerprint AND fallback fingerprint get counted in both branches, inflating metrics. Confidence: 0.70
- When auditing SQL UPDATE/DELETE operations on shared rows (e.g., mark_fixed), check for missing FOR UPDATE locks — concurrent tasks can race and corrupt audit trails. Confidence: 0.70
- When auditing database-persist operations (store_diff_in_profile), verify the target column exists in the schema — silent no-ops waste every write. Confidence: 0.70
- When auditing threat-feed matching logic, trace the full type-resolution path (raw type → normalized family → threat indicator key) to verify keys actually match — convoluted double-resolution may work accidentally but silently miss new types. Confidence: 0.70
- Before reporting a bug as confirmed, verify it against the actual codebase: check function signatures match call sites, grep for column names in migration files, and confirm import paths exist — don't flag suspicious code without verification. Confidence: 0.70
- Perform multiple rescans of the codebase until no bugs or logic gaps are identified — do not stop after the first pass. Confidence: 0.85

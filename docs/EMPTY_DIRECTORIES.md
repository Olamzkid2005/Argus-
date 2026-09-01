> **Current-status notice (verified 2026-09-01):** This document is a dated decision, plan, audit, or historical record. Its completion claims are not a current implementation guarantee; current source, configuration, and tests are authoritative.

# Empty Directories in the Codebase

These directories exist but are intentionally empty:

- `argus-workers/tool_assets/nuclei-templates/` — Placeholder for custom Nuclei templates.
  By default, Nuclei uses its built-in template set (installed via `nuclei -update`).
  Drop custom `.yaml` templates here to have them discovered by `scan.py`.

- `argus-workers/custom_rules/registry/community/` — Placeholder for community-contributed
  custom rules. Not yet populated.

- `argus-workers/custom_rules/registry/versions/` — Placeholder for versioned rule sets.
  Not yet populated.

These directories exist to reserve the path structure for future features. No code
depends on them being populated.

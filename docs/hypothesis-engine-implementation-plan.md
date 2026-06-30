# Implementation Plan: Hypothesis Engine

**Status:** Draft — ready for implementation  
**Scope:** `argus-workers` Python runtime (with TypeScript-side hooks documented)  
**Primary Goal:** Replace the unused `EngagementState.hypotheses: list[str]` placeholder and the trivial CWE/type+host root-cause grouper with a real `HypothesisEngine` that emits ranked, verifiable hypotheses and drives the agent loop toward confirmation or rejection.

---

## 0. Context

The Autonomous Red Team Readiness Review (`docs/autonomous-red-team-readiness-review.md`, blocker #25) states:

> **No hypothesis generation or root-cause analysis**  
> Files: `argus-workers/runtime/engagement_state.py`, `tools/correlation/root_cause.py`, `intelligence_engine.py`  
> Issue: `hypotheses` field is initialized but never used. Root-cause grouping is trivial tuple dedup.  
> Fix: Add a `HypothesisEngine` that emits ranked hypotheses and verification steps.

Current state confirmed by code audit:

- `EngagementState.hypotheses` is declared as `list[str]` at line 96 and never read/written elsewhere.
- `root_cause.py` only groups findings by `cwe:{cwe}` or `type:{type}:host:{host}`. It does not generate causal explanations, confidence scores, or verification steps.
- `IntelligenceEngine.evaluate()` produces scored findings and analysis, but no hypotheses.
- `ReActAgent` selects tools based on recon/observations; it has no concept of active hypotheses to confirm/disprove.
- `FindingCorrelationEngine` computes root causes and attack chains but only logs them in a summary info finding; they do not feed back into planning.

A Hypothesis Engine closes the loop: findings → hypotheses → verification steps → tool selection → confirmed/rejected hypotheses → better replanning.

---

## 1. Data Model

### 1.1 Typed model: `argus-workers/models/hypothesis.py`

Use `TypedDict` (not Pydantic) to stay consistent with how the rest of the system handles findings (`list[dict]`). This avoids runtime conversion overhead, `ValidationError` crash surfaces, and scattered `model_dump()`/`model_validate()` calls. A standalone `validate_hypothesis()` helper provides runtime validation at the two trust boundaries (LLM synthesizer output and Postgres deserialization).

```python
"""Hypothesis data model."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, NotRequired, TypedDict


class HypothesisStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    # PARTIALLY_VERIFIED — reserved for future verification step granularity


class VerificationStep(TypedDict):
    """A single verification action with a machine-executable contract."""
    description: str        # Human-readable: "Run sqlmap against /api/search?q=id"
    tool: str               # Tool name: "sqlmap"
    arguments: dict         # Default arguments: {"target": "/api/search", "parameter": "id"}
    expected: str           # Success criterion: "findings_count > 0" or "status.is_ok"


class Hypothesis(TypedDict):
    """A testable conjecture that explains a cluster of findings and proposes
    verification steps.

    This is a TypedDict for zero-runtime-overhead type checking.
    Validate external input via validate_hypothesis() before accepting it.
    """

    id: str
    engagement_id: str
    description: str
    root_cause_key: NotRequired[str | None]
    source_finding_id: NotRequired[str | None]
    confidence: float
    status: str  # HypothesisStatus value
    verification_steps: list[VerificationStep]
    finding_ids: list[str]
    supporting_finding_ids: list[str]
    refuting_finding_ids: list[str]
    suggested_tools: list[str]
    created_at: str  # ISO-8601
    updated_at: str  # ISO-8601


def validate_hypothesis(h: dict, *, source: str = "unknown") -> dict:
    """Runtime validation at trust boundaries (LLM output, Postgres load).

    Raises ValueError with a descriptive message on invalid input.
    Returns the dict unchanged (no copy) on success.
    """
    errors: list[str] = []

    if not isinstance(h.get("id"), str) or not h["id"]:
        errors.append("id must be a non-empty string")
    if not isinstance(h.get("description"), str) or not h["description"].strip():
        errors.append("description must be a non-empty string")
    confidence = h.get("confidence", -1)
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        errors.append("confidence must be a float in [0.0, 1.0]")
    if h.get("status") not in ("UNVERIFIED", "CONFIRMED", "REJECTED"):
        errors.append(f"invalid status: {h.get('status')!r}")
    for list_field in ("finding_ids", "supporting_finding_ids",
                       "refuting_finding_ids", "suggested_tools"):
        val = h.get(list_field)
        if val is None:
            h[list_field] = []
        elif isinstance(val, str):
            errors.append(f"{list_field} must be a list, got string")
        elif not isinstance(val, list):
            errors.append(f"{list_field} must be a list, got {type(val).__name__}")
    # verification_steps is a list of dicts
    vs = h.get("verification_steps")
    if vs is None:
        h["verification_steps"] = []
    elif isinstance(vs, list):
        for i, step in enumerate(vs):
            if not isinstance(step, dict):
                errors.append(f"verification_steps[{i}] must be a dict")
            elif not isinstance(step.get("description"), str):
                errors.append(f"verification_steps[{i}].description must be a string")
    else:
        errors.append("verification_steps must be a list")

    if errors:
        raise ValueError(f"Hypothesis validation failed ({source}): {'; '.join(errors)}")
    return h
```

### 1.2 Database migration

Create `argus-workers/database/migrations/017_add_hypotheses.sql`. Note: migration `011` currently has duplicates (`011_add_target_profiles_table.sql` and `011_add_assets_table.sql`). Use `017` to avoid collisions. **Separately fix the duplicate `011` migration files** — rename one to `012` and update the migration runner; otherwise fresh database setups will fail.

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS hypotheses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    root_cause_key TEXT,
    source_finding_id UUID,  -- populated for single-finding hypotheses; NULL for grouped
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (status IN ('UNVERIFIED', 'CONFIRMED', 'REJECTED')),
    verification_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    supporting_finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    refuting_finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Prevent duplicate generation on concurrent run_analysis() calls.
-- Grouped hypotheses dedup on (engagement_id, root_cause_key).
-- Single-finding hypotheses dedup on (engagement_id, source_finding_id).
CREATE UNIQUE INDEX IF NOT EXISTS idx_hypotheses_engagement_root_cause
    ON hypotheses(engagement_id, root_cause_key) WHERE root_cause_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_hypotheses_engagement_source_finding
    ON hypotheses(engagement_id, source_finding_id) WHERE source_finding_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hypotheses_engagement_id ON hypotheses(engagement_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status);

COMMIT;
```

### 1.3 Repository: `argus-workers/database/repositories/hypothesis_repository.py`

Follow the `BaseRepository` pattern. Add CRUD for hypotheses and the link table.

Key methods (no link table in MVP — `finding_ids`/`supporting_finding_ids`/`refuting_finding_ids` JSONB columns suffice):

```python
class HypothesisRepository(BaseRepository):
    table_name = "hypotheses"
    id_column = "id"

    def create(self, hypothesis: dict) -> dict:
        ...

    def get_by_engagement(self, engagement_id: str, status: str | None = None) -> list[dict]:
        ...

    def update(self, hypothesis_id: str, updates: dict) -> dict | None:
        ...
```

Register the table name in `database/repositories/base.py` `_ALLOWED_TABLE_NAMES` and `ALLOWED_COLUMNS` if you want to reuse `update_by_id`.

### 1.4 Optional: extend `VulnerabilityFinding`

Add an optional `hypothesis_id: str | None = None` field to `models/finding.py` only if the hypothesis engine needs to tag findings at the model layer. Prefer the `hypothesis_findings` link table for many-to-many relationships.

---

## 2. Files to Create / Modify

| Action | File | Why |
|--------|------|-----|
| Create | `models/hypothesis.py` | TypedDict model with `validate_hypothesis()` helper |
| Create | `models/finding_types.py` | Shared type-family normalization map (imported by both hypothesis_engine and intelligence_engine) |
| Create | `database/repositories/hypothesis_repository.py` | CRUD persistence |
| Create | `database/migrations/017_add_hypotheses.sql` | Schema (no link table in MVP) |
| Create | `tools/hypothesis_engine.py` | Plain service class (NOT an AbstractTool) |
| Create | `tests/test_hypothesis_engine.py` | Unit tests |
| Modify | `database/repositories/finding_repository.py` | Add `get_top_findings_for_hypothesis()` — severity-ranked, capped query |
| Modify | `config/constants.py` | Add `HYPOTHESIS_MAX_INPUT_FINDINGS = 5000` and `HYPOTHESIS_MAX_OUTPUT = 20` |
| Modify | `tools/correlation/root_cause.py` | Add `_group_findings_for_hypotheses()` for hypothesis-specific grouping |
| Modify | `runtime/engagement_state.py` | Change `hypotheses` to `list[dict]`, add CRUD methods, exclude from Redis snapshot |
| Modify | `orchestrator_pkg/orchestrator.py` | **Single generation site** — call `HypothesisEngine.generate()` in `run_analysis` |
| Modify | `orchestrator_pkg/analysis/intelligence_service.py` | Pass hypotheses through synthesis |
| Modify | `llm_synthesizer.py` | Add dedicated `update_hypotheses()` LLM call (separate from `synthesize()`) |
| Modify | `agent/agent_prompts.py` | Add `=== ACTIVE HYPOTHESES ===` section |
| Modify | `agent/react_agent.py` | Pass hypotheses into tool-selection context |
| Modify | `feature_flags.py` | Add `FEATURE_HYPOTHESIS_ENGINE` and add to `AUTONOMOUS_FEATURES` |

---

## 3. Step-by-Step Implementation

### Phase 0 — Foundation (no behavior change yet)

#### Step 0.1 — Add feature flag

In `feature_flags.py`:

1. Add constant:
   ```python
   FEATURE_HYPOTHESIS_ENGINE = "HYPOTHESIS_ENGINE"
   ```
2. Add `"HYPOTHESIS_ENGINE"` to `AUTONOMOUS_FEATURES`.

Use the flag everywhere the engine is invoked:

```python
from feature_flags import is_enabled

if is_enabled("HYPOTHESIS_ENGINE", default=False):
    ...
```

#### Step 0.2 — Add data model, exceptions, and migration

1. Create `models/hypothesis.py`.
2. Add to `exceptions.py` — following the existing `ArgusError` pattern so the orchestrator's outer `except ArgusError` catches them without modification:
   ```python
   class HypothesisError(ArgusError):
       """Base for hypothesis engine failures."""

   class HypothesisGenerationError(HypothesisError):
       """generate() failed to produce hypotheses from findings."""
       default_code = ErrorCode.DATABASE_ERROR  # triggers TRANSIENT retry path

   class HypothesisPersistenceError(HypothesisError):
       """Postgres write for hypothesis create/update failed."""
       default_code = ErrorCode.DATABASE_ERROR
   ```
3. Create `database/migrations/017_add_hypotheses.sql`.
4. Create `database/repositories/hypothesis_repository.py`.
5. Update `database/repositories/base.py` allowlists.
6. Run `python -m database.migrations.runner` locally to verify.

#### Step 0.3 — Add HypothesisEngine service class

Create `tools/hypothesis_engine.py` — a plain service class, not an `AbstractTool`. Hypotheses are NOT emitted as findings through the finding pipeline; they travel through `EngagementState` and Postgres directly. The `FindingBuilder`/`UnifiedToolResult`/`ToolContext` machinery is for agent-selectable tools — the orchestrator calls `HypothesisEngine.generate()` directly:

```python
"""Hypothesis Engine — generates and updates testable hypotheses from findings."""

from __future__ import annotations

import logging
from uuid import uuid4

from exceptions import HypothesisGenerationError, HypothesisPersistenceError
from feature_flags import is_enabled

logger = logging.getLogger(__name__)


class HypothesisEngine:
    """Generate ranked hypotheses and verification steps from a set of findings.

    This is a plain service class — NOT an AbstractTool.
    Hypotheses travel through EngagementState and Postgres, not the finding stream.
    Call ``generate()`` directly from the orchestrator.
    """

    def generate(self, findings: list[dict], engagement_id: str) -> list[dict]:
        """Generate hypotheses from findings. Returns plain dicts."""
        ...
```

No registration in `tool_definitions.py` or `run_agent_tool.py` — this is not an agent-selectable tool. The orchestrator imports and calls it directly.

---

### Phase 1 — Core Hypothesis Generation

#### Step 1.1 — Replace trivial root-cause grouping

Modify `tools/correlation/root_cause.py`:

- Keep `_root_cause_key()` as the deterministic fallback.
- Add a new function `_group_findings_for_hypotheses(findings, min_group_size=2)` that returns groups with metadata (note: hypothesis-specific grouping, not a general-purpose correlation function — rename clearly to avoid confusion with `FindingCorrelationEngine`):
  ```python
  {
      "root_cause_key": str,
      "category": "cwe" | "type_host" | "shared_endpoint" | "shared_parameter",
      "finding_count": int,
      "max_severity": str,
      "affected_endpoints": list[str],
      "finding_ids": list[str],
      "common_parameters": list[str],  # optional
      "common_cwe": str | None,
  }
  ```
- Add a simple parameter-extraction helper that pulls parameter names from `evidence` dicts (e.g., keys named `parameter`, `param`, `input`) so SQLi across multiple endpoints can be grouped by shared parameter.

#### Step 1.2 — Implement deterministic hypothesis generation

In `tools/hypothesis_engine.py`, implement `generate()` without LLM first:

```python
    # Reverse lookup: canonical family → finding types that normalize to it.
    # Used in _single_finding_hypothesis() to map a finding to verification tools.
    # Extracted to models/finding_types.py so intelligence_engine.py reuses the same map.
    _VERIFICATION_TOOL_MAP: dict[str, list[str]] = {
        "SQLI": ["sqlmap", "verification_agent"],
        "XSS": ["finding_verifier", "verification_agent"],
        "SSRF": ["finding_verifier", "verification_agent"],
        "RCE": ["finding_verifier", "verification_agent"],
        "OPEN_REDIRECT": ["finding_verifier", "verification_agent"],
        "JWT": ["jwt_tool", "verification_agent"],
        "BOLA": ["dual_auth_scanner", "verification_agent"],
        "IDOR": ["dual_auth_scanner", "verification_agent"],
        "EXPOSED_SECRET": ["credential_replay", "verification_agent"],
    }

    _TYPE_TO_FAMILY: dict[str, str] = {
        "SQL_INJECTION": "SQLI", "BLIND_SQLI": "SQLI",
        "TIME_BASED_SQLI": "SQLI", "TIME_BASED_SQL_INJECTION": "SQLI", "ERROR_SQLI": "SQLI",
        "REFLECTED_XSS": "XSS", "STORED_XSS": "XSS", "DOM_XSS": "XSS", "BLIND_XSS": "XSS",
        "CROSS_SITE_SCRIPTING": "XSS",
        "COMMAND_INJECTION": "RCE", "SSTI": "RCE",
        "PATH_TRAVERSAL": "LFI", "DIRECTORY_TRAVERSAL": "LFI",
    }

    def generate(self, findings: list[dict], engagement_id: str) -> list[dict]:
        """Generate hypotheses from pre-ranked findings.

        Caller is responsible for passing a severity-ranked, capped list.
        See ``FindingRepository.get_top_findings_for_hypothesis()``.

        Returns an empty list on any failure — the orchestrator degrades
        gracefully without hypotheses rather than crashing the engagement.
        """
        from config.constants import HYPOTHESIS_MAX_OUTPUT
        from metrics import increment_counter

        try:
            hypotheses = self._generate_inner(findings, engagement_id)
            increment_counter("hypothesis.generated", len(hypotheses),
                              tags={"engagement_id": engagement_id})
            return hypotheses
        except Exception as e:
            logger.error(
                "HypothesisEngine.generate() failed — returning empty list",
                extra={"engagement_id": engagement_id, "error": str(e)},
                exc_info=True,
            )
            return []

    def _generate_inner(self, findings: list[dict], engagement_id: str) -> list[dict]:
        hypotheses = []
        groups = _group_findings_for_hypotheses(findings, min_group_size=2)

    for group in groups:
        description = self._describe_group(group)
        suggested_tools = self._suggest_tools(group)
        verification_steps = self._build_verification_steps(group, suggested_tools)  # returns list[VerificationStep]

        hypotheses.append({
            "id": str(uuid4()),
            "engagement_id": engagement_id,
            "description": description,
            "root_cause_key": group["root_cause_key"],
            "confidence": self._initial_confidence(group),
            "status": "UNVERIFIED",
            "verification_steps": verification_steps,
            "finding_ids": group["finding_ids"],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": suggested_tools,
        })

    # Single-finding hypotheses — only when the finding maps to a verification
    # tool the agent wouldn't otherwise run AND verification hasn't happened yet.
    for f in findings:
        f_type = f.get("type", "")
        family = _TYPE_TO_FAMILY.get(f_type.upper(), f_type.upper())
        if family not in _VERIFICATION_TOOL_MAP:
            continue  # no tool to drive -> no hypothesis needed
        if f.get("severity") not in ("CRITICAL", "HIGH"):
            continue
        if f.get("verification_result") is not None:
            continue  # verification already ran, nothing to drive
        hypotheses.append(self._single_finding_hypothesis(f, engagement_id))

    hypotheses.sort(key=lambda h: h["confidence"], reverse=True)
    return hypotheses[:HYPOTHESIS_MAX_OUTPUT]
```

Add a `_emit_hypothesis_summary()` helper that logs the count as a structured event after generation. The summary is emitted by the orchestrator (not by the engine itself — the engine is a plain service class with no side effects):

```python
def _emit_hypothesis_summary(self, hypotheses: list[dict], engagement_id: str) -> None:
    """Log summary after generation — single source of truth for count."""
    from metrics import increment_counter

    confirmed = sum(1 for h in hypotheses if h.get("status") == "CONFIRMED")
    unverified = sum(1 for h in hypotheses if h.get("status") == "UNVERIFIED")
    logger.info(
        "HYPOTHESIS_SUMMARY",
        extra={
            "engagement_id": engagement_id,
            "total": len(hypotheses),
            "unverified": unverified,
            "confirmed": confirmed,
            "avg_confidence": round(
                sum(h.get("confidence", 0) for h in hypotheses) / len(hypotheses), 2
            ) if hypotheses else 0.0,
        },
    )
    # Wrap metric calls — metrics must never crash the caller
    try:
        increment_counter("hypothesis.generated", len(hypotheses),
                          tags={"engagement_id": engagement_id})
    except Exception:
        pass
```

Helper rules for `_describe_group()`:

Qualify descriptions with confidence since not all groups are equally strong at generation time.

| Group pattern | Description template |
|---------------|----------------------|
| Multiple XSS on same host | "Reflected XSS is possible across {host} endpoints, suggesting output encoding is missing globally ({confidence:.0%} confidence)." |
| Multiple SQLi sharing parameter | "SQL injection occurs on parameter '{param}' across {count} endpoints, suggesting a shared unparameterized query pattern ({confidence:.0%} confidence)." |
| Multiple missing auth on admin endpoints | "Administrative endpoints lack authentication, suggesting authentication middleware is misconfigured ({confidence:.0%} confidence)." |
| Mixed JWT + privilege escalation | "JWT weaknesses plus privilege-escalation findings suggest broken authorization layer ({confidence:.0%} confidence)." |
| CWE match | "Findings with CWE-{cwe} cluster on {host}, indicating a common vulnerable component ({confidence:.0%} confidence)." |

Helper method `_initial_confidence()`:

```python
def _initial_confidence(self, group: dict) -> float:
    """
    Deterministic confidence based on group strength.
    Override this method in subclasses to plug in LLM-based scoring later.
    """
    max_severity = group.get("max_severity", "INFO")
    count = group.get("finding_count", 0)
    category = group.get("category", "type_host")
    base = {"CRITICAL": 0.8, "HIGH": 0.7, "MEDIUM": 0.5, "LOW": 0.3, "INFO": 0.2}.get(max_severity, 0.5)
    # Bonus for multi-finding groups (more evidence → higher confidence)
    count_bonus = min(0.15, (count - 2) * 0.05)
    # CWE-keyed groups are stronger than type/host groups
    category_bonus = 0.1 if category == "cwe" else 0.0
    return min(1.0, base + count_bonus + category_bonus)
```

Helper rules for `_suggest_tools()`:

| Finding type(s) | Suggested tools |
|-----------------|-----------------|
| SQLi | `sqlmap`, `verification_agent` |
| XSS | `finding_verifier.verify_xss`, `verification_agent` |
| Open redirect | `finding_verifier.verify_open_redirect`, `verification_agent` |
| JWT weaknesses | `jwt_tool`, `verification_agent` |
| BOLA/IDOR | `dual_auth_scanner`, `verification_agent` |
| Exposed secrets | `credential_replay`, `verification_agent` |
| Generic HIGH/CRITICAL | `verification_agent` |

Helper method `_build_verification_steps()` — returns structured `VerificationStep` dicts so the agent has both a human-readable description AND a machine-executable tool contract:

```python
def _build_verification_steps(self, group: dict, suggested_tools: list[str]) -> list[dict]:
    steps = []
    for tool in suggested_tools:
        step = {
            "description": f"Run {tool} to verify {group.get('root_cause_key', 'unknown')}",
            "tool": tool,
            "arguments": self._default_arguments(tool, group),
            "expected": "findings_count > 0",
        }
        steps.append(step)
    return steps

def _default_arguments(self, tool: str, group: dict) -> dict:
    """Map tool name to default invocation arguments based on group metadata."""
    args: dict = {"target": group.get("affected_endpoints", [None])[0]} if group.get("affected_endpoints") else {}
    if tool == "sqlmap" and group.get("common_parameters"):
        args["parameter"] = group["common_parameters"][0]
    if tool == "finding_verifier":
        args["finding_ids"] = group.get("finding_ids", [])
    return args
```

If a `_VERIFICATION_TOOL_MAP` entry maps to multiple tools, each gets its own `VerificationStep`. The first step's tool name is also stored in `suggested_tools` for Phase 3's `_update_hypotheses_from_result()` matching.

#### Step 1.3 — No changes to FindingCorrelationEngine

The `FindingCorrelationEngine` runs inside the `ReActAgent` tool loop during the scan phase — before hypotheses have been generated. Any placeholder count would always be zero, which is worse than omitting it. Hypothesis observability lives at the orchestrator level (Step 3.1).

#### Step 1.4 — Wire into IntelligenceEngine (pass-through only)

Modify `intelligence_engine.py`:

Do NOT generate hypotheses inside `evaluate()`. Hypotheses are generated once by the orchestrator. `analyze_state()` should accept pre-generated hypotheses and pass them through in the analysis dict:

1. Modify `analyze_state()` signature:
   ```python
   def analyze_state(
       self,
       state: Any,
       enriched_findings: list[dict] | None = None,
       hypotheses: list[dict] | None = None,
   ) -> dict:
   ```
2. Add `hypotheses` to the returned analysis dict:
   ```python
   return {
       # ... existing keys ...
       "hypotheses": hypotheses or [],
   }
   ```

#### Step 1.5 — Persist in EngagementState

Modify `runtime/engagement_state.py`:

1. Change `self.hypotheses: list[str] = []` to `self.hypotheses: list[dict] = []`.
2. Add methods — note that `_bump_version()` is intentionally NOT called here: hypotheses write to Postgres directly (source of truth), and the in-memory list is a read cache. Redis carries the broader `EngagementState` snapshot which excludes the hypothesis list to avoid third-copy drift:
   ```python
   def add_hypothesis(self, hypothesis: dict):
       """Populate in-memory cache. Caller must have written to Postgres first."""
       self.hypotheses.append(hypothesis)

   def update_hypothesis(self, hypothesis_id: str, updates: dict) -> bool:
       """Update in-memory cache. Caller must have written to Postgres first."""
       for h in self.hypotheses:
           if h.get("id") == hypothesis_id:
               h.update(updates)
               h["updated_at"] = datetime.now(timezone.utc).isoformat()
               return True
       return False

   def get_active_hypotheses(self, max_count: int = 10) -> list[dict]:
        # Check in-memory cache first. If cold (worker restart / no writes yet),
        # fall back to Postgres — Redis is never consulted for hypotheses directly.
        from metrics import increment_counter

        unverified = [h for h in self.hypotheses if h.get("status") == "UNVERIFIED"]
        if not unverified:
            try:
                from database.repositories.hypothesis_repository import HypothesisRepository
                repo = HypothesisRepository()
                unverified = repo.get_by_engagement(self.engagement_id, status="UNVERIFIED")
                # Re-populate in-memory cache for next call
                self.hypotheses = unverified
                try:
                    increment_counter("hypothesis.cold_cache_fallback",
                                      tags={"engagement_id": self.engagement_id})
                except Exception:
                    pass
            except Exception as e:
                logger.warning(
                    "Could not recover hypotheses from Postgres — "
                    "agent runs without them",
                    extra={"engagement_id": self.engagement_id, "error": str(e)},
                    exc_info=True,
                )
                return []  # fail open — agent continues without hypothesis context
        unverified.sort(key=lambda h: h.get("confidence", 0), reverse=True)
        return unverified[:max_count]
    ```
3. Include `hypotheses` in `to_dict()` only — exclude from `to_snapshot_dict()` (the Redis-persisted blob) to avoid a third copy of hypothesis data. Postgres is the authoritative store.
4. Handle round-trip in `from_dict()` — only restore hypotheses that are in the dict (they won't be in snapshot dicts, but may be in in-process `to_dict()` calls).
5. **Concurrency note:** The Celery worker currently runs `ReActAgent` single-threaded per engagement, so no lock is needed on `self.hypotheses`. If parallel tool execution is added later, wrap all hypothesis mutations with a `threading.Lock`.
6. **Do NOT add hypotheses to `build_observation()`.** The observation dict is persisted to Redis via `_bump_version()`. Keeping hypotheses out of it enforces the Postgres-only rule (Q5). Consumers that need hypotheses call `get_active_hypotheses()` explicitly.
7. **Add a `hypothesis_write_failure_count: int = 0` field and a `self._hypothesis_write_failures` counter.** Increment it in `update_hypothesis()` when the caller signals a write failure. Expose it in `build_observation()` so the workflow runner can detect persistent failures and stop recommending deep_scan:
   ```python
   def build_observation(self) -> dict:
       # ... existing keys ...
       return {
           # ... existing keys ...
           "hypothesis_write_failures": self._hypothesis_write_failures,
       }
   ```
   - **Agent loop** — `ReActAgent.run()` already calls `get_active_hypotheses()` directly (Phase 3.2)
   - **TypeScript workflow runner** — populate `PlannerContext.hypotheses` from a dedicated `engagement_state.get_active_hypotheses()` call at session start and after each replan cycle, rather than from the observation dict

---

### Phase 2 — Orchestrator / Synthesis Integration (implement before agent loop)

**Why this before the agent loop:** Hypotheses must exist before the agent can act on them. Phase 2 wires `generate()` into `run_analysis()` so hypotheses are created from findings. Phase 3 then hooks the agent into those hypotheses. After Phase 2, you can verify that hypotheses are generated, persisted, and pass through the synthesis pipeline — all before touching the agent loop.

#### Step 2.1 — Generate hypotheses in `run_analysis`

Modify `orchestrator_pkg/orchestrator.py`:

1. After `snapshot, budget_mgr, findings, org_id = snapshot_svc.load_and_build(job)`, generate hypotheses using a dedicated severity-ranked query (not the full finding list — that can be 100K rows):
   ```python
   from config.constants import HYPOTHESIS_MAX_INPUT_FINDINGS

   hypotheses = []
   if is_enabled("HYPOTHESIS_ENGINE", default=False):
       from tools.hypothesis_engine import HypothesisEngine
       # Use a dedicated query that ranks by severity and caps in SQL —
       # avoids loading 100K findings just to slice 5K.
       hypothesis_findings = finding_repo.get_top_findings_for_hypothesis(
           engagement_id, limit=HYPOTHESIS_MAX_INPUT_FINDINGS,
       )
       if hypothesis_findings:
           hypothesis_engine = HypothesisEngine()
           hypotheses = hypothesis_engine.generate(
               hypothesis_findings, engagement_id,
           )
           snapshot["hypotheses"] = hypotheses
   ```
2. Persist generated hypotheses to Postgres via `HypothesisRepository` using `INSERT ... ON CONFLICT DO NOTHING` (the unique constraints on `(engagement_id, root_cause_key)` and `(engagement_id, source_finding_id)` prevent duplicates if `run_analysis()` runs concurrently). Individual failures don't block the rest — a partial hypothesis set is better than none:
   ```python
   repo = HypothesisRepository()
   persisted = []
   for h in hypotheses:
       try:
           repo.create(h)  # uses INSERT ... ON CONFLICT DO NOTHING
           persisted.append(h)
           if engagement_state is not None:
               engagement_state.add_hypothesis(h)
       except Exception as e:
           logger.warning(
               "Hypothesis not persisted — will regenerate next cycle",
               extra={"hypothesis_id": h.get("id"), "engagement_id": engagement_id},
               exc_info=True,
           )
   ```

#### Step 2.2 — Pass hypotheses through IntelligenceService

Modify `orchestrator_pkg/analysis/intelligence_service.py`:

1. In `evaluate()`, pass `snapshot.get("hypotheses", [])` as the `hypotheses` kwarg to `IntelligenceEngine.analyze_state()`. The IntelligenceEngine does NOT regenerate hypotheses — it only passes them through.
2. In `run_synthesis()`, pass `hypotheses` to `LLMSynthesizer.synthesize()`.

#### Step 2.3 — Add dedicated hypothesis update LLM call

Add a **separate** `update_hypotheses()` method to `LLMSynthesizer` — do NOT mix hypothesis updates into the existing `synthesize()` call. The synthesis call is already fragile (JSON extraction from freeform text for findings, attack paths, executive summary). Adding a second structured output contract doubles the extraction surface and couples hypothesis updates to synthesis latency. A dedicated call can timeout independently and fail without blocking the rest of the pipeline:

```python
def update_hypotheses(
    self,
    hypotheses: list[dict],
    context: str,  # recent observations, tool results, synthesis summary
) -> list[dict]:
    """Evaluate and update hypotheses via a dedicated LLM call.

    Each returned dict:
      {"hypothesis_id": "...", "status": "UNVERIFIED|CONFIRMED|REJECTED",
       "confidence": 0.85, "reasoning": "..."}

    Returns empty list on failure (fail open — hypotheses retain current state).
    """
    prompt = self._build_hypothesis_update_prompt(hypotheses, context)
    response = self._call_llm(prompt)
    if not response:
        return []
    try:
        updates = json.loads(response)
        return [validate_hypothesis_update(u) for u in updates]
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse hypothesis updates from LLM")
        return []
```

Wire this in the orchestrator after `synthesize()` returns — hypotheses are updated independently after synthesis completes. Apply each update by calling `HypothesisRepository.update()` then `engagement_state.update_hypothesis()` (same two-path write pattern from Phase 3.3).

#### Step 2.4 — Drive replan from unverified hypotheses

Modify `orchestrator_pkg/orchestrator.py`:

1. After analysis, if any hypothesis has `status == "UNVERIFIED"` and `confidence >= 0.6`, set the analysis result to recommend `next_state="deep_scan"`.
2. Add `verification_steps` to the returned job result so the TypeScript workflow runner or MCP `_replan()` can schedule a deep-scan phase.

---

### Phase 3 — Agent Loop Integration (requires hypotheses from Phase 2)

**Prerequisite:** Phase 2 must be deployed so `run_analysis()` generates and persists hypotheses before Phase 3 hooks the agent into them. Without real hypotheses, `get_active_hypotheses()` returns empty and the agent loop changes are no-ops.

#### Step 3.1 — Add hypothesis prompt section

Modify `agent/agent_prompts.py`:

1. Update `build_tool_selection_prompt()` signature to accept `hypotheses: list[dict] | None = None`.
2. Add a helper `_build_hypotheses_section(hypotheses)`:
   ```python
   def _build_hypotheses_section(hypotheses: list[dict] | None) -> str:
       if not hypotheses:
           return ""
       lines = ["=== ACTIVE HYPOTHESES ==="]
       for h in hypotheses:
           lines.append(
               f"- [{h.get('confidence', 0):.2f}] {h.get('description', '')} "
               f"(status={h.get('status', 'UNVERIFIED')}, "
               f"steps={h.get('verification_steps', [])})"
           )
       return "\n".join(lines)
   ```
3. Insert the section after memory context and before scan candidates.
4. Add instruction text: "Prefer tools that confirm or refute the highest-confidence unverified hypotheses."
5. Sanitize hypothesis descriptions and verification steps with `_sanitize_for_llm()` before rendering.

#### Step 3.2 — Pass hypotheses into ReActAgent

Modify `agent/react_agent.py`:

1. In `plan_next_action()`, accept `hypotheses: list[dict] | None = None`.
2. Forward it to `_call_llm_for_action()` and `build_tool_selection_prompt()`.
3. In `run()`, load active hypotheses from `EngagementState` when available:
   ```python
   hypotheses = []
   if self.engagement_state is not None:
       hypotheses = self.engagement_state.get_active_hypotheses(max_count=10)
   ```
4. Pass `hypotheses` into `plan_next_action()`.

#### Step 3.3 — Update hypothesis state after tool runs

In `ReActAgent.run()`, after each tool result is obtained (after `result = self.registry.call(action.tool, **action.arguments)` at line 985 in the current file), call a new helper `_update_hypotheses_from_result(tool_name, result)`. Insert it after the observation is built and before the next iteration begins:

```python
# After observation is added to history:
self._update_hypotheses_from_result(action.tool, result)
```

The helper method:

```python
def _update_hypotheses_from_result(self, tool_name: str, result: AgentResult):
    if not self.engagement_state:
        return
    from copy import deepcopy
    from exceptions import HypothesisPersistenceError
    from metrics import increment_counter
    snapshot = deepcopy(self.engagement_state.hypotheses)
    try:
        for h in self.engagement_state.hypotheses:
            if h.get("status") != "UNVERIFIED":
                continue
            suggested = h.get("suggested_tools", [])
            if tool_name not in suggested:
                continue
            hyp_id = h.get("id")
            if not hyp_id:
                continue
            if result.status.is_ok and result.findings:
                updates = {
                    "confidence": min(1.0, h.get("confidence", 0.5) + 0.1),
                    "supporting_finding_ids": h.get("supporting_finding_ids", [])
                    + [f.get("id") for f in result.findings if f.get("id")],
                }
                if updates["confidence"] >= 0.85:
                    updates["status"] = "CONFIRMED"
            elif result.status.is_error:
                updates = {
                    "confidence": max(0.0, h.get("confidence", 0.5) - 0.1),
                    "refuting_finding_ids": h.get("refuting_finding_ids", []) + [tool_name],
                }
                if updates["confidence"] <= 0.2:
                    updates["status"] = "REJECTED"
            else:
                continue
            try:
                HypothesisRepository().update(hyp_id, updates)
            except Exception as e:
                raise HypothesisPersistenceError(
                    f"Postgres update failed for {hyp_id}", original=e)
            self.engagement_state.update_hypothesis(hyp_id, updates)
            try:
                if updates.get("status") == "CONFIRMED":
                    increment_counter("hypothesis.confirmed")
                elif updates.get("status") == "REJECTED":
                    increment_counter("hypothesis.rejected")
            except Exception:
                pass
    except HypothesisPersistenceError as e:
        self.engagement_state.hypotheses = snapshot
        logger.warning(
            "Hypothesis update failed - reverted to last-known-good state",
            extra={"tool": tool_name}, exc_info=True)
        try:
            increment_counter("hypothesis.postgres_write_failure", tags={"tool": tool_name})
        except Exception:
            pass
    except Exception as e:
        self.engagement_state.hypotheses = snapshot
        logger.error(
            "Unexpected error in _update_hypotheses_from_result - reverted",
            extra={"tool": tool_name, "error": str(e)}, exc_info=True)
```

The snapshot-before-mutation pattern (shown above) ensures Postgres-first writes with in-memory cache reverting to last-known-good on failure. The `hypothesis_write_failure` counter in `build_observation()` lets the workflow runner detect persistent failures and stop recommending `deep_scan`.</parameter>


---

### Phase 4 — Verification Loop

**Note:** Persistence is already handled in Phase 2.1 (Postgres write) and Phase 3.3 (Postgres update). No additional persistence step needed here.

#### Step 4.1 — Verification tool mapping is in `models/finding_types.py`

The `_VERIFICATION_TOOL_MAP` and `_TYPE_TO_FAMILY` constants are already defined in `tools/hypothesis_engine.py` (see Step 1.2). They live in a shared `models/finding_types.py` module that both `hypothesis_engine.py` and `intelligence_engine.py` import — no duplication.

Normalize each finding's `type` to its family name via `_TYPE_TO_FAMILY.get(finding_type.upper(), finding_type.upper())`, then look up `suggested_tools` from `_VERIFICATION_TOOL_MAP` (fall back to `["verification_agent"]`).

#### Step 4.2 — VerificationAgent integration

Ensure `tools/verification_agent.py` can accept a list of hypothesis-linked findings:

```python
input_findings = getattr(ctx, "_verification_input", None)
# If _hypothesis_input is present and _verification_input is not, use hypothesis findings.
if not input_findings:
    hypotheses = getattr(ctx, "_hypothesis_input", [])
    input_findings = []
    for h in hypotheses:
        if h.get("status") == "UNVERIFIED":
            input_findings.extend(h.get("finding_ids", []))
```

This allows the orchestrator to call `verification_agent` with `extra={"hypothesis_input": active_hypotheses}`.

---

### Phase 5 — TypeScript-Side Hooks

**Important:** The observation dict explicitly does NOT carry hypotheses (Redis snapshot rule, Q5/Q7). The TypeScript workflow runner must fetch hypotheses through a dedicated channel.

**Minimal required change (do in this pass):**

- Add optional `hypotheses?: Array<{id: string, description: string, confidence: number, status: string}>` to `PlannerContext` in `Argus-Tui/packages/opencode/src/argus/planner/planner.ts`.
- Populate it from `engagement_state.get_active_hypotheses()` at session start via the `agentInit` response payload (or an MCP call). Refresh after each replan cycle.

**Future hooks (skip unless explicitly requested):**

- In `replan-rules.ts`, add rules that map high-confidence unverified hypotheses to capabilities:
  - SQLi hypothesis → `SQLI_DETECTION`
  - XSS hypothesis → `VULNERABILITY_SCANNING`
  - JWT/auth hypothesis → `JWT_ANALYSIS`
  - BOLA hypothesis → `DUAL_AUTH_TESTING`
- Verified/confirmed hypotheses can trigger `POST_EXPLOITATION` or `CREDENTIAL_REPLAY`.

---

## 4. Testing Plan

### Unit tests: `tests/test_hypothesis_engine.py`

Test cases:

1. `test_generate_empty_findings` — returns empty list, tool returns `SUCCESS_EMPTY`.
2. `test_generate_groups_xss_by_host` — two XSS findings on same host produce one hypothesis.
3. `test_generate_groups_sqli_by_parameter` — two SQLi findings on same parameter produce one hypothesis.
4. `test_single_finding_critical_hypothesis` — a lone CRITICAL finding with high confidence produces a hypothesis.
5. `test_suggested_tools_mapping` — XSS hypothesis suggests `finding_verifier`/`verification_agent`.
6. `test_hypothesis_finding_emission` — `execute()` emits `HYPOTHESIS` findings.
7. `test_feature_flag_disabled` — when flag is off, returns `SUCCESS_EMPTY`.

### Repository tests: `tests/test_hypothesis_repository.py`

1. `test_create_and_get_by_engagement`
2. `test_update_status`
3. `test_link_finding`
4. `test_get_linked_findings`

### Integration tests

1. `tests/test_intelligence_engine.py` — extend to assert `analysis["hypotheses"]` exists when flag is enabled.
2. `tests/test_finding_correlation_engine.py` — no hypothesis-related changes needed. FCE is not part of the hypothesis pipeline.
3. `tests/test_engagement_state.py` — assert `to_dict()` round-trips hypotheses.
4. `tests/test_agent_prompts.py` — assert `build_tool_selection_prompt` includes hypotheses section.

### Pipeline integration tests

**Phase 2 pipeline test** (can run as soon as Phase 2 is merged, no agent loop needed):

Add `tests/test_hypothesis_pipeline_phase2.py`:

1. Seed 3 SQLi findings → `HypothesisEngine.generate()` returns 1 hypothesis with `suggested_tools=["sqlmap", "verification_agent"]`
2. Verify hypotheses persist through `HypothesisRepository`
3. Verify `EngagementState.get_active_hypotheses()` correctly filters by status and sorts by confidence

**Phase 3 pipeline test** (requires Phase 3 to be merged):

Add `tests/test_hypothesis_pipeline_phase3.py`:

1. Load a state with pre-generated hypotheses from `EngagementState`
2. `build_tool_selection_prompt()` with that hypothesis includes `"=== ACTIVE HYPOTHESES ==="` and the SQLi description
3. Simulate a positive tool result → `_update_hypotheses_from_result()` bumps confidence and sets `status="CONFIRMED"` when threshold crossed
4. Verify `get_active_hypotheses()` returns empty when all hypotheses are CONFIRMED/REJECTED

### Regression tests

- Run `python -m pytest tests/ -m "not requires_db and not requires_redis and not e2e"`.
- Run `python -m database.migrations.runner` against a fresh Postgres container.
- Verify `_update_hypotheses_from_result()` writes to Postgres and the in-memory cache is consistent by inspecting `hypotheses` table via `HypothesisRepository` and comparing to `EngagementState.hypotheses`.

### Verifiable Success Criteria

These are machine-checkable thresholds that must hold for the feature to ship:

| Criterion | Target | How to measure |
|-----------|--------|----------------|
| `generate()` latency | p95 < 2s on 5000 findings | Wrap `generate()` with `time.perf_counter()` in integration test |
| `_update_hypotheses_from_result()` overhead | < 50ms per call | Timer in the helper body |
| Memory per engagement | < 5 MB for 20 hypotheses | `sys.getsizeof()` on `EngagementState.hypotheses` in the pipeline test |
| CONFIRMED true-positive rate | ≥ 60% | Retro analysis after 50 engagements with engine on |
| Cold-cache fallback correctness | Zero errors when Redis is flushed | Integration test that flushes Redis and calls `get_active_hypotheses()` |

If any criterion fails, the feature flag stays off and the gap is filed as a bug.

---

## 5. Observability

### Metrics (counters / histograms)

Add these to the worker's metric registry (StatsD / Prometheus):

| Metric | Type | Where to emit | Alert threshold |
|--------|------|---------------|-----------------|
| `hypothesis.generated` | Counter | End of `generate()` | — |
| `hypothesis.confirmed` | Counter | `_update_hypotheses_from_result` when status → CONFIRMED | — |
| `hypothesis.rejected` | Counter | `_update_hypotheses_from_result` when status → REJECTED | — |
| `hypothesis.generate_duration_ms` | Histogram | Wrap `generate()` body | p95 > 2000ms |
| `hypothesis.update_duration_ms` | Histogram | Wrap `_update_hypotheses_from_result` body | p95 > 50ms |
| `hypothesis.postgres_write_failure` | Counter | Exception handler in `_update_hypotheses_from_result` | > 0 in 1h |
| `hypothesis.cold_cache_fallback` | Counter | `get_active_hypotheses()` when in-memory cache is empty | — |

### Logging

- Every hypothesis creation: `logger.info("Generated hypothesis", extra={"hyp_id": ..., "engagement_id": ..., "confidence": ...})`
- Every status transition: `logger.info("Hypothesis status changed", extra={"hyp_id": ..., "from": ..., "to": ..., "confidence": ...})`
- Postgres write failure: already logged at `logger.warning` with `exc_info=True` — ensure the log shipper captures exceptions

### SLO

Once the feature flag is on by default and 100 engagements have run, require:
- `hypothesis.postgres_write_failure` = 0 over the trailing 7 days
- `hypothesis.generate_duration_ms` p95 < 2000ms over the trailing 7 days
- CONFIRMED true-positive rate ≥ 60% (measured by retro review)

---

## 6. Error Contracts

Every public method must define its error behavior. These contracts are checked in code review:

### `HypothesisEngine.generate(findings, engagement_id) → list[dict]`

| Condition | Behavior |
|-----------|----------|
| `findings` is empty | Return `[]` (no hypotheses for no evidence) |
| `findings` contains non-dict items | Log warning, skip non-dict items, process rest |
| `engagement_id` is empty | Log error, return `[]` |
| Postgres unreachable during persistence | Log warning, return generated hypotheses anyway (they survive in Redis/state) |
| Internal exception during grouping | Log error with traceback, return `[]` (fail open — the pipeline continues without hypotheses) |

### `_update_hypotheses_from_result(tool_name, result)`

| Condition | Behavior |
|-----------|----------|
| `engagement_state` is `None` | Return immediately, no-op |
| Tool name not in any hypothesis `suggested_tools` | Return immediately, no-op |
| Postgres write fails | Log warning with `exc_info=True` and `hyp_id` — Redis write has already succeeded |
| Multiple hypotheses match the same tool | Update all matching (a single tool result can affect multiple hypotheses) |

### `EngagementState.get_active_hypotheses(max_count)`

| Condition | Behavior |
|-----------|----------|
| In-memory cache has UNVERIFIED items | Return sorted slice (no PG call) |
| In-memory cache is empty, PG query succeeds | Repopulate cache, return slice |
| In-memory cache is empty, PG is unreachable | Return `[]` (fail open — agent runs without hypotheses) |
| `max_count <= 0` | Return `[]` |

### `HypothesisRepository.update(id, updates)`

| Condition | Behavior |
|-----------|----------|
| Row not found | Return `None` (caller should log at debug level — likely a race) |
| Constraint violation | Raise `IntegrityError` (should not happen — indicates schema drift) |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Hypothesis explosion (too many hypotheses) | Cap to 20 per engagement; only generate for groups ≥2 or single HIGH/CRITICAL confirmed findings. |
| LLM context overflow | Hypotheses section is placed after memory but before tools; truncate to top 10 active hypotheses. |
| Circular imports | Keep `models/hypothesis.py` free of imports from `intelligence_engine.py` or `runtime/engagement_state.py`. |
| Existing tests break because `hypotheses` field type changed | Update all tests that construct `EngagementState` directly. The default `[]` keeps most code working. |
| Pydantic model / dict impedance mismatch | **Resolved:** Use `TypedDict` instead of Pydantic. No runtime conversion needed — hypotheses stay as dicts everywhere. `validate_hypothesis()` provides guardrails at the two trust boundaries (LLM output, Postgres load) without runtime overhead on internal pass-throughs. |
| Feature flag default keeps engine off | Add `HYPOTHESIS_ENGINE` to `AUTONOMOUS_FEATURES` so `ARGUS_AUTONOMOUS=1` enables it. |
| Verification step mapping is brittle | Use canonical family map from `models/finding_types.py` (shared SSOT), not arbitrary keywords; fall back to `verification_agent` for all unmapped types. |
| Redis cache / Postgres store drift | **Resolved:** Postgres is the sole source of truth for hypotheses. `_bump_version()` is intentionally omitted from hypothesis mutations. The Redis snapshot excludes the hypothesis list. The in-memory `EngagementState.hypotheses` is a read cache populated from Postgres after each write succeeds. |
| Duplicate hypothesis generation on concurrent `run_analysis()` | Prevented by unique indexes on `(engagement_id, root_cause_key)` and `(engagement_id, source_finding_id)` with `INSERT ... ON CONFLICT DO NOTHING` in `HypothesisRepository.create()`. |
| Ephemeral hypotheses on Postgres write failure | `generate()` returns in-memory hypotheses even if Postgres creation fails. A worker crash at that point loses them permanently. **Accepted tradeoff** — the next `run_analysis()` cycle regenerates them from findings. Logged at `logger.warning`. The `hypothesis_write_failures` counter in `build_observation()` lets ops detect the pattern. |
| `_update_hypotheses_from_result` stalls agent loop | **Mitigated:** Postgres write failure skips the in-memory cache update; agent loop continues with stale but consistent state. The `hypothesis_write_failures` counter is observable from the workflow runner, which can stop recommending `deep_scan` on persistent failures. |

---

## 8. Definition of Done

- [ ] `models/hypothesis.py` defines `Hypothesis` and `VerificationStep` as `TypedDict`s with a `validate_hypothesis()` helper for trust-boundary validation.
- [ ] `models/finding_types.py` defines `_VERIFICATION_TOOL_MAP` and `_TYPE_TO_FAMILY` — shared SSOT imported by both `hypothesis_engine.py` and `intelligence_engine.py`.
- [ ] Migration `017_add_hypotheses.sql` exists (no `hypothesis_findings` link table in MVP) and applies cleanly.
- [ ] `HypothesisRepository` supports `create`, `get_by_engagement`, `update` (no `link_finding`/`get_linked_findings` in MVP).
- [ ] `tools/hypothesis_engine.py` is a **plain service class** (NOT an `AbstractTool`) — no `execute()`/`FindingBuilder`/`UnifiedToolResult`. Hypotheses travel through `EngagementState` and Postgres, not the finding stream.
- [ ] `HypothesisEngine.generate()` receives pre-ranked findings from `FindingRepository.get_top_findings_for_hypothesis()` — no internal sort or cap.
- [ ] `config/constants.py` defines `HYPOTHESIS_MAX_INPUT_FINDINGS = 5000` and `HYPOTHESIS_MAX_OUTPUT = 20`.
- [ ] Single-finding hypotheses only generate when the finding type maps to `_VERIFICATION_TOOL_MAP` AND `verification_result` is not set.
- [ ] `Orchestrator.run_analysis()` is the **single generation site** — calls `HypothesisEngine.generate()`, persists via `HypothesisRepository`, populates `EngagementState` cache, emits `HYPOTHESIS_SUMMARY`.
- [ ] `IntelligenceEngine.analyze_state()` accepts and passes through hypotheses (does NOT generate them).
- [ ] `LLMSynthesizer.update_hypotheses()` is a **dedicated LLM call** — separate from `synthesize()` with independent timeout and failure handling.
- [ ] `EngagementState` stores typed hypotheses, omits `_bump_version()` for hypothesis mutations, excludes them from Redis snapshot, exposes `hypothesis_write_failures` counter in `build_observation()`.
- [ ] `ReActAgent` includes active hypotheses in tool-selection prompts and calls `_update_hypotheses_from_result()` after each tool result.
- [ ] `_update_hypotheses_from_result()` writes to Postgres **first**, then in-memory cache. Skips cache update on Postgres failure.
- [ ] `feature_flags.py` includes `HYPOTHESIS_ENGINE` in `AUTONOMOUS_FEATURES`. No registration in `tool_definitions.py` or `run_agent_tool.py`.
- [ ] `_initial_confidence()` is overridable for future LLM-based scoring.
- [ ] Unit and integration tests pass.
- [ ] Readiness review blocker #25 is marked resolved.

---

## 9. Quick Reference: Exact Signatures to Use

### `build_tool_selection_prompt`

```python
def build_tool_selection_prompt(
    recon_context: str,
    available_tools: list[dict],
    tried_tools: set,
    observation_history: str,
    target_profile: dict | None = None,
    mode: str | None = None,
    bugbounty_context: str = "",
    priority_classes: list[str] | None = None,
    candidate_list=None,
    memory_context: str = "",
    hypotheses: list[dict] | None = None,
) -> str
```

### `analyze_state`

```python
def analyze_state(
    self,
    state: Any,
    enriched_findings: list[dict] | None = None,
    hypotheses: list[dict] | None = None,
) -> dict
```

### `LLMSynthesizer.synthesize`

```python
def synthesize(
    self,
    scored_findings: list[dict],
    attack_paths: list[dict],
    recon_context: Any = None,
    hypotheses: list[dict] | None = None,
) -> dict
```

### `EngagementState` hypothesis methods

```python
def add_hypothesis(self, hypothesis: dict) -> None
def update_hypothesis(self, hypothesis_id: str, updates: dict) -> bool
def get_active_hypotheses(self, max_count: int = 10) -> list[dict]
```

---

*End of plan. Implementation should proceed file-by-file in the order listed in Section 3, running tests after each phase.*

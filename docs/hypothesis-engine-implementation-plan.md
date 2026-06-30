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

### 1.1 Pydantic model: `argus-workers/models/hypothesis.py`

Create a new model file. Keep it dependency-light so it can be imported by `intelligence_engine.py`, `runtime/engagement_state.py`, and tools without circular imports.

```python
"""Hypothesis data model."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class HypothesisStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class Hypothesis(BaseModel):
    """
    A testable conjecture that explains a cluster of findings and proposes
    verification steps.
    """

    id: str = Field(..., description="Stable UUID for the hypothesis")
    engagement_id: str = Field(..., description="Owning engagement")
    description: str = Field(..., min_length=1, description="Human-readable causal claim")
    root_cause_key: str | None = Field(None, description="Key from root_cause.py if derived from a group")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Current confidence")
    status: HypothesisStatus = Field(default=HypothesisStatus.UNVERIFIED)
    verification_steps: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    supporting_finding_ids: list[str] = Field(default_factory=list)
    refuting_finding_ids: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list, description="Tool names that can verify/reject")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("verification_steps", "finding_ids", "supporting_finding_ids", "refuting_finding_ids", "suggested_tools", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v)
```

### 1.2 Database migration

Create `argus-workers/database/migrations/017_add_hypotheses.sql`. Note: migration `011` currently has duplicates (`011_add_target_profiles_table.sql` and `011_add_assets_table.sql`). Use `017` to avoid collisions.

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS hypotheses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    root_cause_key TEXT,
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (status IN ('UNVERIFIED', 'PARTIALLY_VERIFIED', 'CONFIRMED', 'REJECTED')),
    verification_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    supporting_finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    refuting_finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hypotheses_engagement_id ON hypotheses(engagement_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status);

-- Link table so findings can support/reject multiple hypotheses.
CREATE TABLE IF NOT EXISTS hypothesis_findings (
    hypothesis_id UUID NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    finding_id UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL DEFAULT 'support' CHECK (relationship IN ('support', 'refute')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (hypothesis_id, finding_id)
);

CREATE INDEX IF NOT EXISTS idx_hypothesis_findings_finding_id ON hypothesis_findings(finding_id);

COMMIT;
```

### 1.3 Repository: `argus-workers/database/repositories/hypothesis_repository.py`

Follow the `BaseRepository` pattern. Add CRUD for hypotheses and the link table.

Key methods:

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

    def link_finding(self, hypothesis_id: str, finding_id: str, relationship: str = "support") -> None:
        ...

    def get_linked_findings(self, hypothesis_id: str) -> list[dict]:
        ...
```

Register the table name in `database/repositories/base.py` `_ALLOWED_TABLE_NAMES` and `ALLOWED_COLUMNS` if you want to reuse `update_by_id`.

### 1.4 Optional: extend `VulnerabilityFinding`

Add an optional `hypothesis_id: str | None = None` field to `models/finding.py` only if the hypothesis engine needs to tag findings at the model layer. Prefer the `hypothesis_findings` link table for many-to-many relationships.

---

## 2. Files to Create / Modify

| Action | File | Why |
|--------|------|-----|
| Create | `models/hypothesis.py` | Pydantic data model |
| Create | `database/repositories/hypothesis_repository.py` | Persistence |
| Create | `database/migrations/017_add_hypotheses.sql` | Schema |
| Create | `tools/hypothesis_engine.py` | Agent tool implementation |
| Create | `tools/definitions/hypothesis_engine.yaml` | Tool definition |
| Create | `tests/test_hypothesis_engine.py` | Unit tests |
| Modify | `tools/correlation/root_cause.py` | Use richer grouping keys; expose `root_cause_key` to hypotheses |
| Modify | `tools/finding_correlation_engine.py` | Emit hypotheses as findings and pass them into results |
| Modify | `intelligence_engine.py` | Generate hypotheses inside `evaluate()` and `analyze_state()` |
| Modify | `runtime/engagement_state.py` | Change `hypotheses` to `list[dict]` and persist them |
| Modify | `agent/agent_prompts.py` | Add `=== ACTIVE HYPOTHESES ===` section |
| Modify | `agent/react_agent.py` | Pass hypotheses into tool-selection context |
| Modify | `orchestrator_pkg/analysis/intelligence_service.py` | Wire hypotheses through synthesis |
| Modify | `orchestrator_pkg/orchestrator.py` | Call hypothesis generation in `run_analysis` |
| Modify | `llm_synthesizer.py` | Accept and return hypothesis updates |
| Modify | `feature_flags.py` | Add `FEATURE_HYPOTHESIS_ENGINE` and add to `AUTONOMOUS_FEATURES` |
| Modify | `tool_definitions.py` | Register `hypothesis_engine` tool and add to `_AGENT_INTERNAL_TOOLS` |
| Modify | `tools/run_agent_tool.py` | Add `hypothesis_engine` to `ALLOWED_TOOLS` |
| Regenerate | `_generated_tools.py` | Run `python scripts/generate_tool_defs.py` |

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

#### Step 0.2 — Add data model and migration

1. Create `models/hypothesis.py`.
2. Create `database/migrations/017_add_hypotheses.sql`.
3. Create `database/repositories/hypothesis_repository.py`.
4. Update `database/repositories/base.py` allowlists.
5. Run `python -m database.migrations.runner` locally to verify.

#### Step 0.3 — Add tool skeleton

Create `tools/hypothesis_engine.py`:

```python
"""Hypothesis Engine — generates and updates testable hypotheses from findings."""

from __future__ import annotations

import logging
from uuid import uuid4

from feature_flags import is_enabled
from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult
from tools.correlation.root_cause import find_root_causes

logger = logging.getLogger(__name__)


class HypothesisEngine(AbstractTool):
    """Generate ranked hypotheses and verification steps from a set of findings."""

    tool_name: str = "hypothesis_engine"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)

        if not is_enabled("HYPOTHESIS_ENGINE", default=False):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        input_findings = getattr(ctx, "_hypothesis_input", None)
        if not input_findings or not isinstance(input_findings, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)
        hypotheses = self.generate(input_findings, ctx.engagement_id)

        # Emit each hypothesis as a structured finding so it survives the pipeline.
        for h in hypotheses:
            builder.info(
                "HYPOTHESIS",
                ctx.target,
                {
                    "hypothesis_id": h["id"],
                    "description": h["description"],
                    "confidence": h["confidence"],
                    "status": h["status"],
                    "verification_steps": h["verification_steps"],
                    "finding_count": len(h["finding_ids"]),
                    "suggested_tools": h.get("suggested_tools", []),
                },
            )

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def generate(self, findings: list[dict], engagement_id: str) -> list[dict]:
        """Generate hypotheses from findings. Returns plain dicts."""
        ...
```

Register it:
- `tool_definitions.py`: add `_register(ToolDefinition(...))` and add to `_AGENT_INTERNAL_TOOLS`.
- `tools/definitions/hypothesis_engine.yaml`: create YAML.
- `tools/run_agent_tool.py`: add `"hypothesis_engine"` to `ALLOWED_TOOLS`.
- Run `python scripts/generate_tool_defs.py`.

At this point the tool exists but `generate()` can return an empty list. The build should still pass.

---

### Phase 1 — Core Hypothesis Generation

#### Step 1.1 — Replace trivial root-cause grouping

Modify `tools/correlation/root_cause.py`:

- Keep `_root_cause_key()` as the deterministic fallback.
- Add a new function `generate_root_cause_groups(findings, min_group_size=2)` that returns groups with metadata:
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
def generate(self, findings: list[dict], engagement_id: str) -> list[dict]:
    hypotheses = []
    groups = generate_root_cause_groups(findings, min_group_size=2)

    for group in groups:
        description = self._describe_group(group)
        suggested_tools = self._suggest_tools(group)
        verification_steps = self._build_verification_steps(group, suggested_tools)

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

    # Single-finding hypotheses for HIGH/CRITICAL confirmed findings
    for f in findings:
        if f.get("severity") in ("CRITICAL", "HIGH") and f.get("confidence", 0) >= 0.8:
            hypotheses.append(self._single_finding_hypothesis(f, engagement_id))

    hypotheses.sort(key=lambda h: h["confidence"], reverse=True)
    return hypotheses[:20]  # cap to avoid noise
```

Helper rules for `_describe_group()`:

| Group pattern | Description template |
|---------------|----------------------|
| Multiple XSS on same host | "Reflected XSS is possible across {host} endpoints, suggesting output encoding is missing globally." |
| Multiple SQLi sharing parameter | "SQL injection occurs on parameter '{param}' across {count} endpoints, suggesting a shared unparameterized query pattern." |
| Multiple missing auth on admin endpoints | "Administrative endpoints lack authentication, suggesting authentication middleware is misconfigured." |
| Mixed JWT + privilege escalation | "JWT weaknesses plus privilege-escalation findings suggest broken authorization layer." |
| CWE match | "Findings with CWE-{cwe} cluster on {host}, indicating a common vulnerable component." |

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

#### Step 1.3 — Wire into FindingCorrelationEngine

Modify `tools/finding_correlation_engine.py`:

```python
from tools.hypothesis_engine import HypothesisEngine

# After root_cause/attack_chain/rank:
engine = HypothesisEngine()
hypotheses = engine.generate(unique_findings, ctx.engagement_id)

# Add hypothesis findings to result
for h in hypotheses:
    builder.info("HYPOTHESIS", ctx.target, { ... })
```

Also add `hypotheses_count` to the `CORRELATION_SUMMARY` finding.

#### Step 1.4 — Wire into IntelligenceEngine

Modify `intelligence_engine.py`:

1. Add import:
   ```python
   from tools.hypothesis_engine import HypothesisEngine
   ```
2. In `evaluate()`, after enrichment and before `analyze_state()`:
   ```python
   hypotheses = []
   if is_enabled("HYPOTHESIS_ENGINE", default=False):
       hypothesis_engine = HypothesisEngine()
       hypotheses = hypothesis_engine.generate(enriched_findings, snapshot.get("engagement_id"))
   ```
3. Pass `hypotheses` into `analyze_state()`:
   ```python
   analysis = self.analyze_state(
       snapshot,
       enriched_findings=enriched_findings,
       hypotheses=hypotheses,
   )
   ```
4. Modify `analyze_state()` signature:
   ```python
   def analyze_state(
       self,
       state: Any,
       enriched_findings: list[dict] | None = None,
       hypotheses: list[dict] | None = None,
   ) -> dict:
   ```
5. Add `hypotheses` to the returned analysis dict.
6. Add `hypotheses` to the `evaluate()` return dict.

#### Step 1.5 — Persist in EngagementState

Modify `runtime/engagement_state.py`:

1. Change `self.hypotheses: list[str] = []` to `self.hypotheses: list[dict] = []`.
2. Add methods:
   ```python
   def add_hypothesis(self, hypothesis: dict):
       self.hypotheses.append(hypothesis)
       self._bump_version()

   def update_hypothesis(self, hypothesis_id: str, updates: dict) -> bool:
       for h in self.hypotheses:
           if h.get("id") == hypothesis_id:
               h.update(updates)
               h["updated_at"] = datetime.now(timezone.utc).isoformat()
               self._bump_version()
               return True
       return False

   def get_active_hypotheses(self, max_count: int = 10) -> list[dict]:
       unverified = [h for h in self.hypotheses if h.get("status") == "UNVERIFIED"]
       unverified.sort(key=lambda h: h.get("confidence", 0), reverse=True)
       return unverified[:max_count]
   ```
3. Include `hypotheses` in `to_dict()` and `to_snapshot_dict()`.
4. Handle round-trip in `from_dict()`.

---

### Phase 2 — Agent Loop Integration

#### Step 2.1 — Add hypothesis prompt section

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

#### Step 2.2 — Pass hypotheses into ReActAgent

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

#### Step 2.3 — Update hypothesis state after tool runs

In `ReActAgent.run()`, after each tool result is summarized, call a new helper `_update_hypotheses_from_result(tool_name, result)`:

```python
def _update_hypotheses_from_result(self, tool_name: str, result: AgentResult):
    if not self.engagement_state:
        return
    for h in self.engagement_state.hypotheses:
        if h.get("status") != "UNVERIFIED":
            continue
        suggested = h.get("suggested_tools", [])
        if tool_name in suggested:
            if result.status.is_ok and result.findings:
                h["supporting_finding_ids"].extend([f.get("id") for f in result.findings if f.get("id")])
                h["confidence"] = min(1.0, h.get("confidence", 0.5) + 0.1)
                if h["confidence"] >= 0.85:
                    h["status"] = "CONFIRMED"
            elif result.status.is_error:
                h["refuting_finding_ids"].append(tool_name)
                h["confidence"] = max(0.0, h.get("confidence", 0.5) - 0.1)
                if h["confidence"] <= 0.2:
                    h["status"] = "REJECTED"
    self.engagement_state._bump_version()
```

This is intentionally simple for the first iteration. More sophisticated update logic can come later.

---

### Phase 3 — Orchestrator / Synthesis Integration

#### Step 3.1 — Generate hypotheses in `run_analysis`

Modify `orchestrator_pkg/orchestrator.py`:

1. After `snapshot, budget_mgr, findings, org_id = snapshot_svc.load_and_build(job)`, generate hypotheses:
   ```python
   hypotheses = []
   if is_enabled("HYPOTHESIS_ENGINE", default=False) and findings:
       from tools.hypothesis_engine import HypothesisEngine
       hypothesis_engine = HypothesisEngine()
       hypotheses = hypothesis_engine.generate(findings, job.get("engagement_id"))
       snapshot["hypotheses"] = hypotheses
   ```
2. Persist generated hypotheses to the database via `HypothesisRepository`.
3. If `EngagementState` is available in the snapshot, write hypotheses into it.

#### Step 3.2 — Pass hypotheses through IntelligenceService

Modify `orchestrator_pkg/analysis/intelligence_service.py`:

1. In `evaluate()`, pass `snapshot.get("hypotheses", [])` to `IntelligenceEngine.evaluate()` if the engine supports it, or rely on the engine to regenerate them.
2. In `run_synthesis()`, pass `hypotheses` to `LLMSynthesizer.synthesize()`.

#### Step 3.3 — Extend LLMSynthesizer

Modify `llm_synthesizer.py`:

1. Update `synthesize()` signature:
   ```python
   def synthesize(
       self,
       scored_findings: list[dict],
       attack_paths: list[dict],
       recon_context: Any = None,
       hypotheses: list[dict] | None = None,
   ) -> dict:
   ```
2. Update `build_synthesis_prompt()` to include a `=== HYPOTHESES ===` section.
3. Add a structured output key `hypothesis_updates` to the expected JSON. The LLM should return a list of:
   ```json
   {
     "hypothesis_id": "...",
     "status": "CONFIRMED|REJECTED|PARTIALLY_VERIFIED|UNVERIFIED",
     "confidence": 0.85,
     "reasoning": "..."
   }
   ```
4. Apply updates to the stored hypotheses and the engagement state.

#### Step 3.4 — Drive replan from unverified hypotheses

Modify `orchestrator_pkg/orchestrator.py`:

1. After analysis, if any hypothesis has `status == "UNVERIFIED"` and `confidence >= 0.6`, set the analysis result to recommend `next_state="deep_scan"`.
2. Add `verification_steps` to the returned job result so the TypeScript workflow runner or MCP `_replan()` can schedule a deep-scan phase.

---

### Phase 4 — Persistence and Verification Loop

#### Step 4.1 — Save hypotheses to Postgres

In the orchestrator's `run_analysis`, after hypothesis generation:

```python
from database.repositories.hypothesis_repository import HypothesisRepository

repo = HypothesisRepository()
for h in hypotheses:
    repo.create(h)
```

#### Step 4.2 — Map verification steps to actual tools

In `tools/hypothesis_engine.py`, add a mapping from hypothesis patterns to concrete verification tools:

```python
_VERIFICATION_TOOL_MAP = {
    "sql-injection": ["sqlmap", "verification_agent"],
    "sqli": ["sqlmap", "verification_agent"],
    "xss": ["finding_verifier", "verification_agent"],
    "cross-site-scripting": ["finding_verifier", "verification_agent"],
    "open-redirect": ["finding_verifier", "verification_agent"],
    "jwt": ["jwt_tool", "verification_agent"],
    "bola": ["dual_auth_scanner", "verification_agent"],
    "idor": ["dual_auth_scanner", "verification_agent"],
    "exposed_secret": ["credential_replay", "verification_agent"],
}
```

Use keyword matching against `description` + finding `type` values to populate `suggested_tools`.

#### Step 4.3 — VerificationAgent integration

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

### Phase 5 — TypeScript-Side Hooks (documented, optional for first pass)

The Python-side changes are sufficient for the worker/agent loop. The TypeScript workflow runner can consume hypotheses once they are emitted as `HYPOTHESIS` findings and the analysis result recommends `deep_scan`.

Document these future hooks in the plan:

- Add `hypotheses: Hypothesis[]` to `PlannerContext` in `Argus-Tui/packages/opencode/src/argus/planner/planner.ts`.
- In `replan-rules.ts`, add rules that map high-confidence unverified hypotheses to capabilities:
  - SQLi hypothesis → `SQLI_DETECTION`
  - XSS hypothesis → `VULNERABILITY_SCANNING`
  - JWT/auth hypothesis → `JWT_ANALYSIS`
  - BOLA hypothesis → `DUAL_AUTH_TESTING`
- Verified/confirmed hypotheses can trigger `POST_EXPLOITATION` or `CREDENTIAL_REPLAY`.

Do not implement TypeScript changes in this pass unless explicitly requested.

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
2. `tests/test_finding_correlation_engine.py` — assert `CORRELATION_SUMMARY` includes `hypotheses_count`.
3. `tests/test_engagement_state.py` — assert `to_dict()` round-trips hypotheses.
4. `tests/test_agent_prompts.py` — assert `build_tool_selection_prompt` includes hypotheses section.

### Regression tests

- Run `python -m pytest tests/ -m "not requires_db and not requires_redis and not e2e"`.
- Run `python scripts/generate_tool_defs.py` and verify `_generated_tools.py` is updated.
- Run `python -m database.migrations.runner` against a fresh Postgres container.

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Hypothesis explosion (too many hypotheses) | Cap to 20 per engagement; only generate for groups ≥2 or single HIGH/CRITICAL confirmed findings. |
| LLM context overflow | Hypotheses section is placed after memory but before tools; truncate to top 10 active hypotheses. |
| Circular imports | Keep `models/hypothesis.py` free of imports from `intelligence_engine.py` or `runtime/engagement_state.py`. |
| Existing tests break because `hypotheses` field type changed | Update all tests that construct `EngagementState` directly. The default `[]` keeps most code working. |
| Feature flag default keeps engine off | Add `HYPOTHESIS_ENGINE` to `AUTONOMOUS_FEATURES` so `ARGUS_AUTONOMOUS=1` enables it. |
| Verification step mapping is brittle | Use keyword matching, not exact type strings; fall back to `verification_agent` for all unmapped types. |

---

## 6. Definition of Done

- [ ] `models/hypothesis.py` exists and validates.
- [ ] Migration `017_add_hypotheses.sql` exists and applies cleanly.
- [ ] `HypothesisRepository` supports create/get/update/link.
- [ ] `tools/hypothesis_engine.py` generates deterministic hypotheses from findings.
- [ ] `FindingCorrelationEngine` emits `HYPOTHESIS` findings.
- [ ] `IntelligenceEngine.evaluate()` returns hypotheses in the result.
- [ ] `EngagementState` stores typed hypotheses, round-trips them, and exposes `get_active_hypotheses()`.
- [ ] `ReActAgent` includes active hypotheses in tool-selection prompts.
- [ ] `LLMSynthesizer` accepts hypotheses and returns `hypothesis_updates`.
- [ ] `Orchestrator.run_analysis()` generates hypotheses and recommends `deep_scan` for high-confidence unverified ones.
- [ ] `feature_flags.py` includes `HYPOTHESIS_ENGINE` in `AUTONOMOUS_FEATURES`.
- [ ] Tool is registered in `tool_definitions.py`, YAML, `run_agent_tool.py`, and `_generated_tools.py`.
- [ ] Unit and integration tests pass.
- [ ] Readiness review blocker #25 is marked resolved.

---

## 7. Quick Reference: Exact Signatures to Use

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

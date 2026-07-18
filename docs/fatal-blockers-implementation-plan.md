# Implementation Plan: Three Fatal Autonomy Blockers

> **Date:** 2026-07-18  
> **Scope:** Concrete code changes for the 3 fatal blockers identified in `docs/autonomy-blockers.md`  
> **Files affected:** ~15 existing files, 5 new modules  
> **Phases:** Each blocker is broken into incremental, testable phases

---

## Table of Contents

1. [Blocker #1 — Meta-Cognition Layer](#blocker-1--meta-cognition-layer)
2. [Blocker #2 — Cross-Scan Learning](#blocker-2--cross-scan-learning)
3. [Blocker #3 — Shadow Mode Convergence](#blocker-3--shadow-mode-convergence)
4. [Implementation Order & Dependencies](#implementation-order--dependencies)

---

## Blocker #1 — Meta-Cognition Layer

### The Problem

The system cannot distinguish between "I found nothing because the target is clean"
and "I found nothing because my LLM is down and my deterministic fallback is dumb."
When the LLM fails, `DeterministicRuntime` runs a linear for-loop over tools with
zero adaptation. The system never knows it's operating in degraded mode.

### Design

Add a `DegradationAwareness` module that tracks:
1. **LLM availability rate** — what % of LLM calls succeeded in the last N attempts
2. **Deterministic fallback usage** — what % of tool selections used the fallback
3. **Confidence calibration** — dynamic signal quality per tool per target type
4. **Adaptive behavior** — when degraded, reduce scope/increase coverage criteria

### Phase 1: Degradation Metrics Module

**New file:** `argus-workers/runtime/degradation_awareness.py`

```python
"""
DegradationAwareness — The system's sense of self.

Tracks runtime health metrics across multiple dimensions and provides
a unified "am I operating normally?" answer. The agent loop uses this
to adjust its behavior when the system is degraded.

Usage:
    da = DegradationAwareness(engagement_id)
    da.record_llm_result(success=True)
    da.record_tool_result(tool_name="nuclei", findings=5)
    status = da.get_status()  # "healthy" | "degraded" | "critical"
"""

import time
import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Rolling window for metrics
_LLM_WINDOW_SIZE = 20       # last 20 LLM calls
_TOOL_WINDOW_SIZE = 50      # last 50 tool calls

class DegradationLevel:
    HEALTHY = "healthy"      # LLM working, tools producing findings
    DEGRADED = "degraded"    # LLM failing or no findings trend
    CRITICAL = "critical"    # Both LLM and tools failing

@dataclass
class DegradationStatus:
    level: str = DegradationLevel.HEALTHY
    llm_success_rate: float = 1.0
    llm_window_size: int = 0
    tool_finding_rate: float = 0.0
    tool_window_size: int = 0
    consecutive_low_signal: int = 0
    recommended_action: str = ""


class DegradationAwareness:
    """Tracks runtime health and recommends adaptive actions."""

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self._llm_results: deque[bool] = deque(maxlen=_LLM_WINDOW_SIZE)
        self._tool_finding_counts: deque[int] = deque(maxlen=_TOOL_WINDOW_SIZE)
        self._consecutive_low_signal = 0
        self._last_llm_success_rate = 1.0

    def record_llm_result(self, success: bool):
        """Record whether the last LLM call succeeded or failed."""
        self._llm_results.append(success)
        if success:
            self._consecutive_low_signal = 0
        else:
            self._consecutive_low_signal += 1

    def record_tool_result(self, tool_name: str, findings_count: int):
        """Record how many findings a tool produced."""
        self._tool_finding_counts.append(findings_count)

    def get_llm_success_rate(self) -> float:
        """Fraction of successful LLM calls in the rolling window."""
        if not self._llm_results:
            return 1.0  # Assume healthy when no data
        return sum(self._llm_results) / len(self._llm_results)

    def get_tool_finding_rate(self) -> float:
        """Fraction of tools that produced at least 1 finding."""
        if not self._tool_finding_counts:
            return 0.5  # Neutral when no data
        return sum(1 for c in self._tool_finding_counts if c > 0) / len(self._tool_finding_counts)

    def get_status(self) -> DegradationStatus:
        """Compute unified status with recommended action."""
        llm_rate = self.get_llm_success_rate()
        tool_rate = self.get_tool_finding_rate()

        status = DegradationStatus(
            llm_success_rate=round(llm_rate, 2),
            llm_window_size=len(self._llm_results),
            tool_finding_rate=round(tool_rate, 2),
            tool_window_size=len(self._tool_finding_counts),
            consecutive_low_signal=self._consecutive_low_signal,
        )

        # Decision logic
        if llm_rate < 0.3 and tool_rate < 0.1:
            status.level = DegradationLevel.CRITICAL
            status.recommended_action = (
                "LLM and tools both failing. Recommend stopping engagement "
                "and checking infrastructure."
            )
        elif llm_rate < 0.5:
            status.level = DegradationLevel.DEGRADED
            status.recommended_action = (
                "LLM success rate below 50%. Switching to deterministic "
                "tool ordering with expanded coverage criteria."
            )
        elif tool_rate < 0.2 and len(self._tool_finding_counts) >= 10:
            status.level = DegradationLevel.DEGRADED
            status.recommended_action = (
                "Low finding rate despite functioning LLM. "
                "Consider broadening scope or switching attack strategies."
            )
        else:
            status.level = DegradationLevel.HEALTHY
            status.recommended_action = ""

        self._last_llm_success_rate = llm_rate
        return status
```

### Phase 2: Integrate DegradationAwareness into ReActAgent

**Modify:** `argus-workers/agent/react_agent.py`

Changes:

1. Add `degradation_awareness` parameter to `__init__`:
```python
def __init__(self, ..., degradation_awareness=None):
    ...
    self.degradation_awareness = degradation_awareness or DegradationAwareness(engagement_id or "")
```

2. Record LLM results in `plan_next_action()` — after every LLM call attempt:
```python
# In plan_next_action(), after LLM call:
if self.degradation_awareness:
    self.degradation_awareness.record_llm_result(action is not None)
```

3. Record tool results in `run()` — after every tool execution:
```python
# In run(), after result = self.registry.call(...):
if self.degradation_awareness:
    finding_count = len(getattr(result, 'findings', []) or [])
    self.degradation_awareness.record_tool_result(action.tool, finding_count)
```

4. Check degradation before each iteration — add stop/degrade logic:
```python
# At the top of the iteration loop, after the existing _cancelled check:
if self.degradation_awareness:
    da_status = self.degradation_awareness.get_status()
    if da_status.level == "critical":
        logger.warning("DegradationAwareness: %s — stopping agent", da_status.recommended_action)
        break
```

### Phase 3: Adaptive Stopping Criteria

**Modify:** `argus-workers/agent/react_agent.py` — `run()` method

Replace the current fixed `empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP`
with adaptive logic:

```python
# Replace hardcoded empty_output detection with:
if self.degradation_awareness:
    status = self.degradation_awareness.get_status()
    if status.level == DegradationLevel.DEGRADED:
        # When degraded, require more evidence before stopping
        if len(tried_tools) >= 8 and empty_output_consecutive >= 6:
            logger.info("Degraded mode: stopping after %d empty tools", empty_output_consecutive)
            break
    else:
        # Normal mode: use configured threshold
        if empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP and len(tried_tools) >= 4:
            break
else:
    # Original behavior when DegradationAwareness is not available
    if empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP and len(tried_tools) >= 4:
        break
```

### Phase 4: Dynamic Coverage Criteria in Agent Prompts

**Modify:** `argus-workers/agent/agent_prompts.py`

When the system is degraded, inject stricter stopping rules so the LLM
does more thorough checks before declaring completion:

```python
def build_stopping_rules(degradation_level: str = "healthy") -> str:
    """Return appropriate stopping rules based on system health."""
    if degradation_level == "degraded":
        return f"""
CRITICAL — SYSTEM RUNNING IN DEGRADED MODE:
The LLM is experiencing reduced availability. Tool selection may be
less intelligent than usual. Compensate by:
  1. Running ALL available tools for the detected tech stack
  2. NEVER stopping after fewer than 8 tool executions
  3. Verifying findings with at least 2 different tools when possible
  4. Accepting that some vulnerability classes may be missed
"""
    return WEBAPP_STOPPING_RULES  # Original rules
```

### Phase 5: Health Server Integration

**Modify:** `argus-workers/health_server.py`

Add degradation metrics to the `/metrics` endpoint:

```python
# In _collect_metrics():
if self._engagement_id and hasattr(self, '_degradation_awareness'):
    da_status = self._degradation_awareness.get_status()
    metrics["degradation"] = {
        "level": da_status.level,
        "llm_success_rate": da_status.llm_success_rate,
        "tool_finding_rate": da_status.tool_finding_rate,
        "consecutive_low_signal": da_status.consecutive_low_signal,
        "recommended_action": da_status.recommended_action,
    }
```

### Testing Phase 1-5

```python
# tests/test_degradation_awareness.py
class TestDegradationAwareness:
    def test_healthy_when_llm_succeeding(self):
        da = DegradationAwareness("eng-1")
        for _ in range(10):
            da.record_llm_result(success=True)
        assert da.get_status().level == "healthy"

    def test_degraded_when_llm_failing(self):
        da = DegradationAwareness("eng-1")
        for _ in range(10):
            da.record_llm_result(success=False)  # 0% success
        assert da.get_status().level == "degraded"

    def test_critical_when_everything_failing(self):
        da = DegradationAwareness("eng-1")
        for _ in range(10):
            da.record_llm_result(success=False)
            da.record_tool_result("nuclei", 0)
        assert da.get_status().level == "critical"
```

---

## Blocker #2 — Cross-Scan Learning

### The Problem

The `MemoryRetriever._get_long_term()` queries by `engagement_id` — not by target URL.
Every scan of the same target starts from zero. The `TargetProfileRepository` exists
and correctly stores profiles keyed by `(org_id, target_domain)`, but the memory
retrieval path queries by the current engagement only.

### Design

Fix the long-term memory retrieval to query by **target domain** instead of
**engagement ID**. Add a Target Intelligence service that:
1. Queries profiles by domain at engagement start
2. Updates profiles at engagement completion
3. Exposes the profile as an LLM-visible context block

### Phase 1: Fix MemoryRetriever Long-Term Query

**Modify:** `argus-workers/runtime/memory.py` — `_get_long_term()`

```python
def _get_long_term(self, state: Any) -> dict:
    """Long-term: target profile from target_profiles table.
    
    FIX: Query by org_id + domain (extracted from engagement),
    NOT by engagement_id. This enables cross-scan learning.
    """
    engagement_id = getattr(state, "engagement_id", "")
    if not engagement_id or not self.connection_string:
        return {}
    
    try:
        # Step 1: Resolve the engagement to get org_id and target_url
        from database.connection import db_cursor
        
        with db_cursor() as cursor:
            cursor.execute(
                "SELECT org_id, target_url FROM engagements WHERE id = %s",
                (engagement_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {}
            org_id, target_url = row
        
        if not org_id or not target_url:
            return {}
        
        # Step 2: Extract domain from target_url
        from urllib.parse import urlparse
        domain = urlparse(target_url).netloc or target_url.split("/")[0]
        
        # Step 3: Query profile by (org_id, domain) — cross-scan!
        from database.repositories.target_profile_repository import (
            TargetProfileRepository,
        )
        repo = TargetProfileRepository()
        profile = repo.get_profile(org_id, domain)
        
        if profile and hasattr(profile, "to_dict"):
            return profile.to_dict()
        if isinstance(profile, dict):
            return profile
            
    except Exception as e:
        logger.debug("Long-term memory retrieval failed: %s", e)
    return {}
```

### Phase 2: Auto-Upsert Profiles After Scan Completion

**Modify:** `argus-workers/orchestrator_pkg/orchestrator.py` — after reporting phase

Add a profile upsert call at the end of the engagement lifecycle:

```python
# In run_reporting() or run_analysis(), after all phases complete:
def _upsert_target_profile(self, job: dict, findings: list[dict]):
    """Auto-save target profile after scan completion."""
    try:
        from database.repositories.target_profile_repository import (
            TargetProfileRepository,
        )
        org_id = self._get_org_id()
        target_url = job.get("target") or (
            job.get("targets", [None])[0] if job.get("targets") else None
        )
        if org_id and target_url:
            repo = TargetProfileRepository()
            repo.upsert_from_engagement(
                org_id=org_id,
                target_url=target_url,
                engagement_id=self.engagement_id,
                recon_context=getattr(self, 'recon_context', None),
                findings=findings,
            )
    except Exception as e:
        logger.warning("Failed to upsert target profile (non-fatal): %s", e)
```

### Phase 3: Tool Accuracy Feedback

**Modify:** `argus-workers/tools/tool_runner.py` or `argus-workers/intelligence_engine.py`

Track which tools produce false positives vs. confirmed findings, so the profile
can record `noisy_tools` and `best_tools`:

```python
# In intelligence_engine.py, during finding evaluation:
def _compute_tool_accuracy(self, scored_findings: list[dict]) -> dict[str, float]:
    """Compute per-tool false positive rate from scored findings."""
    tool_stats: dict[str, dict[str, int]] = {}
    for f in scored_findings:
        tool = f.get("source_tool", "unknown")
        fp_likelihood = f.get("fp_likelihood", 0.0)
        if tool not in tool_stats:
            tool_stats[tool] = {"total": 0, "fp_estimated": 0}
        tool_stats[tool]["total"] += 1
        if fp_likelihood > 0.5:
            tool_stats[tool]["fp_estimated"] += 1
    
    return {
        tool: stats["fp_estimated"] / max(stats["total"], 1)
        for tool, stats in tool_stats.items()
    }
```

Pass the result to `TargetProfileRepository.upsert_from_engagement()`.

### Phase 4: LLM Prompt Injection from Profile

**Modify:** `argus-workers/agent/agent_prompts.py` — `build_tool_selection_prompt()`

The profile is already used when `target_profile` is provided (Section 0 of the prompt).
The fix in Phase 1 ensures the profile is actually populated. This phase adds
**strategic priority ordering** based on past results:

```python
# In build_tool_selection_prompt(), after "=== WHAT WE KNOW ABOUT THIS TARGET ===":
if target_profile and target_profile.get("best_tools"):
    # Reorder available tools so best-performing tools appear first
    best_tool_names = [t["tool"] for t in target_profile["best_tools"][:5]]
    noisy_tool_names = set(target_profile.get("noisy_tools", [])[:5])
    
    # Add instruction to the prompt
    strategy_hint = (
        "\n=== STRATEGY FROM PAST SCANS ===\n"
        f"Tools that found findings before: {', '.join(best_tool_names)}. "
        f"Prioritize these.\n"
    )
    if noisy_tool_names:
        strategy_hint += (
            f"Tools that were noisy/FP before: {', '.join(noisy_tool_names)}. "
            f"Run these last or skip if coverage is sufficient.\n"
        )
    # Inject before the tool catalogue
    prompt = strategy_hint + prompt
```

### Testing Phase 1-4

```python
# tests/test_cross_scan_learning.py
class TestCrossScanLearning:
    def test_long_term_queries_by_domain_not_engagement(self, monkeypatch):
        """Verify the fix: _get_long_term resolves engagement->domain->profile."""
        retriever = MemoryRetriever("postgresql://localhost:5432/test")
        
        # Mock the DB to return org_id + target_url
        def mock_cursor():
            class MockCursor:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def execute(self, query, params): pass
                def fetchone(self):
                    return ("org-123", "https://example.com")
            return MockCursor()
        
        monkeypatch.setattr("database.connection.db_cursor", mock_cursor)
        
        # Mock the profile repo to verify it's called with (org_id, domain)
        class MockRepo:
            def get_profile(self, org_id, domain):
                assert org_id == "org-123"
                assert domain == "example.com"
                return {"total_scans": 3, "best_tools": ...}
        
        monkeypatch.setattr(
            "runtime.memory.TargetProfileRepository",
            lambda: MockRepo(),
        )
        
        state = MagicMock(engagement_id="eng-1")
        profile = retriever._get_long_term(state)
        assert profile["total_scans"] == 3

    def test_intelligence_selects_best_tools_from_profile(self):
        """Profile data feeds into tool selection prioritization."""
        ...
```

---

## Blocker #3 — Shadow Mode Convergence

### The Problem

Shadow comparison counters use `threading.Lock()` which doesn't synchronize across
Celery worker processes. The "100 consecutive successes before flipping" requirement
can never converge in a multi-worker deployment.

### Design

Replace per-process in-memory counters with a **Postgres-backed stats table** that
uses atomic `UPDATE ... SET consecutive = consecutive + 1 WHERE ...` operations.
Add a `shadow_mode_stats` table with an auto-reset-on-mismatch trigger.

### Phase 1: Database Migration

**New migration:** `argus-workers/database/migrations/010_shadow_mode_stats.py`

```sql
CREATE TABLE IF NOT EXISTS shadow_mode_stats (
    phase VARCHAR(64) NOT NULL,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    total_mismatches INTEGER NOT NULL DEFAULT 0,
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_result VARCHAR(16) NOT NULL DEFAULT 'none',  -- 'match', 'mismatch', 'none'
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (phase)
);
```

### Phase 2: Rewrite Shadow Mode with DB Backend

**Modify:** `argus-workers/runtime/shadow_mode.py`

Replace the in-memory counters with database operations:

```python
"""
Shadow-Mode Validation — DB-backed counters for cross-worker convergence.

Replaces the per-process threading.Lock() counters with Postgres atomic
UPDATE operations. This ensures shadow stats converge across all Celery
workers, enabling the "100 consecutive successes" requirement.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def shadow_compare(
    phase: str,
    engagement_id: str,
    new_result: Any,
    old_path_fn: Callable[[], Any],
    key_fields: list[str] | None = None,
) -> None:
    """
    Run shadow comparison with DB-backed counters.
    
    Uses atomic UPDATE ... RETURNING to safely increment consecutive_successes
    across all workers. On mismatch, resets to 0 in the same transaction.
    """
    try:
        old_result = old_path_fn()
    except Exception as e:
        logger.warning(
            "SHADOW_MISMATCH: phase=%s engagement=%s — old path raised: %s",
            phase, engagement_id, e,
        )
        _update_stats_db(phase, match=False)
        return

    # Compare using hashes
    if (key_fields is not None
        and isinstance(new_result, dict)
        and isinstance(old_result, dict)):
        new_subset = {k: new_result.get(k) for k in key_fields if k in new_result}
        old_subset = {k: old_result.get(k) for k in key_fields if k in old_result}
        match = _compute_hash(new_subset) == _compute_hash(old_subset)
    else:
        match = _compute_hash(new_result) == _compute_hash(old_result)

    _update_stats_db(phase, match=match)
    
    if match:
        logger.debug("SHADOW_OK: phase=%s engagement=%s", phase, engagement_id)
    else:
        logger.warning(
            "SHADOW_MISMATCH: phase=%s engagement=%s — outputs differ",
            phase, engagement_id,
        )


def _compute_hash(obj: Any) -> str:
    """Compute a stable hash for comparison purposes."""
    normalized = _normalize_for_comparison(obj)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _normalize_for_comparison(obj: Any) -> str:
    """Normalize an object to a stable string for comparison."""
    try:
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, sort_keys=True, default=str)
        elif hasattr(obj, "to_dict"):
            return json.dumps(obj.to_dict(), sort_keys=True, default=str)
        elif hasattr(obj, "__dict__"):
            return json.dumps(obj.__dict__, sort_keys=True, default=str)
        else:
            return str(obj)
    except (TypeError, ValueError):
        return str(obj)


def _update_stats_db(phase: str, match: bool) -> None:
    """
    Atomically update shadow stats in Postgres.
    
    On match:   consecutive_successes += 1
    On mismatch: consecutive_successes = 0, total_mismatches += 1
    
    Uses a single atomic UPDATE to prevent race conditions across workers.
    """
    try:
        from database.connection import db_cursor
        
        with db_cursor(commit=True) as cursor:
            if match:
                cursor.execute(
                    """
                    INSERT INTO shadow_mode_stats 
                        (phase, consecutive_successes, total_mismatches, 
                         last_run_at, last_result, updated_at)
                    VALUES (%s, 1, 0, NOW(), 'match', NOW())
                    ON CONFLICT (phase) DO UPDATE SET
                        consecutive_successes = shadow_mode_stats.consecutive_successes + 1,
                        last_run_at = NOW(),
                        last_result = 'match',
                        updated_at = NOW()
                    """,
                    (phase,),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO shadow_mode_stats 
                        (phase, consecutive_successes, total_mismatches,
                         last_run_at, last_result, updated_at)
                    VALUES (%s, 0, 1, NOW(), 'mismatch', NOW())
                    ON CONFLICT (phase) DO UPDATE SET
                        consecutive_successes = 0,
                        total_mismatches = shadow_mode_stats.total_mismatches + 1,
                        last_run_at = NOW(),
                        last_result = 'mismatch',
                        updated_at = NOW()
                    """,
                    (phase,),
                )
    except Exception as e:
        logger.error("Failed to update shadow stats in DB: %s", e)


def get_shadow_stats(phase: str | None = None) -> dict:
    """Get shadow-mode validation stats from DB."""
    try:
        from database.connection import db_cursor
        
        with db_cursor() as cursor:
            if phase:
                cursor.execute(
                    "SELECT * FROM shadow_mode_stats WHERE phase = %s",
                    (phase,),
                )
                columns = [desc[0] for desc in cursor.description]
                row = cursor.fetchone()
                return dict(zip(columns, row)) if row else {
                    "phase": phase, "consecutive_successes": 0, "total_mismatches": 0
                }
            else:
                cursor.execute("SELECT * FROM shadow_mode_stats ORDER BY phase")
                columns = [desc[0] for desc in cursor.description]
                return {
                    row[0]: dict(zip(columns, row))
                    for row in cursor.fetchall()
                }
    except Exception as e:
        logger.error("Failed to read shadow stats: %s", e)
        return {"error": str(e)}


def get_consecutive_successes(phase: str) -> int:
    """Quick accessor for the consecutive successes counter."""
    stats = get_shadow_stats(phase)
    if isinstance(stats, dict):
        return stats.get("consecutive_successes", 0)
    # When phase is specified, get_shadow_stats returns a flat dict
    return stats.get("consecutive_successes", 0)


def reset_shadow_stats(phase: str | None = None):
    """Reset shadow-mode statistics (for testing)."""
    try:
        from database.connection import db_cursor
        
        with db_cursor(commit=True) as cursor:
            if phase:
                cursor.execute(
                    "DELETE FROM shadow_mode_stats WHERE phase = %s",
                    (phase,),
                )
            else:
                cursor.execute("DELETE FROM shadow_mode_stats")
    except Exception as e:
        logger.error("Failed to reset shadow stats: %s", e)
```

### Phase 3: Expose Stats via Health Endpoint

**Modify:** `argus-workers/health_server.py`

Add a `/shadow-stats` endpoint that operators can poll:

```python
elif self.path == "/shadow-stats":
    self._handle_shadow_stats()

def _handle_shadow_stats(self):
    """Serve shadow-mode convergence stats."""
    from runtime.shadow_mode import get_shadow_stats
    stats = get_shadow_stats()
    self._json_response(stats)
```

### Phase 4: Auto-Flip Mechanism

**New file:** `argus-workers/runtime/shadow_flipper.py`

```python
"""
ShadowFlipper — Automatically promote feature flags from shadow mode
to default-enabled when convergence criteria are met.

Checks the DB-backed shadow stats and flips feature flags when
consecutive_successes >= 100 for a given phase.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Map of shadow phase → feature flag to enable when converged
SHADOW_TO_FLAG_MAP: dict[str, str] = {
    "deterministic_scan": "CLEAN_ORCHESTRATOR",
    "engagement_state": "ENGAGEMENT_STATE",
    "governance": "GOVERNANCE_V2",
}

# Threshold for auto-flip
CONVERGENCE_THRESHOLD = 100


def check_and_auto_flip(phase: str) -> bool:
    """
    Check if a shadow phase has converged and auto-flip its flag.
    
    Returns True if the flag was flipped, False otherwise.
    """
    from runtime.shadow_mode import get_consecutive_successes
    from feature_flags import get_feature_flags
    
    consecutive = get_consecutive_successes(phase)
    if consecutive < CONVERGENCE_THRESHOLD:
        return False
    
    flag_name = SHADOW_TO_FLAG_MAP.get(phase)
    if not flag_name:
        logger.warning("No flag mapped for shadow phase '%s'", phase)
        return False
    
    # Check if the flag is already enabled
    ff = get_feature_flags()
    if ff.is_enabled(flag_name):
        logger.info(
            "Flag '%s' already enabled for converged phase '%s' "
            "(%d consecutive successes)",
            flag_name, phase, consecutive,
        )
        return False
    
    # Write the flag to the database
    _write_flag_to_db(flag_name, True)
    
    logger.info(
        "AUTO-FLIP: Shadow phase '%s' converged (%d consecutive successes). "
        "Feature flag '%s' set to True in database.",
        phase, consecutive, flag_name,
    )
    return True


def _write_flag_to_db(flag_name: str, value: bool) -> None:
    """Persist a feature flag value to the database."""
    try:
        from database.connection import db_cursor
        
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO feature_flags (flag_name, enabled, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (flag_name) DO UPDATE SET
                    enabled = %s,
                    updated_at = NOW()
                """,
                (flag_name, value, value),
            )
    except Exception as e:
        logger.error("Failed to write feature flag '%s' to DB: %s", flag_name, e)
```

### Phase 5: Scheduled Convergence Check

**Modify:** `argus-workers/celery_app.py` — add a periodic task

```python
# In beat_schedule:
"check-shadow-convergence": {
    "task": "tasks.maintenance.check_shadow_convergence",
    "schedule": crontab(minute="*/30"),  # Every 30 minutes
},
```

**New task:** `argus-workers/tasks/maintenance.py`

```python
def check_shadow_convergence():
    """Check all shadow phases for convergence and auto-flip flags."""
    from runtime.shadow_mode import get_shadow_stats
    from runtime.shadow_flipper import check_and_auto_flip, SHADOW_TO_FLAG_MAP
    
    stats = get_shadow_stats()
    flipped_count = 0
    for phase in SHADOW_TO_FLAG_MAP:
        if check_and_auto_flip(phase):
            flipped_count += 1
    
    if flipped_count:
        logger.info("Shadow convergence check: %d flag(s) auto-flipped", flipped_count)
    else:
        logger.debug("Shadow convergence check: no flags flipped")
```

### Testing Phase 1-5

```python
# tests/test_shadow_mode_convergence.py
class TestShadowModeDbBackend:
    def test_consecutive_successes_across_calls(self, test_db):
        """Atomic UPDATE ensures counters work across simulated workers."""
        # Worker 1
        shadow_compare("test_phase", "eng-1", {"a": 1}, lambda: {"a": 1})
        assert get_consecutive_successes("test_phase") == 1
        
        # Worker 2 (different process, same DB)
        shadow_compare("test_phase", "eng-2", {"b": 2}, lambda: {"b": 2})
        assert get_consecutive_successes("test_phase") == 2

    def test_mismatch_resets_counter(self, test_db):
        shadow_compare("test_phase", "eng-1", {"a": 1}, lambda: {"a": 1})
        shadow_compare("test_phase", "eng-2", {"a": 1}, lambda: {"a": 999})
        assert get_consecutive_successes("test_phase") == 0

    def test_auto_flip_at_threshold(self, test_db):
        # Simulate 100 consecutive successes
        for i in range(100):
            shadow_compare("deterministic_scan", f"eng-{i}", {"ok": 1}, lambda: {"ok": 1})
        
        assert check_and_auto_flip("deterministic_scan") == True
```

---

## Implementation Order & Dependencies

### Recommended Build Order

```
Phase 1A: DegradationAwareness module (new file) ──── 1-2 days
        ↓
Phase 1B: Integration into ReActAgent ─────────────── 1 day
        ↓
Phase 1C: Adaptive stopping + health metrics ──────── 1 day
        ↓
Phase 2A: Fix MemoryRetriever._get_long_term() ────── 1 day
        ↓
Phase 2B: Auto-upsert profiles + tool accuracy ────── 1-2 days
        ↓
Phase 2C: LLM prompt injection from profiles ──────── 1 day
        ↓
Phase 3A: DB migration for shadow_mode_stats ──────── 0.5 day
        ↓
Phase 3B: Rewrite shadow_mode.py with DB ops ──────── 1-2 days
        ↓
Phase 3C: ShadowFlipper + scheduled convergence ───── 1 day
```

**Total estimated effort:** 8-11 days for all three blockers.

### Dependency Graph

```
Blocker #1 (Meta-Cognition) ─── standalone, no deps
    ├─ Phase 1A: DegradationAwareness module
    ├─ Phase 1B: Integrate into ReActAgent
    ├─ Phase 1C: Adaptive stopping
    └─ Phase 1D: Health server integration

Blocker #2 (Cross-Scan Learning) ─── depends on Phase 1A for monitoring
    ├─ Phase 2A: Fix _get_long_term() 
    ├─ Phase 2B: Auto-upsert + tool accuracy → depends on intelligence_engine
    └─ Phase 2C: Prompt injection → depends on agent_prompts.py

Blocker #3 (Shadow Mode) ─── standalone, no deps on 1 or 2
    ├─ Phase 3A: DB migration
    ├─ Phase 3B: Rewrite shadow_mode.py
    ├─ Phase 3C: ShadowFlipper module
    └─ Phase 3D: Scheduled convergence check
```

All three blockers can be worked on in **parallel** since they touch different
parts of the codebase with minimal overlap. The only shared dependency is the
database connection module, which is already stable.

### Feature Flag Migration

After each blocker's phases are complete and tested:

| Blocker | Feature Flag | Current Default | After Migration |
|---------|-------------|-----------------|-----------------|
| Meta-Cognition | (new) `DEGRADATION_AWARENESS` | Off (not in `AUTONOMOUS_FEATURES`) | Add to `AUTONOMOUS_FEATURES` |
| Cross-Scan Learning | `MEMORY_RETRIEVAL` | False | True (after Phase 2 passes shadow) |
| Shadow Convergence | (new, implicit) | N/A | Always on (replaces threading counters) |

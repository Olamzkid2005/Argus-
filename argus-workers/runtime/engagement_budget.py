"""One cumulative budget ledger per engagement (Stage 6.1).

Before this module the run's limits lived in three unrelated places: the wall
clock in ``Governance``, the LLM cost cap inside ``LlmCostTracker``, and tool
timeouts in the caller. Nothing persisted a single engagement-level record of
what had actually been spent, so a resumed run could spend a fresh budget, a
failed or malformed LLM call was invisible, and a tool call could outlive the
deadline that was supposed to bound it.

``EngagementBudgetLedger`` is that record. It owns:

* the wall-clock deadline (UTC), and ``remaining_seconds()`` / the timeout bound
  for any in-flight call;
* LLM call accounting that includes failed, fallback and malformed responses,
  plus token counts and cost (or an explicit ``cost_known = False``);
* tool calls and request usage;
* ``stop_reason()`` — the single answer to "may this run continue?" — with
  distinct ``deadline`` / ``cancelled`` / ``budget`` reasons.

It is persisted through a small store protocol: the in-memory store for tests
and local runs, ``PostgresBudgetLedgerStore`` for the worker. A resumed run
loads the same record, so usage accumulates rather than resets.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

STOP_DEADLINE = "deadline"
STOP_CANCELLED = "cancelled"
STOP_BUDGET = "budget"

_MALFORMED_MARKERS = ("json", "parse", "unexpected response type")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def classify_llm_failure(reason: str) -> str:
    """Bucket a fallback reason as ``malformed`` or ``failure``."""
    lowered = (reason or "").lower()
    if any(marker in lowered for marker in _MALFORMED_MARKERS):
        return "malformed"
    return "failure"


@dataclass
class BudgetUsage:
    """The persisted cumulative usage of one engagement."""

    engagement_id: str
    deadline_at: str = ""
    llm_calls: int = 0
    llm_failures: int = 0
    llm_fallbacks: int = 0
    llm_malformed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True
    tool_calls: int = 0
    request_count: int = 0
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BudgetUsage | None:
        if not data:
            return None
        known = {
            key: data[key]
            for key in cls.__dataclass_fields__
            if key in data
        }
        if not known.get("engagement_id"):
            return None
        return cls(**known)


class BudgetLedgerStore(Protocol):
    """Persistence boundary for the ledger."""

    def save(self, usage: BudgetUsage) -> None: ...

    def load(self, engagement_id: str) -> dict[str, Any] | None: ...


class InMemoryBudgetLedgerStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(self, usage: BudgetUsage) -> None:
        with self._lock:
            self._rows[usage.engagement_id] = usage.to_dict()

    def load(self, engagement_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(engagement_id)
            return dict(row) if row else None


class PostgresBudgetLedgerStore:
    """UPSERT the ledger into ``engagement_budget_usage``.

    A missing table is reported, never silently ignored: callers treat the
    ledger as the record of what was spent, so failing to store it is a
    persistence error rather than something to swallow.
    """

    def save(self, usage: BudgetUsage) -> None:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engagement_budget_usage (
                    engagement_id, deadline_at, llm_calls, llm_failures,
                    llm_fallbacks, llm_malformed, input_tokens, output_tokens,
                    cost_usd, cost_known, tool_calls, request_count,
                    created_at, updated_at
                ) VALUES (
                    %s, NULLIF(%s, '')::timestamptz, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::timestamptz, %s::timestamptz
                )
                ON CONFLICT (engagement_id) DO UPDATE SET
                    deadline_at = EXCLUDED.deadline_at,
                    llm_calls = EXCLUDED.llm_calls,
                    llm_failures = EXCLUDED.llm_failures,
                    llm_fallbacks = EXCLUDED.llm_fallbacks,
                    llm_malformed = EXCLUDED.llm_malformed,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    cost_usd = EXCLUDED.cost_usd,
                    cost_known = EXCLUDED.cost_known,
                    tool_calls = EXCLUDED.tool_calls,
                    request_count = EXCLUDED.request_count,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    usage.engagement_id,
                    usage.deadline_at,
                    usage.llm_calls,
                    usage.llm_failures,
                    usage.llm_fallbacks,
                    usage.llm_malformed,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cost_usd,
                    usage.cost_known,
                    usage.tool_calls,
                    usage.request_count,
                    usage.created_at,
                    usage.updated_at,
                ),
            )

    def load(self, engagement_id: str) -> dict[str, Any] | None:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                """
                SELECT engagement_id, deadline_at, llm_calls, llm_failures,
                       llm_fallbacks, llm_malformed, input_tokens, output_tokens,
                       cost_usd, cost_known, tool_calls, request_count,
                       created_at, updated_at
                FROM engagement_budget_usage
                WHERE engagement_id = %s
                """,
                (engagement_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        columns = (
            "engagement_id",
            "deadline_at",
            "llm_calls",
            "llm_failures",
            "llm_fallbacks",
            "llm_malformed",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "cost_known",
            "tool_calls",
            "request_count",
            "created_at",
            "updated_at",
        )
        data = dict(zip(columns, row, strict=False))
        if isinstance(data.get("deadline_at"), datetime):
            data["deadline_at"] = data["deadline_at"].astimezone(UTC).isoformat()
        for key in ("created_at", "updated_at"):
            if isinstance(data.get(key), datetime):
                data[key] = data[key].astimezone(UTC).isoformat()
        return data


class EngagementBudgetLedger:
    """Cumulative budget for one engagement, bounded by a UTC deadline."""

    def __init__(
        self,
        engagement_id: str,
        *,
        deadline_at: str | None = None,
        max_seconds: float | None = None,
        max_cost_usd: float | None = None,
        max_tool_calls: int | None = None,
        max_llm_calls: int | None = None,
        usage: BudgetUsage | None = None,
        store: BudgetLedgerStore | None = None,
        clock=time.monotonic,
    ) -> None:
        self.engagement_id = engagement_id
        self.max_cost_usd = max_cost_usd
        self.max_tool_calls = max_tool_calls
        self.max_llm_calls = max_llm_calls
        self.store = store
        self._clock = clock
        self._started_monotonic = clock()
        self._lock = threading.Lock()

        loaded = usage
        if loaded is None and store is not None and engagement_id:
            try:
                loaded = BudgetUsage.from_dict(store.load(engagement_id))
            except Exception:
                # A broken store must not erase the in-memory record; the
                # caller sees the persistence error on save instead.
                loaded = None

        if loaded is not None:
            self.usage = loaded
            # A restored deadline is absolute; max_seconds only applies to runs
            # that have no deadline of their own.
            if deadline_at and not self.usage.deadline_at:
                self.usage.deadline_at = deadline_at
        else:
            resolved_deadline = deadline_at
            if not resolved_deadline and max_seconds is not None:
                resolved_deadline = (
                    datetime.now(UTC) + timedelta(seconds=float(max_seconds))
                ).isoformat()
            self.usage = BudgetUsage(
                engagement_id=engagement_id,
                deadline_at=resolved_deadline or "",
            )

    # ── Time ────────────────────────────────────────────────────────────
    def deadline(self) -> datetime | None:
        return _parse_utc(self.usage.deadline_at)

    def remaining_seconds(self, now: datetime | None = None) -> float | None:
        deadline = self.deadline()
        if deadline is None:
            return None
        current = now or datetime.now(UTC)
        return (deadline - current).total_seconds()

    def bounded_timeout(self, requested: float) -> float:
        """Never hand a call more time than the engagement has left."""
        remaining = self.remaining_seconds()
        if remaining is None:
            return requested
        return max(0.0, min(float(requested), remaining))

    # ── Decisions ───────────────────────────────────────────────────────
    def stop_reason(self, *, cancelled: bool = False) -> str | None:
        if cancelled:
            return STOP_CANCELLED
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            return STOP_DEADLINE
        usage = self.usage
        if self.max_cost_usd is not None and usage.cost_known and usage.cost_usd > self.max_cost_usd:
            return STOP_BUDGET
        if self.max_tool_calls is not None and usage.tool_calls >= self.max_tool_calls:
            return STOP_BUDGET
        if self.max_llm_calls is not None and usage.llm_calls >= self.max_llm_calls:
            return STOP_BUDGET
        return None

    # ── Accounting ──────────────────────────────────────────────────────
    def record_llm_call(
        self,
        *,
        success: bool = True,
        fallback: bool = False,
        reason: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        """Record one LLM call, including calls that did not produce an answer."""
        with self._lock:
            usage = self.usage
            usage.llm_calls += 1
            usage.request_count += 1
            usage.input_tokens += max(0, int(input_tokens or 0))
            usage.output_tokens += max(0, int(output_tokens or 0))
            if cost_usd is None:
                # Explicit unknown-cost accounting: an unpriced call still
                # happens, and the ledger says we cannot price it.
                usage.cost_known = False
            else:
                usage.cost_usd += float(cost_usd)
            if fallback:
                usage.llm_fallbacks += 1
                bucket = classify_llm_failure(reason)
                if bucket == "malformed":
                    usage.llm_malformed += 1
            if not success or fallback:
                usage.llm_failures += 1
            usage.updated_at = _utc_now()
        self.persist()

    def record_tool_call(self) -> None:
        with self._lock:
            self.usage.tool_calls += 1
            self.usage.updated_at = _utc_now()
        self.persist()

    def persist(self) -> None:
        if self.store is None:
            return
        self.store.save(self.usage)

    def status(self) -> dict[str, Any]:
        remaining = self.remaining_seconds()
        return {
            **self.usage.to_dict(),
            "remaining_seconds": None if remaining is None else round(remaining, 2),
            "stop_reason": self.stop_reason(),
        }

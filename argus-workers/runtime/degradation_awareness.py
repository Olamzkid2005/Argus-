"""
DegradationAwareness — The system's sense of self.

Tracks runtime health metrics across multiple dimensions and provides
a unified "am I operating normally?" answer. The agent loop uses this
to adjust its behavior when the system is degraded rather than silently
running deterministic fallback without awareness.

Usage:
    da = DegradationAwareness(engagement_id)
    da.record_llm_result(success=True)
    da.record_tool_result(tool_name="nuclei", findings_count=5)
    status = da.get_status()  # DegradationStatus with level, rates, action
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Rolling window sizes for metrics
_LLM_WINDOW_SIZE = 20       # last 20 LLM calls
_TOOL_WINDOW_SIZE = 50      # last 50 tool calls


class DegradationLevel:
    """Well-known degradation levels."""
    HEALTHY = "healthy"      # LLM working, tools producing findings
    DEGRADED = "degraded"    # LLM failing or no findings trend
    CRITICAL = "critical"    # Both LLM and tools failing


@dataclass
class DegradationStatus:
    """Snapshot of current system health."""
    level: str = DegradationLevel.HEALTHY
    llm_success_rate: float = 1.0
    llm_window_size: int = 0
    tool_finding_rate: float = 0.0
    tool_window_size: int = 0
    consecutive_llm_failures: int = 0
    recommended_action: str = ""


class DegradationAwareness:
    """Tracks runtime health and recommends adaptive actions.

    Thread-safe: all mutable state is updated via deque append (atomic
    in CPython) and read under a lock for consistency.
    """

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self._llm_results: deque[bool] = deque(maxlen=_LLM_WINDOW_SIZE)
        self._tool_finding_counts: deque[int] = deque(maxlen=_TOOL_WINDOW_SIZE)
        self._consecutive_llm_failures = 0
        self._last_llm_success_rate = 1.0
        self._lock = threading.Lock()
        # Register with global registry for health endpoint observability
        try:
            register_degradation_awareness(self)
        except Exception:
            logger.debug("Failed to register DegradationAwareness in global registry")

    def record_llm_result(self, success: bool):
        """Record whether the last LLM call succeeded or failed.

        Args:
            success: True if the LLM returned a valid result, False otherwise.
        """
        with self._lock:
            self._llm_results.append(success)
            if success:
                self._consecutive_llm_failures = 0
            else:
                self._consecutive_llm_failures += 1

    def record_tool_result(self, tool_name: str, findings_count: int):
        """Record how many findings a tool execution produced.

        Args:
            tool_name: Name of the tool that executed.
            findings_count: Number of findings produced (0 is valid).
        """
        with self._lock:
            self._tool_finding_counts.append(findings_count)

    def get_llm_success_rate(self) -> float:
        """Fraction of successful LLM calls in the rolling window.

        Returns 1.0 when no data (assume healthy), so the system doesn't
        immediately think it's degraded on the first call.
        """
        with self._lock:
            if not self._llm_results:
                return 1.0
            return sum(self._llm_results) / len(self._llm_results)

    def get_tool_finding_rate(self) -> float:
        """Fraction of tools that produced at least 1 finding.

        Returns 0.5 when no data (neutral starting point).
        """
        with self._lock:
            if not self._tool_finding_counts:
                return 0.5
            return sum(1 for c in self._tool_finding_counts if c > 0) / len(self._tool_finding_counts)

    def get_status(self) -> DegradationStatus:
        """Compute unified status with recommended action.

        Decision logic:
        - CRITICAL: LLM < 30% AND tools < 10% → stop engagement
        - DEGRADED: LLM < 50% → switch to deterministic with wider coverage
        - DEGRADED: tools < 20% after 10+ tool runs → broaden strategy
        - HEALTHY: everything nominal
        """
        with self._lock:
            llm_rate = self.get_llm_success_rate()
            tool_rate = self.get_tool_finding_rate()

            status = DegradationStatus(
                llm_success_rate=round(llm_rate, 2),
                llm_window_size=len(self._llm_results),
                tool_finding_rate=round(tool_rate, 2),
                tool_window_size=len(self._tool_finding_counts),
                consecutive_llm_failures=self._consecutive_llm_failures,
            )

            if llm_rate < 0.3 and tool_rate < 0.1:
                status.level = DegradationLevel.CRITICAL
                status.recommended_action = (
                    "LLM and tools both failing. Recommend stopping engagement "
                    "and checking infrastructure."
                )
            elif llm_rate < 0.5 and len(self._llm_results) >= 5:
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

            return status

    def to_dict(self) -> dict[str, Any]:
        """Serialize status for health endpoint."""
        status = self.get_status()
        return {
            "engagement_id": self.engagement_id,
            "level": status.level,
            "llm_success_rate": status.llm_success_rate,
            "llm_window_size": status.llm_window_size,
            "tool_finding_rate": status.tool_finding_rate,
            "tool_window_size": status.tool_window_size,
            "consecutive_llm_failures": status.consecutive_llm_failures,
            "recommended_action": status.recommended_action,
        }

    def reset(self):
        """Reset all metrics (e.g., for testing or new phase)."""
        with self._lock:
            self._llm_results.clear()
            self._tool_finding_counts.clear()
            self._consecutive_llm_failures = 0


# ── Global DegradationAwareness Registry ──
# Enables the health server to report degradation status for all active
# engagements without coupling the handler to individual agent instances.

_degradation_registry: dict[str, DegradationAwareness] = {}
_degradation_registry_lock = threading.Lock()


def register_degradation_awareness(da: DegradationAwareness) -> None:
    """Register a DegradationAwareness instance for health monitoring.

    Thread-safe: uses a lock for registry modification.
    """
    with _degradation_registry_lock:
        _degradation_registry[da.engagement_id] = da


def get_all_degradation_statuses() -> dict[str, dict[str, Any]]:
    """Get serialized degradation status for all active engagements.

    Returns:
        {engagement_id: to_dict()} for each registered DA instance.
    """
    with _degradation_registry_lock:
        return {
            eng_id: da.to_dict()
            for eng_id, da in list(_degradation_registry.items())
        }


def get_worst_degradation_status() -> dict[str, Any] | None:
    """Get the worst degradation level across all active engagements.

    Priority: critical > degraded > healthy.
    Returns None if no engagements are registered.

    Returns:
        Dict with the worst status (or None if registry empty).
    """
    with _degradation_registry_lock:
        if not _degradation_registry:
            return None

        worst: dict[str, Any] | None = None
        worst_priority = -1
        level_map = {"healthy": 0, "degraded": 1, "critical": 2}

        for da in _degradation_registry.values():
            status = da.to_dict()
            priority = level_map.get(status.get("level", "healthy"), -1)
            if priority > worst_priority:
                worst_priority = priority
                worst = status

        return worst


def unregister_degradation_awareness(engagement_id: str) -> None:
    """Remove a DegradationAwareness instance from the registry.

    Thread-safe. Idempotent — no-op if engagement_id not found.
    """
    with _degradation_registry_lock:
        _degradation_registry.pop(engagement_id, None)

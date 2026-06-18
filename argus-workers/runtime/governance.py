"""
Governance — Unified safety controls for the agent runtime.

Centralizes all runtime safety controls that were previously fragmented across:
- LoopBudgetManager (cycle/depth/LLM limits)
- LlmCostTracker (dollar cost tracking)
- HardTimeoutSeconds (wall-clock timeout)
- Low-signal detection (NEW)

Architecture:
  Governance wraps these components and provides a single check() method
  that the agent loop calls before each action. The orchestrator calls
  governance.check() rather than managing each limit independently.

Usage:
    governance = Governance(engagement_id, connection_string)
    can_proceed, reason = governance.check(action)
    if not can_proceed:
        # Switch to deterministic fallback or stop
        governance.record_shutdown(reason)
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Default thresholds
_DEFAULT_MAX_TOKENS = 100_000
_DEFAULT_MAX_COST_USD = 10.0
_DEFAULT_MAX_RUNTIME_SECONDS = 3600  # 1 hour
_DEFAULT_LOW_SIGNAL_THRESHOLD = 3  # consecutive low-value tool runs
_DEFAULT_HIGH_VALUE_SEVERITIES = {"CRITICAL", "HIGH"}


class Governance:
    """
    Unified runtime governance.

    Combines budget, cost, timeout, and signal-quality checks into a
    single governance.check() call that the agent loop uses before
    executing any action.

    Each control is independently configurable via constructor params
    and defaults to permissive values when not provided.
    """

    def __init__(
        self,
        engagement_id: str,
        connection_string: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_cost_usd: float = _DEFAULT_MAX_COST_USD,
        max_runtime_seconds: int = _DEFAULT_MAX_RUNTIME_SECONDS,
        low_signal_threshold: int = _DEFAULT_LOW_SIGNAL_THRESHOLD,
    ):
        self.engagement_id = engagement_id
        self.connection_string = connection_string
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.max_runtime_seconds = max_runtime_seconds
        self.low_signal_threshold = low_signal_threshold

        # Runtime tracking
        self._start_time = time.time()
        self._total_tokens_used = 0
        self._total_cost_usd = 0.0
        self._consecutive_low_signal = 0
        self._last_tool_results: list[dict] = []
        self._is_shutdown = False
        self._shutdown_reason = ""

    # ── Public API ──

    def check(self, action: dict | Any) -> tuple[bool, str]:
        """
        Check if an action is permitted under all governance controls.

        Args:
            action: An AgentAction or dict with 'tool', 'arguments', 'cost_usd'

        Returns:
            (can_proceed: bool, reason: str)
        """
        if self._is_shutdown:
            return False, self._shutdown_reason

        if isinstance(action, dict):
            tool_name = action.get("tool", "unknown")
            cost = action.get("cost_usd", 0.0) or 0.0
        else:
            tool_name = getattr(action, "tool", "unknown") or "unknown"
            cost = getattr(action, "cost_usd", 0.0) or 0.0

        # 1. Runtime timeout check
        elapsed = time.time() - self._start_time
        if elapsed > self.max_runtime_seconds:
            self._shutdown(
                "runtime_timeout", f"Runtime exceeded {self.max_runtime_seconds}s"
            )
            return False, self._shutdown_reason

        # 2. Cost check (estimate before execution)
        # We check approximate cost even before execution to prevent
        # the agent from choosing expensive tools when budget is tight.
        projected_cost = self._total_cost_usd + float(cost)
        if projected_cost > self.max_cost_usd:
            self._shutdown(
                "cost_guard",
                f"Projected cost ${projected_cost:.4f} exceeds ${self.max_cost_usd:.4f}",
            )
            return False, self._shutdown_reason

        # 3. Token budget check (approximate based on tool complexity)
        estimated_tokens = self._estimate_token_usage(tool_name)
        projected_tokens = self._total_tokens_used + estimated_tokens
        if projected_tokens > self.max_tokens:
            self._shutdown(
                "token_budget",
                f"Projected tokens {projected_tokens} exceeds {self.max_tokens}",
            )
            return False, self._shutdown_reason

        return True, ""

    def record_result(self, result: Any, action: dict | Any | None = None):
        """
        Record a tool result for signal-quality tracking.

        Args:
            result: ToolResult from ToolRunner
            action: Optional AgentAction/dict for cost/token tracking
        """
        if self._is_shutdown:
            return

        # Track cost
        if action is not None:
            if isinstance(action, dict):
                cost = action.get("cost_usd", 0.0) or 0.0
            else:
                cost = getattr(action, "cost_usd", 0.0) or 0.0
            self._total_cost_usd += float(cost)

        # Track tokens (estimated)
        tool_name = ""
        if action is not None:
            if isinstance(action, dict):
                tool_name = action.get("tool", "") or ""
            else:
                tool_name = getattr(action, "tool", "") or ""
        self._total_tokens_used += self._estimate_token_usage(tool_name)

        # Track signal quality
        result_dict = {}
        if hasattr(result, "success"):
            result_dict["success"] = result.success
            result_dict["tool"] = getattr(result, "tool", tool_name)
            result_dict["findings_count"] = self._extract_finding_count(result)
            result_dict["severity"] = self._extract_max_severity(result)
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {"success": False, "tool": str(result)}

        self._last_tool_results.append(result_dict)
        if len(self._last_tool_results) > 10:
            self._last_tool_results = self._last_tool_results[-10:]

        # Low-signal detection
        if not self._result_has_high_value(result_dict):
            self._consecutive_low_signal += 1
        else:
            self._consecutive_low_signal = 0

    def check_low_signal(self) -> tuple[bool, str]:
        """
        Check if consecutive low-signal threshold is exceeded.

        Returns:
            (is_low_signal: bool, detail: str)
        """
        if self._consecutive_low_signal >= self.low_signal_threshold:
            return True, (
                f"Low-signal threshold reached: "
                f"{self._consecutive_low_signal} consecutive low-value tool runs"
            )
        return False, ""

    def get_status(self) -> dict:
        """Return current governance status for observation building."""
        elapsed = time.time() - self._start_time
        return {
            "engagement_id": self.engagement_id,
            "runtime_elapsed_seconds": round(elapsed, 1),
            "max_runtime_seconds": self.max_runtime_seconds,
            "total_cost_usd": round(self._total_cost_usd, 6),
            "max_cost_usd": self.max_cost_usd,
            "total_tokens_estimated": self._total_tokens_used,
            "max_tokens": self.max_tokens,
            "consecutive_low_signal": self._consecutive_low_signal,
            "low_signal_threshold": self.low_signal_threshold,
            "is_shutdown": self._is_shutdown,
            "shutdown_reason": self._shutdown_reason,
            "recent_tool_count": len(self._last_tool_results),
        }

    def is_shutdown(self) -> bool:
        """Check if governance has shut down the runtime."""
        return self._is_shutdown

    @property
    def shutdown_reason(self) -> str:
        return self._shutdown_reason

    def reset_low_signal_counter(self):
        """Reset the low-signal counter (e.g., when starting a new phase)."""
        self._consecutive_low_signal = 0

    # ── Internal helpers ──

    def _shutdown(self, reason: str, detail: str):
        """Mark governance as shutdown with a reason."""
        self._is_shutdown = True
        self._shutdown_reason = f"{reason}: {detail}"
        logger.warning(
            "Governance shutdown for engagement %s: %s",
            self.engagement_id,
            self._shutdown_reason,
        )

    def _estimate_token_usage(self, tool_name: str) -> int:
        """Estimate token usage per tool invocation.
        NOTE: These are rough estimates, not actual token counts.
        Actual LLM token usage may differ significantly.
        """
        # Rough estimates based on tool complexity
        estimates = {
            "nuclei": 200,
            "web_scanner": 300,
            "port_scanner": 100,
            "api_scanner": 250,
            "browser_scanner": 400,
            "websocket_scanner": 200,
            "llm_detector": 500,
            "ai_vuln_scanner": 600,
            "sbom_generator": 150,
            "api_security_scanner": 350,
        }
        return estimates.get(tool_name.lower(), 150)

    def _extract_finding_count(self, result: Any) -> int:
        """Extract finding count from a tool result."""
        if hasattr(result, "findings") and result.findings:
            return len(result.findings)
        if hasattr(result, "output") and result.output:
            import json

            try:
                data = json.loads(result.output)
                if isinstance(data, list):
                    return len(data)
                if isinstance(data, dict):
                    return len(data.get("findings", data.get("results", [])))
            except (json.JSONDecodeError, TypeError):
                pass
        return 0

    def _extract_max_severity(self, result: Any) -> str:
        """Extract maximum severity from a tool result."""
        severities = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        max_sev = "INFO"
        max_val = 0

        findings = []
        if hasattr(result, "findings") and result.findings:
            findings = result.findings
        elif hasattr(result, "output") and result.output:
            import json

            try:
                data = json.loads(result.output)
                if isinstance(data, list):
                    findings = data
                elif isinstance(data, dict):
                    findings = data.get("findings", data.get("results", []))
            except (json.JSONDecodeError, TypeError):
                pass

        for f in findings:
            sev = f.get("severity", "INFO") if isinstance(f, dict) else "INFO"
            val = severities.get(sev.upper(), 0)
            if val > max_val:
                max_val = val
                max_sev = sev

        return max_sev

    def _result_has_high_value(self, result_dict: dict) -> bool:
        """Check if a result has high-value findings."""
        if not result_dict.get("success", False):
            return False
        severity = result_dict.get("severity", "INFO")
        return severity.upper() in _DEFAULT_HIGH_VALUE_SEVERITIES

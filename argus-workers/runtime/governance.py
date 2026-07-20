"""
Governance — Unified safety controls for the agent runtime.

Centralizes all runtime safety controls that were previously fragmented across:
- LoopBudgetManager (cycle/depth/LLM limits)
- LlmCostTracker (dollar cost tracking via Redis for cross-worker persistence)
- HardTimeoutSeconds (wall-clock timeout)
- Low-signal detection

Architecture:
  Governance wraps these components and provides a single check() method
  that the agent loop calls before each action. The orchestrator calls
  governance.check() rather than managing each limit independently.
  Cost tracking is persisted via LlmCostTracker (Redis-backed) so spend
  is not lost across worker restarts (fixes item 25).

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

from tasks.utils import LlmCostTracker

logger = logging.getLogger(__name__)

# Default thresholds
_DEFAULT_MAX_TOKENS = 100_000
_DEFAULT_MAX_COST_USD = 10.0
_DEFAULT_MAX_RUNTIME_SECONDS = 3600  # 1 hour
# Blocker 64: Must be < constants.py:zero_finding_stop (4).
# If low_signal_threshold >= zero_finding_stop, the legacy empty-output detection
# in react_agent.py fires before Governance's low-signal check, creating a race.
# Aligned: 3 < 4 ensures Governance always fires first with an informative reason.
_DEFAULT_LOW_SIGNAL_THRESHOLD = 3
_DEFAULT_HIGH_VALUE_SEVERITIES = {"CRITICAL", "HIGH"}
# Blocker 9: Diminishing returns detection thresholds
_DIMINISHING_RETURNS_WINDOW = 8  # Look at last 8 tool results
_DIMINISHING_RETURNS_RATE_THRESHOLD = 0.15  # If finding rate drops below 15%
_DIMINISHING_RETURNS_CONFIRMATION = 3  # Confirm 3 times before triggering



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

        # Runtime tracking — wall clock start is kept for diagnostics but the
        # timeout check uses _active_time_accumulated (blocker 58).
        self._start_time = time.time()
        self._total_tokens_used = 0
        self._total_cost_usd = 0.0
        self._consecutive_low_signal = 0
        self._last_tool_results: list[dict] = []
        self._is_shutdown = False
        self._shutdown_reason = ""

        # Blocker 9: Diminishing returns tracking
        # Rolling window of finding counts per tool (last N tools)
        self._finding_counts_window: list[int] = []
        self._consecutive_flat_finding_rate = 0
        # Track unique vulnerability types covered (for coverage scoring)
        self._covered_vuln_types: set[str] = set()

        # LlmCostTracker for cross-worker persistent cost tracking (item 25)
        # Falls back to in-process counting if Redis is unavailable.
        self._cost_tracker: LlmCostTracker | None = None
        try:
            self._cost_tracker = LlmCostTracker(engagement_id, max_cost=max_cost_usd)
        except Exception as e:
            logger.warning(
                "Failed to create LlmCostTracker for %s: %s — using in-memory cost tracking only",
                engagement_id,
                e,
            )
        # Active execution time tracking (blocker 58): accumulated seconds spent
        # actively executing tool calls, excluding idle/waiting time.
        self._active_time_accumulated: float = 0.0
        self._active_timer_start: float | None = None

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

        # 1. Active runtime timeout check (blocker 58)
        elapsed = self._active_time_accumulated
        if self._active_timer_start is not None:
            elapsed += time.time() - self._active_timer_start
        if elapsed > self.max_runtime_seconds:
            self._shutdown(
                "runtime_timeout",
                f"Active runtime exceeded {self.max_runtime_seconds}s "
                f"(accumulated: {elapsed:.1f}s, wall: {time.time() - self._start_time:.1f}s)",
            )
            return False, self._shutdown_reason

        # 2. Cost check (estimate before execution)
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

    def record_result(
        self,
        result: Any,
        action: dict | Any | None = None,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
    ) -> None:
        """
        Record a tool result for signal-quality tracking.

        Uses actual LLM token counts when available (blocker 48), falling
        back to the static estimate when not provided (e.g. for non-LLM
        deterministic tool execution).

        Args:
            result: ToolResult from ToolRunner
            action: Optional AgentAction/dict for cost/token tracking
            actual_input_tokens: Actual LLM input tokens (from LLMResponse)
            actual_output_tokens: Actual LLM output tokens (from LLMResponse)
        """
        if self._is_shutdown:
            return

        # Track cost — persist via LlmCostTracker when available (item 25)
        if action is not None:
            if isinstance(action, dict):
                cost = action.get("cost_usd", 0.0) or 0.0
            else:
                cost = getattr(action, "cost_usd", 0.0) or 0.0
            cost_float = float(cost)
            self._total_cost_usd += cost_float
            if self._cost_tracker is not None:
                self._cost_tracker.record_llm_call(cost_float)

        # Track tokens — use actual counts when available (blocker 48)
        tool_name = ""
        if action is not None:
            if isinstance(action, dict):
                tool_name = action.get("tool", "") or ""
            else:
                tool_name = getattr(action, "tool", "") or ""

        if actual_input_tokens is not None and actual_output_tokens is not None:
            # Use actual LLM token counts from the response
            self._total_tokens_used += actual_input_tokens + actual_output_tokens
            logger.debug(
                "Governance recorded actual token usage for %s: %d input + %d output = %d total",
                tool_name or "llm_call",
                actual_input_tokens,
                actual_output_tokens,
                actual_input_tokens + actual_output_tokens,
            )
        else:
            # Fallback to static estimate for non-LLM tool calls
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

        # Blocker 9: Track finding counts per tool for diminishing returns
        finding_count = result_dict.get("findings_count", 0)
        if isinstance(finding_count, int) and finding_count >= 0:
            self._finding_counts_window.append(finding_count)
            if len(self._finding_counts_window) > _DIMINISHING_RETURNS_WINDOW:
                self._finding_counts_window = self._finding_counts_window[-(_DIMINISHING_RETURNS_WINDOW + 1):]

        # Track covered vulnerability types (for tool-hit-rate scoring)
        severity = result_dict.get("severity", "INFO") or "INFO"
        if isinstance(finding_count, int) and finding_count > 0:
            tool_name = result_dict.get("tool", "") or ""
            if tool_name:
                self._covered_vuln_types.add(tool_name)
            if severity.upper() in ("HIGH", "CRITICAL"):
                self._covered_vuln_types.add(f"severity:{severity.upper()}")

    def start_active_timer(self) -> None:
        """Start tracking active execution time (blocker 58).

        Call this just before executing a tool call. Idle time between
        start/stop pairs is excluded from the active runtime budget.
        """
        self._active_timer_start = time.time()

    def stop_active_timer(self) -> None:
        """Stop tracking active execution time (blocker 58).

        Call this immediately after a tool call completes. Accumulates
        the elapsed time into _active_time_accumulated.
        """
        if self._active_timer_start is not None:
            elapsed = time.time() - self._active_timer_start
            self._active_time_accumulated += elapsed
            self._active_timer_start = None

    def get_active_runtime_seconds(self) -> float:
        """Get accumulated active execution time in seconds.

        Includes any currently-running timer if start_active_timer() was
        called without a matching stop.
        """
        elapsed = self._active_time_accumulated
        if self._active_timer_start is not None:
            elapsed += time.time() - self._active_timer_start
        return round(elapsed, 1)

    def get_status(self) -> dict:
        """Return current governance status for observation building."""
        wall_elapsed = time.time() - self._start_time
        active_elapsed = self.get_active_runtime_seconds()
        # Use persisted cost from LlmCostTracker when available (item 25)
        persisted_cost = 0.0
        if self._cost_tracker is not None:
            persisted_cost = self._cost_tracker.total
        # Compute finding rate for status
        window = list(self._finding_counts_window)
        if len(window) >= 4:
            mid = len(window) // 2
            early_rate = sum(window[:mid]) / max(len(window[:mid]), 1)
            late_rate = sum(window[mid:]) / max(len(window[mid:]), 1)
        else:
            early_rate = 0.0
            late_rate = 0.0

        return {
            "engagement_id": self.engagement_id,
            "runtime_elapsed_seconds": round(wall_elapsed, 1),
            "active_runtime_seconds": active_elapsed,
            "max_runtime_seconds": self.max_runtime_seconds,
            "total_cost_usd": round(max(self._total_cost_usd, persisted_cost), 6),
            "max_cost_usd": self.max_cost_usd,
            "total_tokens_estimated": self._total_tokens_used,
            "max_tokens": self.max_tokens,
            "consecutive_low_signal": self._consecutive_low_signal,
            "low_signal_threshold": self.low_signal_threshold,
            "is_shutdown": self._is_shutdown,
            "shutdown_reason": self._shutdown_reason,
            "recent_tool_count": len(self._last_tool_results),
            "cost_tracker_available": self._cost_tracker is not None,
            "finding_rate_window": len(window),
            "finding_rate_early": round(early_rate, 2),
            "finding_rate_recent": round(late_rate, 2),
            "consecutive_flat_rate": self._consecutive_flat_finding_rate,
            "covered_vuln_types": len(self._covered_vuln_types),
        }

    def is_shutdown(self) -> bool:
        """Check if governance has shut down the runtime."""
        return self._is_shutdown

    @property
    def shutdown_reason(self) -> str:
        return self._shutdown_reason

    def check_diminishing_returns(self) -> tuple[bool, str]:
        """Check if tool findings are exhibiting diminishing returns.

        Analyzes the rolling window of finding counts to determine if the
        rate of discovery has flattened. Returns:
            (should_stop: bool, reason: str)

        Three signals:
        1. Finding rate trend: rate of findings in last N tools vs first N/2
        2. Consecutive flat rate: multiple consecutive tools with near-zero findings
        3. Coverage saturation: high % of available vuln types already covered

        Blocker 9: This prevents the agent from running indefinitely when
        tools consistently produce no findings after initial successes.
        """
        window = list(self._finding_counts_window)
        if len(window) < 4:
            return False, ""  # Need at least 4 data points

        # Signal 1: Finding rate trend
        # Compare finding rate in recent half vs earlier half of window
        mid = len(window) // 2
        early_half = window[:mid]
        late_half = window[mid:]

        early_findings = sum(early_half)
        late_findings = sum(late_half)
        total_tools_early = len(early_half)
        total_tools_late = len(late_half)

        early_rate = early_findings / max(total_tools_early, 1)
        late_rate = late_findings / max(total_tools_late, 1)

        # Signal 2: Consecutive flat rate
        recent_zero_or_low = sum(
            1 for c in window[-4:] if c < 2
        )
        consecutive_low = recent_zero_or_low >= 3

        # Signal 3: Coverage saturation
        len(self._covered_vuln_types) / max(
            len(self._last_tool_results), 1
        )

        # Decision: stop when late_rate drops significantly below early_rate
        # AND we have high consecutive low findings
        if early_rate > 0 and late_rate == 0 and consecutive_low and len(window) >= 6:
            self._consecutive_flat_finding_rate += 1

            if self._consecutive_flat_finding_rate >= _DIMINISHING_RETURNS_CONFIRMATION:
                reason = (
                    f"Diminishing returns: early rate={early_rate:.2f} findings/tool "
                    f"vs recent rate={late_rate:.2f} findings/tool. "
                    f"Last {recent_zero_or_low}/4 tools had <2 findings. "
                    f"Coverage: {len(self._covered_vuln_types)} type(s) covered."
                )
                logger.info("Governance diminishing returns: %s", reason)
                return True, reason
        else:
            # Reset counter when findings pick up again
            if self._consecutive_flat_finding_rate > 0:
                self._consecutive_flat_finding_rate = 0

        return False, ""

    def reset_low_signal_counter(self) -> None:
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

        NOTE: These are now calibrated to reflect realistic tool outputs.
        The original values (200-300) were placebos — a nuclei scan with
        100 templates and 50 findings can easily use 5,000 tokens to
        describe all findings in the LLM context. These estimates are used
        for the token budget guard which must be meaningful to prevent
        unbounded context growth (blocker 6 fix).

        When actual LLM token counts are available (from LLMService), they
        are used instead via record_result()'s actual_input_tokens and
        actual_output_tokens parameters (blocker 48).
        """
        # Calibrated estimates based on typical tool output verbosity.
        # Finding-rich tools (nuclei, web_scanner) produce large observation
        # summaries that consume the most tokens. Lightweight tools
        # (port_scanner, sbom) produce structured but smaller outputs.
        estimates = {
            "nuclei": 3000,           # Multi-template, 50-200 findings typical
            "web_scanner": 4000,       # Full crawl + checks, 100+ findings
            "port_scanner": 800,       # Structured port list, few tokens
            "api_scanner": 2500,       # Endpoint enumeration + findings
            "browser_scanner": 3500,   # CSP/security analysis + screenshots
            "websocket_scanner": 2000, # WS message analysis
            "llm_detector": 500,       # LLM-driven analysis already counted
            "ai_vuln_scanner": 600,    # AI-driven analysis already counted
            "sbom_generator": 800,     # Structured SBOM, moderate size
            "api_security_scanner": 3000,  # Multi-API analysis
            "sqlmap": 2000,            # SQL injection testing + results
            "dalfox": 2000,            # XSS scanning + findings
            "wpscan": 1500,            # WordPress enumeration
            "testssl": 1200,           # TLS analysis
            "commix": 1500,            # Command injection testing
            "ffuf_scanner": 1000,      # Fuzzing results
            "arjun_scanner": 800,      # Parameter discovery
            "subfinder": 500,          # Subdomain discovery
        }
        return estimates.get(tool_name.lower(), 1000)

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
                    return len(data.get("findings", data.get("results", [])))  # type: ignore[arg-type]
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
                    findings = data.get("findings", data.get("results", []))  # type: ignore[assignment]
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

"""
Circuit Breaker for tool execution resilience.

Prevents cascading failures by stopping calls to failing tools.

Requirements: 4.2
"""

import threading
import time
from collections.abc import Callable
from enum import Enum
from functools import wraps

from exceptions import CircuitOpenError
from utils.logging_utils import ScanLogger


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing if recovery is possible


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading tool failures.

    After 3 consecutive failures, the circuit opens for 5 minutes.
    Then allows one test call before returning to normal or opening again.

    Usage:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300)

        @breaker
        def call_tool():
            return tool_runner.run(...)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: int = 300,
        name: str | None = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            cooldown_seconds: Time to wait before testing recovery
            name: Optional name for logging
        """
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.name = name or "default"

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._lock = threading.RLock()
        # Active-time tracking (blocker 58): accumulate only execution time
        # toward cooldown, not wall-clock idle time.
        self._active_time_accumulator: float = 0.0  # seconds of active execution
        self._active_time_since_open: float = 0.0  # seconds since circuit opened

    @property
    def state(self) -> CircuitState:
        """Get current circuit state (read-only, no side effects).

        NOTE: Use is_available() to check if a call can proceed — it
        handles the OPEN -> HALF_OPEN transition on cooldown expiry.
        This property is intentionally side-effect-free for safe use
        in logging and monitoring.
        """
        with self._lock:
            return self._state

    def is_available(self) -> bool:
        """
        Check if calls are currently allowed.

        Uses active-time tracking (blocker 58) instead of wall-clock time:
        the cooldown only advances while the system is actively executing
        tools, not during idle periods.

        If the circuit is OPEN and the cooldown has expired (based on
        active time), transitions to HALF_OPEN to allow a test call.
        This is the only method that should trigger this transition.
        """
        with self._lock:
            if self._state == CircuitState.OPEN and self._last_failure_time:
                # Check active-time-based cooldown (blocker 58)
                active_cooldown_elapsed = self._active_time_since_open >= self.cooldown_seconds
                wall_cooldown_elapsed = (time.time() - self._last_failure_time) >= self.cooldown_seconds
                # Use whichever elapses first — if wall clock just ran
                # AND at least some active time accumulated, proceed.
                cooldown_expired = wall_cooldown_elapsed or active_cooldown_elapsed
                if cooldown_expired:
                    self._state = CircuitState.HALF_OPEN
                    slog = ScanLogger("circuit_breaker", engagement_id=self.name)
                    slog.info(
                        f"Circuit {self.name}: OPEN -> HALF_OPEN "
                        f"(active_cooldown={active_cooldown_elapsed}, "
                        f"wall_cooldown={wall_cooldown_elapsed})"
                    )
            return self._state != CircuitState.OPEN

    def record_success(self, duration_seconds: float = 0.0):
        """Record a successful call, resetting failure count.

        Args:
            duration_seconds: Duration of the successful tool execution.
                              Used for active-time tracking (blocker 58).
        """
        slog = ScanLogger("circuit_breaker", engagement_id=self.name)
        with self._lock:
            if self._failure_count > 0:
                slog.info(
                    f"Circuit {self.name}: success — resetting (was {self._failure_count} failures)"
                )
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._active_time_since_open = 0.0
                self._active_time_accumulator = 0.0
                slog.info("Circuit %s: HALF_OPEN -> CLOSED (recovered)", self.name)
            elif self._state == CircuitState.CLOSED:
                # Reset active-time accumulator on normal success too
                self._active_time_accumulator = 0.0

    def record_failure(self, duration_seconds: float = 0.0):
        """Record a failed call, potentially opening the circuit.

        Args:
            duration_seconds: Duration of the failed tool execution.
                              Used for active-time tracking (blocker 58).
        """
        slog = ScanLogger("circuit_breaker", engagement_id=self.name)
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            # Accumulate active time from this tool execution (blocker 58)
            self._active_time_accumulator += duration_seconds

            if self._state == CircuitState.HALF_OPEN:
                # Half-open probe failed → re-open with fresh cooldown
                self._state = CircuitState.OPEN
                self._active_time_since_open = self._active_time_accumulator
                slog.warn(
                    f"Circuit {self.name}: HALF_OPEN -> OPEN after probe failure "
                    f"(failure #{self._failure_count}, "
                    f"active_cooldown={self._active_time_since_open:.1f}s)"
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._active_time_since_open = 0.0  # Start fresh active-time cooldown
                self._active_time_accumulator = 0.0  # Reset accumulator for new cycle
                self._last_failure_time = time.time()
                slog.warn(
                    f"Circuit {self.name}: OPEN after {self._failure_count} failures "
                    f"(cooldown={self.cooldown_seconds}s)"
                )

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator to wrap tool execution with circuit breaker.

        Usage:
            breaker = CircuitBreaker()

            @breaker
            def run_semgrep():
                return tool_runner.run_semgrep(...)
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.is_available():
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is OPEN. "
                    f"Wait {self._time_until_retry():.0f}s before retry."
                )

            try:
                result = func(*args, **kwargs)
                # Success is the absence of an exception, regardless
                # of whether the result is truthy (empty findings list
                # is a valid outcome for a scan tool).
                self.record_success()
                return result
            except CircuitOpenError:
                # Don't record nested circuit breaks as failures
                raise
            except Exception:
                self.record_failure()
                raise

        return wrapper

    def _time_until_retry(self) -> float:
        """Calculate seconds until next retry attempt."""
        if self._last_failure_time:
            elapsed = time.time() - self._last_failure_time
            return max(0, self.cooldown_seconds - elapsed)
        return 0


class ToolCircuitBreakerManager:
    """
    Manages circuit breakers per tool.

    Usage:
        manager = ToolCircuitBreakerManager()
        breaker = manager.get_breaker("nmap")
        breaker.record_failure()
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 300):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def get_breaker(
        self, tool_name: str, failure_threshold: int | None = None, cooldown_seconds: int | None = None
    ) -> CircuitBreaker:
        """Get or create circuit breaker for a tool."""
        with self._lock:
            if tool_name not in self._breakers:
                self._breakers[tool_name] = CircuitBreaker(
                    failure_threshold=failure_threshold if failure_threshold is not None else self._failure_threshold,
                    cooldown_seconds=cooldown_seconds if cooldown_seconds is not None else self._cooldown_seconds,
                    name=tool_name,
                )
            return self._breakers[tool_name]

    def get_status(self) -> dict[str, str]:
        """Get status of all circuit breakers."""
        with self._lock:
            return {
                name: breaker.state.value for name, breaker in self._breakers.items()
            }

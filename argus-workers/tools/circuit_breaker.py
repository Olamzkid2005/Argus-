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

from utils.logging_utils import ScanLogger


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
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
        name: str | None = None
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

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for cooldown expiry."""
        with self._lock:
            if self._state == CircuitState.OPEN and self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
            return self._state

    def is_available(self) -> bool:
        """Check if calls are currently allowed."""
        return self.state != CircuitState.OPEN

    def record_success(self):
        """Record a successful call, resetting failure count."""
        slog = ScanLogger("circuit_breaker", engagement_id=self.name)
        with self._lock:
            if self._failure_count > 0:
                slog.info(f"Circuit {self.name}: success — resetting (was {self._failure_count} failures)")
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                slog.info(f"Circuit {self.name}: HALF_OPEN -> CLOSED (recovered)")

    def record_failure(self):
        """Record a failed call, potentially opening the circuit."""
        slog = ScanLogger("circuit_breaker", engagement_id=self.name)
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                slog.warn(f"Circuit {self.name}: OPEN after {self._failure_count} failures (cooldown={self.cooldown_seconds}s)")

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


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and call is attempted."""
    pass


class ToolCircuitBreakerManager:
    """
    Manages circuit breakers per tool.

    Usage:
        manager = ToolCircuitBreakerManager()
        breaker = manager.get_breaker("nmap")
        breaker.record_failure()
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def get_breaker(
        self,
        tool_name: str,
        failure_threshold: int = 3,
        cooldown_seconds: int = 300
    ) -> CircuitBreaker:
        """Get or create circuit breaker for a tool."""
        with self._lock:
            if tool_name not in self._breakers:
                self._breakers[tool_name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    cooldown_seconds=cooldown_seconds,
                    name=tool_name
                )
            return self._breakers[tool_name]

    def get_status(self) -> dict[str, str]:
        """Get status of all circuit breakers."""
        with self._lock:
            return {
                name: breaker.state.value
                for name, breaker in self._breakers.items()
            }

"""
Per-host rate limiting for tool execution.

Prevents accidentally overwhelming fragile targets by limiting the
rate of requests to any single host. Uses a sliding-window algorithm
per hostname extracted from tool arguments.

Usage at the call site:
    from runtime.rate_limiter import PER_HOST_LIMITER
    PER_HOST_LIMITER.acquire(target_hostname)

Cross-tool coordination (blocker 44):
    The module-level singleton PER_HOST_LIMITER is shared across all tools.
    Additionally, the backpressure system tracks 429/rate-limited responses
    and dynamically reduces the per-host rate limit when backpressure is detected.
"""

import logging
import re
import threading
import time
from collections import defaultdict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Pattern to extract hostname from common tool argument patterns
# Handles: -u https://host, --url https://host, https://host, host:port
_HOST_PATTERN = re.compile(
    r"(?:https?://)?([a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)*)"
)


def extract_host(text: str) -> str | None:
    """Extract a hostname from a tool argument string."""
    # Try parsing as URL first
    text = text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        try:
            return urlparse(text).hostname
        except ValueError:
            logger.debug("Failed to parse URL: %s, falling back to regex", text[:100])
    # Fall back to regex
    m = _HOST_PATTERN.match(text)
    if m:
        return m.group(1).lower()
    return None


class PerHostRateLimiter:
    """Sliding-window rate limiter keyed by target hostname.

    Supports dynamic backpressure: when a tool reports a 429/rate-limited
    response for a host, the per-host rate is automatically reduced.
    The rate recovers back to the configured level over time.

    This is a module-level singleton (PER_HOST_LIMITER) so all tools
    share the same rate limit state — making it truly cross-tool (blocker 44).
    """

    def __init__(self, requests_per_second: int = 10):
        self.base_rps = requests_per_second
        self._enabled = requests_per_second > 0
        self._host_timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Backpressure tracking per host (blocker 44)
        self._host_backpressure: dict[str, dict] = defaultdict(
            lambda: {
                "consecutive_429s": 0,
                "current_rps": requests_per_second,
                "last_backpressure_time": 0.0,
                "backpressure_window_end": 0.0,  # when backpressure expires
            }
        )

    @property
    def rps(self) -> int:
        """Current effective RPS (may be reduced by backpressure)."""
        # Return the global base rate (per-host RPS varies)
        return self.base_rps

    def _get_host_rps(self, host: str) -> float:
        """Get the effective RPS for a host, accounting for backpressure."""
        bp = self._host_backpressure[host]
        now = time.time()
        # Check if backpressure window has expired
        if bp["backpressure_window_end"] > 0 and now > bp["backpressure_window_end"]:
            # Backpressure window expired — restore full rate
            bp["current_rps"] = float(self.base_rps)
            bp["consecutive_429s"] = 0
            bp["backpressure_window_end"] = 0.0
        return bp["current_rps"]

    def record_backpressure(self, host: str) -> None:
        """Record a 429/rate-limited response for a host.

        Each consecutive 429 reduces the effective per-host rate:
        - 1st 429: reduce to 50% (5 req/s for default 10)
        - 2nd 429: reduce to 25% (2.5 req/s)
        - 3rd+ 429: reduce to 10% (1 req/s)

        Backpressure decays after 60 seconds without additional 429s.

        Args:
            host: The hostname that returned a 429.
        """
        with self._lock:
            bp = self._host_backpressure[host]
            bp["consecutive_429s"] += 1
            bp["last_backpressure_time"] = time.time()
            # Extend backpressure window: 60s from now
            bp["backpressure_window_end"] = time.time() + 60.0

            consecutive = bp["consecutive_429s"]
            if consecutive >= 3:
                bp["current_rps"] = max(1.0, float(self.base_rps) * 0.1)
            elif consecutive >= 2:
                bp["current_rps"] = max(1.0, float(self.base_rps) * 0.25)
            else:
                bp["current_rps"] = max(1.0, float(self.base_rps) * 0.5)

            logger.warning(
                "Backpressure applied to host %s: %d consecutive 429s — "
                "reduced rate to %.1f req/s for 60s",
                host,
                consecutive,
                bp["current_rps"],
            )

    def clear_backpressure(self, host: str) -> None:
        """Clear backpressure for a host (called on successful non-429 response)."""
        with self._lock:
            if host in self._host_backpressure:
                bp = self._host_backpressure[host]
                bp["consecutive_429s"] = 0
                bp["current_rps"] = float(self.base_rps)
                bp["backpressure_window_end"] = 0.0

    def acquire(self, host: str | None) -> bool:
        """
        Block until a rate slot is available for the given host.

        Uses the per-host effective RPS (which may be reduced by backpressure).
        Uses a 1-second sliding window per hostname.

        Returns True if rate limited, False if no host provided or rate limiting disabled.
        """
        if not self._enabled or not host:
            return False

        with self._lock:
            now = time.time()
            window_start = now - 1.0  # 1-second sliding window

            # Get effective RPS for this host (accounting for backpressure)
            effective_rps = self._get_host_rps(host)

            # Prune timestamps outside the window
            self._host_timestamps[host] = [t for t in self._host_timestamps[host] if t > window_start]

            if len(self._host_timestamps[host]) >= int(effective_rps):
                # Need to wait — calculate sleep time
                sleep_time = self._host_timestamps[host][0] + 1.0 - now
                if sleep_time > 0:
                    logger.debug(
                        "Rate limiting host %s — sleeping %.2fs (%.1f req/s limit)",
                        host, sleep_time, effective_rps,
                    )
                    time.sleep(sleep_time)
                    # After sleeping, update window
                    now = time.time()
                    self._host_timestamps[host] = [t for t in self._host_timestamps[host] if t > now - 1.0]

            self._host_timestamps[host].append(time.time())
            return True

    def set_rate(self, requests_per_second: int):
        """Update the rate limit. 0 disables limiting."""
        self._enabled = requests_per_second > 0
        self.base_rps = max(0, requests_per_second)
        # Reset backpressure states for all hosts
        with self._lock:
            for host in self._host_backpressure:
                bp = self._host_backpressure[host]
                bp["current_rps"] = float(self.base_rps)
                bp["consecutive_429s"] = 0
                bp["backpressure_window_end"] = 0.0

    def get_status(self, host: str | None = None) -> dict:
        """Get the current rate limiter status.

        Args:
            host: Optional hostname to get status for. If None, returns summary.

        Returns:
            Status dict with backpressure and rate info.
        """
        with self._lock:
            if host:
                bp = self._host_backpressure.get(host)
                if bp:
                    return {
                        "host": host,
                        "base_rps": self.base_rps,
                        "effective_rps": bp["current_rps"],
                        "consecutive_429s": bp["consecutive_429s"],
                        "backpressure_active": time.time() < bp["backpressure_window_end"],
                    }
                return {"host": host, "base_rps": self.base_rps, "effective_rps": float(self.base_rps)}
            return {
                "base_rps": self.base_rps,
                "hosts_with_backpressure": [
                    h for h, bp in self._host_backpressure.items()
                    if bp["consecutive_429s"] > 0
                ],
            }


# Module-level singleton — shared across all tools (blocker 44)
PER_HOST_LIMITER = PerHostRateLimiter()

"""
Per-host rate limiting for tool execution.

Prevents accidentally overwhelming fragile targets by limiting the
rate of requests to any single host. Uses a sliding-window algorithm
per hostname extracted from tool arguments.

Usage at the call site:
    from runtime.rate_limiter import PER_HOST_LIMITER
    PER_HOST_LIMITER.acquire(target_hostname)
"""

import logging
import re
import time
import threading
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
            pass
    # Fall back to regex
    m = _HOST_PATTERN.match(text)
    if m:
        return m.group(1).lower()
    return None


class PerHostRateLimiter:
    """Sliding-window rate limiter keyed by target hostname."""
    
    def __init__(self, requests_per_second: int = 10):
        self.rps = requests_per_second
        self._enabled = requests_per_second > 0
        self._host_timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def acquire(self, host: str | None) -> bool:
        """
        Block until a rate slot is available for the given host.
        
        Returns True if rate limited, False if no host provided or rate limiting disabled.
        """
        if not self._enabled or not host:
            return False
        
        with self._lock:
            now = time.time()
            window_start = now - 1.0  # 1-second sliding window
            
            # Prune timestamps outside the window
            self._host_timestamps[host] = [t for t in self._host_timestamps[host] if t > window_start]
            
            if len(self._host_timestamps[host]) >= self.rps:
                # Need to wait — calculate sleep time
                sleep_time = self._host_timestamps[host][0] + 1.0 - now
                if sleep_time > 0:
                    logger.debug(
                        "Rate limiting host %s — sleeping %.2fs (%d req/s limit)",
                        host, sleep_time, self.rps,
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
        self.rps = max(0, requests_per_second)


# Module-level singleton
PER_HOST_LIMITER = PerHostRateLimiter()

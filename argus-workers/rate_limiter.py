"""
Rate limiting and target protection for Argus Pentest Platform.

This module implements per-domain rate limiting with adaptive slowdown,
circuit breaker patterns, and robots.txt respect.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RateLimitEventType(Enum):
    """Types of rate limit events."""
    THROTTLED = "throttled"
    BACKOFF_429 = "backoff_429"
    BACKOFF_503 = "backoff_503"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"
    RATE_INCREASED = "rate_increased"
    RATE_DECREASED = "rate_decreased"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_second: float = 5.0
    concurrent_requests: int = 2
    respect_robots_txt: bool = True
    adaptive_slowdown: bool = True


class DomainRateLimiter:
    """
    Per-domain rate limiter with adaptive slowdown and circuit breaker.

    Implements:
    - Token bucket algorithm for RPS limiting
    - Semaphore for concurrent request limiting
    - Adaptive rate adjustment based on target responses
    - Circuit breaker for consecutive errors
    """

    def __init__(
        self,
        domain: str,
        config: RateLimitConfig,
        db_connection=None
    ):
        """
        Initialize domain rate limiter.

        Args:
            domain: Target domain (e.g., "example.com")
            config: Rate limit configuration
            db_connection: Database connection for logging events
        """
        self.domain = domain
        self.config = config
        self.db = db_connection

        # Token bucket for RPS limiting
        self.current_rps = config.requests_per_second
        self.tokens = config.requests_per_second
        self.last_refill = time.time()

        # Semaphore for concurrent request limiting - lazy init to avoid creating outside event loop
        self._semaphore: asyncio.Semaphore | None = None

        # Adaptive rate limiting state
        self.consecutive_errors = 0
        self.consecutive_successes = 0
        self.circuit_breaker_open = False
        self.circuit_breaker_until = 0

        # Backoff state
        self.backoff_until = 0

        # Robots.txt crawl delay
        self.robots_crawl_delay: float | None = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazy initialization of semaphore to avoid creating outside event loop"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.concurrent_requests)
        return self._semaphore

    async def throttle(self) -> None:
        """
        Throttle request to maintain configured RPS.

        Uses token bucket algorithm:
        - Tokens refill at current_rps rate
        - Each request consumes 1 token
        - If no tokens available, wait until refill
        """
        # Check circuit breaker
        if self.circuit_breaker_open:
            current_time = time.time()
            if current_time < self.circuit_breaker_until:
                wait_time = self.circuit_breaker_until - current_time
                logger.warning(
                    f"Circuit breaker open for {self.domain}, "
                    f"waiting {wait_time:.1f}s"
                )
                await asyncio.sleep(wait_time)
            else:
                # Close circuit breaker
                self.circuit_breaker_open = False
                self.consecutive_errors = 0
                await self._log_event(RateLimitEventType.CIRCUIT_BREAKER_CLOSED)
                logger.info(f"Circuit breaker closed for {self.domain}")

        # Check backoff
        if self.backoff_until > time.time():
            wait_time = self.backoff_until - time.time()
            logger.info(f"Backoff active for {self.domain}, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            self.backoff_until = 0

        # Apply robots.txt crawl delay if configured
        if self.config.respect_robots_txt and self.robots_crawl_delay:
            effective_rps = min(
                self.current_rps,
                1.0 / self.robots_crawl_delay
            )
        else:
            effective_rps = self.current_rps

        # Refill tokens based on time elapsed
        current_time = time.time()
        time_elapsed = current_time - self.last_refill
        self.tokens = min(
            effective_rps,
            self.tokens + (time_elapsed * effective_rps)
        )
        self.last_refill = current_time

        # Wait if no tokens available
        if self.tokens < 1.0:
            wait_time = (1.0 - self.tokens) / effective_rps
            logger.debug(
                f"Rate limiting {self.domain}: waiting {wait_time:.3f}s "
                f"(current RPS: {self.current_rps:.2f})"
            )
            await asyncio.sleep(wait_time)
            self.tokens = 1.0
            self.last_refill = time.time()

        # Consume token
        self.tokens -= 1.0

        await self._log_event(RateLimitEventType.THROTTLED)

    async def record_success(self) -> None:
        """
        Record successful request.

        Increases rate gradually if adaptive slowdown enabled.
        """
        self.consecutive_errors = 0
        self.consecutive_successes += 1

        # Gradually increase rate on consistent success
        if (
            self.config.adaptive_slowdown and
            self.consecutive_successes >= 10 and
            self.current_rps < self.config.requests_per_second
        ):
            old_rps = self.current_rps
            self.current_rps = min(
                self.config.requests_per_second,
                self.current_rps * 1.1  # Increase by 10%
            )
            self.consecutive_successes = 0

            logger.info(
                f"Increased rate for {self.domain}: "
                f"{old_rps:.2f} -> {self.current_rps:.2f} RPS"
            )
            await self._log_event(RateLimitEventType.RATE_INCREASED)

    async def record_error(self, status_code: int) -> None:
        """
        Record error response and adapt rate limiting.

        Args:
            status_code: HTTP status code
        """
        self.consecutive_successes = 0
        self.consecutive_errors += 1

        if not self.config.adaptive_slowdown:
            return

        # Handle 429 Too Many Requests
        if status_code == 429:
            old_rps = self.current_rps
            self.current_rps *= 0.25  # Reduce by 75%
            self.backoff_until = time.time() + 60  # 60 second backoff

            logger.warning(
                f"429 response from {self.domain}: "
                f"reduced rate {old_rps:.2f} -> {self.current_rps:.2f} RPS, "
                f"backing off 60s"
            )
            await self._log_event(
                RateLimitEventType.BACKOFF_429,
                status_code=status_code
            )

        # Handle 503 Service Unavailable
        elif status_code == 503:
            old_rps = self.current_rps
            self.current_rps *= 0.5  # Reduce by 50%
            self.backoff_until = time.time() + 30  # 30 second backoff

            logger.warning(
                f"503 response from {self.domain}: "
                f"reduced rate {old_rps:.2f} -> {self.current_rps:.2f} RPS, "
                f"backing off 30s"
            )
            await self._log_event(
                RateLimitEventType.BACKOFF_503,
                status_code=status_code
            )

        # Trigger circuit breaker after 5 consecutive errors
        if self.consecutive_errors >= 5:
            self.circuit_breaker_open = True
            self.circuit_breaker_until = time.time() + 300  # 5 minute backoff

            logger.error(
                f"Circuit breaker triggered for {self.domain} "
                f"after {self.consecutive_errors} consecutive errors"
            )
            await self._log_event(
                RateLimitEventType.CIRCUIT_BREAKER_OPEN,
                status_code=status_code
            )

    def set_robots_crawl_delay(self, delay: float) -> None:
        """
        Set crawl delay from robots.txt.

        Args:
            delay: Crawl delay in seconds
        """
        self.robots_crawl_delay = delay
        logger.info(
            f"Set robots.txt crawl delay for {self.domain}: {delay}s"
        )

    async def _log_event(
        self,
        event_type: RateLimitEventType,
        status_code: int | None = None
    ) -> None:
        """
        Log rate limit event to database.

        Args:
            event_type: Type of rate limit event
            status_code: HTTP status code if applicable
        """
        if not self.db:
            return

        try:
            from database.repositories.rate_limit_repository import RateLimitRepository

            repo = RateLimitRepository(self.db)
            repo.create_event(
                domain=self.domain,
                event_type=event_type.value,
                status_code=status_code,
                current_rps=self.current_rps
            )
        except Exception as e:
            logger.error(f"Failed to log rate limit event: {e}")


class TargetRateController:
    """
    Manages rate limiters for multiple target domains.

    Creates and caches DomainRateLimiter instances per domain.
    """

    def __init__(self, db_connection=None):
        """
        Initialize target rate controller.

        Args:
            db_connection: Database connection for logging events
        """
        self.db = db_connection
        self.limiters: dict[str, DomainRateLimiter] = {}

    def get_limiter(
        self,
        target_url: str,
        config: RateLimitConfig | None = None
    ) -> DomainRateLimiter:
        """
        Get or create rate limiter for target domain.

        Args:
            target_url: Target URL
            config: Rate limit configuration (uses defaults if None)

        Returns:
            DomainRateLimiter for the target domain
        """
        # Extract domain from URL
        parsed = urlparse(target_url)
        domain = parsed.netloc or parsed.path

        # Return existing limiter if available
        if domain in self.limiters:
            return self.limiters[domain]

        # Create new limiter
        if config is None:
            config = RateLimitConfig()

        limiter = DomainRateLimiter(domain, config, self.db)
        self.limiters[domain] = limiter

        logger.info(
            f"Created rate limiter for {domain}: "
            f"{config.requests_per_second} RPS, "
            f"{config.concurrent_requests} concurrent"
        )

        return limiter

    def clear_limiter(self, target_url: str) -> None:
        """
        Clear rate limiter for target domain.

        Args:
            target_url: Target URL
        """
        parsed = urlparse(target_url)
        domain = parsed.netloc or parsed.path

        if domain in self.limiters:
            del self.limiters[domain]
            logger.info(f"Cleared rate limiter for {domain}")

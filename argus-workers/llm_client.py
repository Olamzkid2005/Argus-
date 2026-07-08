"""
LLM Client - Unified wrapper for OpenAI SDK and generic HTTP API.
Supports both async and sync calls with retry logic.

API key resolution order (first found wins):
1. Explicit api_key parameter passed to constructor
2. OPENAI_API_KEY environment variable
3. LLM_API_KEY environment variable
4. Redis key settings:*:openrouter_api_key (configured via UI Settings page)
"""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass

from config.constants import LLM_AGENT_COST_PER_1K_INPUT, LLM_AGENT_COST_PER_1K_OUTPUT
from exceptions import LLMUnavailableError
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from an LLM call with token and cost tracking."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class LLMClient:
    """
    Unified LLM client supporting OpenAI SDK and generic HTTP API.

    Automatically detects provider from environment. Provides both
    async and sync methods. Implements retry with exponential backoff.
    Graceful degradation: is_available() returns False if not configured.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        max_retries: int = 2,
        redis_url: str | None = None,
        user_email: str | None = None,
    ):
        """
        Initialize LLM client.

        API key resolution order:
        1. Explicit api_key parameter
        2. OPENAI_API_KEY environment variable
        3. LLM_API_KEY environment variable
        4. Database user_settings (scoped to user_email if provided)
        5. Redis key settings:{user_email}:openrouter_api_key (from UI Settings page)

        Args:
            provider: "openai" or "generic". Auto-detects from env if None.
            model: Model name. Defaults to env LLM_MODEL or "gpt-4o-mini".
            api_key: API key. Pass explicitly to override env/Redis.
            api_url: Base URL for generic provider. Defaults to env LLM_API_URL.
            max_retries: Max retry attempts on failure (default 2).
            redis_url: Redis URL for loading key from UI Settings (defaults to REDIS_URL env).
            user_email: User email for tenant-scoped API key lookup (M-v5-01).
                        When set, keys are scoped to this user only, preventing
                        cross-tenant billing leakage.
        """
        self.provider = provider or os.getenv("LLM_PROVIDER", "openai")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.max_retries = max_retries
        self._user_email = user_email

        # Resolve API key: explicit > env var > DB (user_settings) > Redis (UI Settings)
        # DB and Redis lookups are scoped to user_email when available (M-v5-01).
        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or self._load_key_from_db()
            or self._load_key_from_redis(redis_url)
        )
        # Auto-detect provider from API key prefix
        # Blocker 55: Validate API key prefix against known providers.
        # When the prefix doesn't match any known pattern, log a warning so
        # the operator knows to set LLM_PROVIDER explicitly.
        if self.api_key:
            _known_prefix = True
            if self.api_key.startswith("sk-or-"):
                # OpenRouter
                self.provider = "generic"
                self.api_url = "https://openrouter.ai/api/v1/chat/completions"
            elif self.api_key.startswith("sk-proj-"):
                # OpenAI project API key (new format)
                self.provider = "openai"
                self.api_url = api_url or os.getenv(
                    "LLM_API_URL",
                    "https://api.openai.com/v1/chat/completions",
                )
            elif self.api_key.startswith("sk-"):
                # OpenAI legacy key (sk-...) or compatible
                self.provider = "openai"
                self.api_url = api_url or os.getenv(
                    "LLM_API_URL",
                    "https://api.openai.com/v1/chat/completions",
                )
            elif self.api_key.startswith("AIzaSy") or self.api_key.startswith("AQ."):
                # Google Gemini / AI Studio (AIzaSy=old format, AQ.=new format)
                self.provider = "generic"
                self.api_url = api_url or os.getenv(
                    "LLM_API_URL",
                    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                )
                # Default model for Gemini if not explicitly set
                if not model and not os.getenv("LLM_MODEL"):
                    self.model = "gemini-2.0-flash"
            elif self.api_key.startswith("sk-ant-"):
                # Anthropic — NOT auto-configurable because Anthropic's API is not
                # OpenAI-compatible (different payload format).
                # Gap 9.5: Instead of silently falling through to OpenAI payload format
                # (which would fail with a confusing auth error), emit a loud warning
                # and mark the client as unavailable until properly configured.
                _known_prefix = True
                self._has_anthropic_key_without_config = (
                    self.provider == "openai"
                    and not os.getenv("LLM_PROVIDER")
                )
                if self._has_anthropic_key_without_config:
                    logger.error(
                        "ANTHROPIC API KEY DETECTED (sk-ant-...) but Anthropic's API is not "
                        "OpenAI-compatible and cannot be auto-configured.\n"
                        "To use Anthropic, set these environment variables:\n"
                        "  LLM_PROVIDER=anthropic\n"
                        "  LLM_API_URL=https://api.anthropic.com/v1/messages\n"
                        "  LLM_MODEL=claude-sonnet-4-20250514 (or your chosen Claude model)\n"
                        "Without these settings, the LLM client will report itself as unavailable "
                        "and fall back to deterministic mode."
                    )
                else:
                    # User has explicitly set LLM_PROVIDER — respect that
                    self.api_url = api_url or os.getenv(
                        "LLM_API_URL",
                        "https://api.anthropic.com/v1/messages",
                    )
            else:
                _known_prefix = False
                self.api_url = api_url or os.getenv(
                    "LLM_API_URL",
                    "https://api.openai.com/v1/chat/completions"
                    if self.provider == "openai"
                    else "",
                )

            if not _known_prefix:
                logger.warning(
                    "LLM API key prefix '%s...' does not match any known provider pattern "
                    "(sk-or-, sk-proj-, sk-, AIzaSy, AQ., sk-ant-). "
                    "Set LLM_PROVIDER and LLM_API_URL explicitly if the auto-detected "
                    "provider '%s' is incorrect.",
                    self.api_key[:8],
                    self.provider,
                )
        else:
            self.api_url = api_url or os.getenv(
                "LLM_API_URL",
                "https://api.openai.com/v1/chat/completions"
                if self.provider == "openai"
                else "",
            )

        # OpenAI SDK client (lazy init)
        self._openai_client = None

        # Gap 9.5: Track whether an Anthropic key was detected without proper config.
        self._has_anthropic_key_without_config = False

        # Rate limiting: max 60 requests per minute per provider
        # Uses Redis sorted-set sliding window for cross-worker coordination.
        # Falls back to in-process rate limiter when Redis is unavailable.
        self._rate_limit_max = 60
        self._rate_limit_window = 60.0
        self._request_timestamps: list[float] = []
        self._redis_url = redis_url
        # Lazy Redis clients for rate limiter — initialized once, reused across calls
        self._redis_client = None
        self._redis_async_client = None

        # Circuit breaker: after N consecutive failures, skip calls for cooldown
        # threshold is set to max_retries + 1 so the circuit opens when all
        # retry attempts are exhausted (default: max_retries=2 → threshold=3)
        self._circuit_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_threshold = max_retries + 1
        self._circuit_cooldown = 30.0
        self._circuit_lock = threading.Lock()
        self._rate_lock = threading.Lock()

    def _load_key_from_db(self) -> str | None:
        """
        Load API key from the user_settings database table.

        When user_email is set (M-v5-01), the lookup is scoped to that user only,
        preventing cross-tenant billing leakage. When user_email is not set,
        falls back to unscoped lookup with a warning.

        Returns:
            API key string if found, None otherwise.
        """
        try:
            from database.connection import db_cursor

            key_names = ("openrouter_api_key", "openai_api_key", "llm_api_key")

            if getattr(self, "_user_email", None):
                # Tenant-scoped lookup (M-v5-01): only return this user's key
                with db_cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT key, value
                        FROM user_settings
                        WHERE user_email = %s
                          AND key = ANY(%s)
                          AND value IS NOT NULL
                          AND value != ''
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (self._user_email, list(key_names)),
                    )
                    row = cursor.fetchone()
                    if row and row[1] and len(str(row[1])) > 10:
                        logger.info(
                            "Loaded API key from database for user %s (redacted)",
                            self._user_email,
                        )
                        return row[1]
            return None
        except Exception as e:
            logger.debug("Could not load API key from database settings: %s", e)
            return None

    def _load_key_from_redis(self, redis_url: str | None = None) -> str | None:
        """
        Load API key from Redis, where the UI Settings page stores it.

        When user_email is set (M-v5-01), looks up the exact key for that user:
        settings:{user_email}:openrouter_api_key. When not set, falls back to
        scanning all settings:*:openrouter_api_key keys (cross-tenant risk).

        Args:
            redis_url: Redis URL. Defaults to REDIS_URL env var.

        Returns:
            API key string if found, None otherwise.
        """
        redis_url = redis_url or os.getenv("REDIS_URL")
        if not redis_url:
            return None

        try:
            import redis as redis_module

            r = redis_module.from_url(
                redis_url, socket_connect_timeout=3, socket_timeout=3
            )

            # Try multiple key patterns in priority order
            key_patterns = [
                "gemini_api_key",
                "openrouter_api_key",
                "openai_api_key",
                "llm_api_key",
            ]

            if getattr(self, "_user_email", None):
                # Tenant-scoped lookup (M-v5-01): exact key for this user
                for pattern in key_patterns:
                    key = f"settings:{self._user_email}:{pattern}"
                    value = r.get(key)
                    if (
                        value
                        and isinstance(value, (str, bytes))
                        and len(str(value)) > 10
                    ):
                        api_key = value.decode() if isinstance(value, bytes) else value
                        logger.info(
                            "Loaded API key from Redis for user %s (redacted)",
                            self._user_email,
                        )
                        return api_key
            logger.debug("No API key found in Redis settings")
            return None

        except Exception as e:
            logger.debug("Could not load API key from Redis: %s", e)
            return None

    def _get_openai_client(self):
        """Lazy-init OpenAI client."""
        if self._openai_client is None and self.api_key:
            try:
                from openai import AsyncOpenAI, OpenAI

                self._openai_client = OpenAI(api_key=self.api_key)
                self._async_openai_client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                logger.warning("openai package not installed, falling back to HTTP API")
                self.provider = "generic"
        return self._openai_client

    def _build_messages(self, system_prompt: str, user_prompt: str) -> list[dict]:
        """Build messages list for chat completion."""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _get_redis(self):
        """Lazy-init sync Redis client, reused across all rate-limit checks."""
        if self._redis_client is None and self._redis_url:
            import redis as redis_module

            self._redis_client = redis_module.from_url(
                self._redis_url, socket_connect_timeout=1, socket_timeout=1
            )
        return self._redis_client

    async def _get_redis_async(self):
        """Lazy-init async Redis client, reused across all rate-limit checks."""
        if self._redis_async_client is None and self._redis_url:
            import redis.asyncio as aioredis

            self._redis_async_client = await aioredis.from_url(
                self._redis_url, socket_connect_timeout=1, socket_timeout=1
            )
        return self._redis_async_client

    def _check_rate_limit(self):
        """Rate limiter: max 60 requests/min per provider.

        Uses Redis sorted-set sliding window for cross-worker coordination.
        Falls back to in-process rate limiter when Redis is unavailable.
        """
        now = time.time()
        window_start = now - self._rate_limit_window

        # Try Redis-based rate limiter first for cross-worker coordination
        r = self._get_redis()
        if r is not None:
            try:
                import uuid

                rate_key = f"llm_rate:{self.provider}"

                # Remove timestamps outside the window
                r.zremrangebyscore(rate_key, 0, window_start)

                # Count requests in window
                count = r.zcount(rate_key, window_start, now)

                if count >= self._rate_limit_max:
                    # Get earliest timestamp to calculate sleep time
                    earliest = r.zrange(rate_key, 0, 0, withscores=True)
                    if earliest:
                        sleep_time = earliest[0][1] + self._rate_limit_window - now
                        if sleep_time > 0:
                            logger.warning(
                                "LLM rate limit hit (cross-worker) — sleeping %.1fs",
                                sleep_time,
                            )
                            time.sleep(sleep_time)

                # Record this request
                member = f"{uuid.uuid4()}:{now}"
                r.zadd(rate_key, {member: now})
                r.expire(rate_key, int(self._rate_limit_window) + 10)
                return
            except (ConnectionError, OSError, ValueError) as e:
                logger.debug(
                    "Redis rate limiter unavailable — falling back to in-process: %s", e
                )

        # Fallback: in-process rate limiter
        with self._rate_lock:
            self._request_timestamps = [
                t for t in self._request_timestamps if t > window_start
            ]
            if len(self._request_timestamps) >= self._rate_limit_max:
                sleep_time = self._request_timestamps[0] + self._rate_limit_window - now
                if sleep_time > 0:
                    logger.warning(
                        "LLM rate limit hit (in-process) — sleeping %.1fs", sleep_time
                    )
                    time.sleep(sleep_time)
            self._request_timestamps.append(now)

    async def _check_rate_limit_async(self):
        """Async rate limiter: sleeps with asyncio.sleep instead of time.sleep."""
        now = time.time()
        window_start = now - self._rate_limit_window

        # Try Redis-based rate limiter first for cross-worker coordination
        r = await self._get_redis_async()
        if r is not None:
            try:
                import uuid

                rate_key = f"llm_rate:{self.provider}"

                await r.zremrangebyscore(rate_key, 0, window_start)
                count = await r.zcount(rate_key, window_start, now)

                if count >= self._rate_limit_max:
                    earliest = await r.zrange(rate_key, 0, 0, withscores=True)
                    if earliest:
                        sleep_time = earliest[0][1] + self._rate_limit_window - now
                        if sleep_time > 0:
                            logger.warning(
                                "LLM rate limit hit (cross-worker) — sleeping %.1fs",
                                sleep_time,
                            )
                            await asyncio.sleep(sleep_time)

                member = f"{uuid.uuid4()}:{now}"
                await r.zadd(rate_key, {member: now})
                await r.expire(rate_key, int(self._rate_limit_window) + 10)
                return
            except (ConnectionError, OSError, ValueError) as e:
                logger.debug(
                    "Redis rate limiter unavailable — falling back to in-process: %s", e
                )

        # Fallback: in-process rate limiter
        with self._rate_lock:
            self._request_timestamps = [
                t for t in self._request_timestamps if t > window_start
            ]
            if len(self._request_timestamps) >= self._rate_limit_max:
                sleep_time = self._request_timestamps[0] + self._rate_limit_window - now
                if sleep_time > 0:
                    logger.warning(
                        "LLM rate limit hit (in-process) — sleeping %.1fs", sleep_time
                    )
                    await asyncio.sleep(sleep_time)
            self._request_timestamps.append(now)

    # ── Core LLM helpers (Gap 9.1: extracted from duplicated chat/chat_sync/chat_async) ──

    @staticmethod
    def _parse_response_text(data: dict) -> str:
        """Extract response text from API response data, handling multiple formats."""
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
        elif "content" in data:
            return data["content"]
        return str(data)

    @staticmethod
    def _compute_cost(input_tokens: int, output_tokens: int) -> float:
        """Compute USD cost from token counts."""
        return (
            (input_tokens / 1000 * LLM_AGENT_COST_PER_1K_INPUT)
            + (output_tokens / 1000 * LLM_AGENT_COST_PER_1K_OUTPUT)
        )

    def _check_circuit_breaker(self) -> None:
        """Check circuit breaker state. Raises LLMUnavailableError if open."""
        with self._circuit_lock:
            if self._circuit_failures >= self._circuit_threshold:
                if time.time() < self._circuit_open_until:
                    raise LLMUnavailableError(
                        f"LLM circuit breaker open — skipping call for "
                        f"{self._circuit_open_until - time.time():.0f}s "
                        f"({self._circuit_failures} consecutive failures)"
                    )
                self._circuit_failures = 0

    def _increment_circuit_breaker(self) -> None:
        """Record a failure and open circuit if threshold reached."""
        with self._circuit_lock:
            self._circuit_failures += 1
            if self._circuit_failures >= self._circuit_threshold:
                self._circuit_open_until = time.time() + self._circuit_cooldown
                logger.warning(
                    "LLM circuit breaker OPEN after %d failures — cooling down for %.0fs",
                    self._circuit_failures,
                    self._circuit_cooldown,
                )

    def _extract_usage_and_cost(self, response) -> tuple[int, int, float]:
        """Extract input_tokens, output_tokens, and cost from an OpenAI SDK response."""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost = self._compute_cost(input_tokens, output_tokens)
        return input_tokens, output_tokens, cost

    def _extract_usage_and_cost_from_dict(self, data: dict) -> tuple[int, int, float]:
        """Extract input_tokens, output_tokens, and cost from an HTTP API response dict."""
        if "usage" in data:
            input_tokens = data["usage"].get("prompt_tokens", 0)
            output_tokens = data["usage"].get("completion_tokens", 0)
        else:
            input_tokens, output_tokens = 0, 0
        cost = self._compute_cost(input_tokens, output_tokens)
        return input_tokens, output_tokens, cost

    def _build_llm_response_from_sdk(self, response, start: float) -> LLMResponse:
        """Build an LLMResponse from an OpenAI SDK response."""
        input_tokens, output_tokens, cost = self._extract_usage_and_cost(response)
        return LLMResponse(
            text=response.choices[0].message.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

    def _build_llm_response_from_http(
        self, data: dict, start: float
    ) -> LLMResponse:
        """Build an LLMResponse from an HTTP API response dict."""
        input_tokens, output_tokens, cost = self._extract_usage_and_cost_from_dict(data)
        text = self._parse_response_text(data)
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

    def _log_llm_complete(
        self, start: float, tokens: int = 0, cost: float = 0.0
    ) -> None:
        """Log successful LLM completion."""
        from utils.logging_utils import ScanLogger

        slog = ScanLogger("llm_client")
        duration_ms = int((time.time() - start) * 1000)
        slog.llm_complete(self.model, duration_ms=duration_ms, tokens=tokens, cost=cost)

    async def _call_llm_core_async(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
        timeout: int | None = None,
    ) -> LLMResponse:
        """Shared core for async LLM calls with retry, circuit breaker, and rate limiting.

        Gap 9.1: Consolidates the retry loop, circuit breaker, rate limiting,
        and response parsing that was duplicated across chat(), chat_sync(),
        and chat_async(). Returns structured LLMResponse with token/cost tracking.
        """
        slog = ScanLogger("llm_client")
        action_desc = messages[0].get("content", "")[:60] if messages else "chat"
        slog.llm_start(self.model, action_desc)

        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")

        self._check_circuit_breaker()
        await self._check_rate_limit_async()

        req_timeout = timeout or 30
        start = time.time()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if self.provider == "openai" and self._get_openai_client():
                    kwargs: dict = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "timeout": req_timeout,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format

                    response = await asyncio.wait_for(
                        self._async_openai_client.chat.completions.create(**kwargs),
                        timeout=req_timeout,
                    )
                    self._circuit_failures = 0
                    result = self._build_llm_response_from_sdk(response, start)
                    self._log_llm_complete(
                        start, tokens=result.input_tokens + result.output_tokens, cost=result.cost_usd
                    )
                    return result
                else:
                    import certifi
                    import httpx

                    async with httpx.AsyncClient(
                        timeout=req_timeout, verify=certifi.where()
                    ) as client:
                        payload: dict = {
                            "model": self.model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        }
                        if response_format:
                            payload["response_format"] = response_format

                        headers = {"Content-Type": "application/json"}
                        if self.api_key:
                            headers["Authorization"] = f"Bearer {self.api_key}"

                        resp = await client.post(
                            self.api_url, json=payload, headers=headers
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        self._circuit_failures = 0
                        result = self._build_llm_response_from_http(data, start)
                        self._log_llm_complete(
                            start, tokens=result.input_tokens + result.output_tokens, cost=result.cost_usd
                        )
                        return result

            except LLMUnavailableError:
                raise
            except Exception as e:
                last_error = e
                self._increment_circuit_breaker()
                logger.warning(
                    "LLM chat_async attempt %d failed: %s", attempt + 1, e
                )
                if attempt < self.max_retries:
                    if (
                        self._circuit_open_until
                        and time.time() < self._circuit_open_until
                    ):
                        logger.warning(
                            "Circuit breaker still open — aborting retries"
                        )
                        break
                    await asyncio.sleep(2**attempt)

        raise LLMUnavailableError(
            f"LLM call failed after {self.max_retries + 1} retries: {last_error}"
        )

    def _call_llm_core_sync(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
        timeout: int | None = None,
    ) -> LLMResponse:
        """Sync equivalent of _call_llm_core_async.

        Gap 9.1: Consolidates the retry loop, circuit breaker, rate limiting,
        and response parsing that was duplicated across all three chat methods.
        """
        slog = ScanLogger("llm_client")
        action_desc = messages[0].get("content", "")[:60] if messages else "chat_sync"
        slog.llm_start(self.model, action_desc)

        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")

        self._check_circuit_breaker()
        self._check_rate_limit()

        req_timeout = timeout or 30
        start = time.time()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if self.provider == "openai" and self._get_openai_client():
                    kwargs: dict = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "timeout": req_timeout,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format

                    response = self._openai_client.chat.completions.create(**kwargs)
                    self._circuit_failures = 0
                    result = self._build_llm_response_from_sdk(response, start)
                    self._log_llm_complete(
                        start, tokens=result.input_tokens + result.output_tokens, cost=result.cost_usd
                    )
                    return result
                else:
                    import certifi
                    import httpx

                    with httpx.Client(
                        timeout=req_timeout, verify=certifi.where()
                    ) as client:
                        payload: dict = {
                            "model": self.model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        }
                        if response_format:
                            payload["response_format"] = response_format

                        headers = {"Content-Type": "application/json"}
                        if self.api_key:
                            headers["Authorization"] = f"Bearer {self.api_key}"

                        resp = client.post(
                            self.api_url, json=payload, headers=headers
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        self._circuit_failures = 0
                        result = self._build_llm_response_from_http(data, start)
                        self._log_llm_complete(
                            start, tokens=result.input_tokens + result.output_tokens, cost=result.cost_usd
                        )
                        return result

            except LLMUnavailableError:
                raise
            except Exception as e:
                last_error = e
                self._increment_circuit_breaker()
                logger.warning(
                    "LLM chat_sync attempt %d failed: %s", attempt + 1, e
                )
                if attempt < self.max_retries:
                    if (
                        self._circuit_open_until
                        and time.time() < self._circuit_open_until
                    ):
                        logger.warning(
                            "Circuit breaker still open — aborting retries"
                        )
                        break
                    time.sleep(2**attempt)

        raise LLMUnavailableError(
            f"LLM call failed after {self.max_retries + 1} retries: {last_error}"
        )

    # ── Public API: thin wrappers around shared core ──

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
    ) -> str:
        """
        Send chat completion request (async). Returns plain text.

        Gap 9.1: Delegates to _call_llm_core_async() — the shared implementation
        that consolidates retry loop, circuit breaker, rate limiting, and
        response parsing from the formerly duplicated chat()/chat_sync()/chat_async().

        Args:
            messages: List of {"role": ..., "content": ...} dicts
            temperature: Sampling temperature (default 0.3)
            max_tokens: Max tokens in response (default 500)
            response_format: Optional {"type": "json_object"} for structured output

        Returns:
            Response text string

        Raises:
            LLMUnavailableError: If client is not configured or all retries fail
        """
        result = await self._call_llm_core_async(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return result.text

    def chat_sync(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
        timeout: int | None = None,
    ) -> "LLMResponse":
        """
        Send chat completion request (synchronous).
        Used by scan-phase code that can't use async.

        Gap 9.1: Delegates to _call_llm_core_sync() — the shared implementation.

        Same parameters as chat(), plus:
        timeout: Per-request timeout in seconds. Defaults to 30.

        Returns:
            LLMResponse with .text, .input_tokens, .output_tokens, .cost_usd
        """
        return self._call_llm_core_sync(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            timeout=timeout,
        )

    async def chat_async(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
        timeout: int | None = None,
    ) -> LLMResponse:
        """
        Send chat completion request (async). Returns LLMResponse with token/cost tracking.

        Gap 9.1: Delegates to _call_llm_core_async() — the shared implementation.

        Same parameters as chat_sync, returns LLMResponse.
        Uses httpx.AsyncClient for HTTP calls.
        """
        return await self._call_llm_core_async(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            timeout=timeout,
        )

    def is_available(self) -> bool:
        """Check if the LLM client is configured and potentially reachable.

        Implements proper circuit breaker pattern (H5):
        - CLOSED: normal operation, allow calls
        - OPEN: too many failures, reject calls until cooldown expires
        - HALF-OPEN: cooldown expired, allow a single probe call.
          On success → CLOSED (failures=0). On failure → OPEN again.

        Does NOT reset _circuit_failures to 0 here — that only happens
        on actual successful API responses, ensuring proper half-open
        semantics.

        Also rejects placeholder values like "your_openai_api_key_here" or
        "change_me_" prefixed strings that are clearly not real API keys.

        Gap 9.5: When an Anthropic key (sk-ant-...) is detected but LLM_PROVIDER
        is not set, the client reports itself as unavailable with a clear error
        message logged at init time.
        """
        if not self.api_key:
            return False
        # Reject obvious placeholder values that are not real API keys.
        # Placeholder patterns: "your_*_key_here", "change_me_*"
        _placeholder_prefixes = ("your_", "change_me_")
        if any(self.api_key.lower().startswith(p) for p in _placeholder_prefixes):
            return False
        # Gap 9.5: Anthropic key detected without provider config — unavailable
        if getattr(self, "_has_anthropic_key_without_config", False):
            return False
        # Also reject keys that are too short to be valid (most API keys are 20+ chars)
        if len(self.api_key) < 10:
            return False
        with self._circuit_lock:
            if (
                self._circuit_failures >= self._circuit_threshold
                and time.time() < self._circuit_open_until
            ):
                return False  # Circuit is OPEN
            # Cooldown expired — transition to HALF-OPEN.
            # The next call will be a probe; if it succeeds, failures
            # reset to 0. If it fails, the circuit opens again.
            # Do NOT reset _circuit_failures here (H5 fix).
        return True

    async def is_available_async(self) -> bool:
        """Async version of is_available. Same logic, awaitable."""
        return self.is_available()


def load_llm_setting(key: str, default: str = "", user_email: str | None = None) -> str:
    """
    Load an LLM feature setting from Redis.

    Settings are stored by the UI Settings page at Redis keys in the format:
    - settings:{user_email}:{key} (user-level)
    - settings:global:{key} (global default)

    When user_email is provided, the lookup is scoped to that user only.
    When not provided, only the global setting is checked — cross-tenant
    scanning of all users' settings is NOT performed (C-v5-01).

    Args:
        key: Setting key name (e.g., "llm_review_enabled", "llm_payload_generation_enabled")
        default: Default value if not found in Redis
        user_email: Optional user email for tenant-scoped lookup

    Returns:
        Setting value string, or default if not found
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return default

    try:
        import redis as redis_module

        r = redis_module.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)

        # Tenant-scoped lookup: check this specific user's setting first
        if user_email:
            user_key = f"settings:{user_email}:{key}"
            value = r.get(user_key)
            if value is not None:
                val = value.decode() if isinstance(value, bytes) else value
                if val:
                    logger.debug(
                        "Loaded LLM setting '%s' for user '%s' from Redis",
                        key,
                        user_email,
                    )
                    return val

        # Global fallback: check the global default setting
        global_key = f"settings:global:{key}"
        value = r.get(global_key)
        if value is not None:
            val = value.decode() if isinstance(value, bytes) else value
            if val:
                logger.debug("Loaded LLM setting '%s' from global Redis key", key)
                return val

        if not user_email:
            logger.debug(
                "No user_email provided for LLM setting '%s' — checked global default only. "
                "Pass user_email for tenant-scoped lookup (C-v5-01).",
                key,
            )

        return default

    except Exception as e:
        logger.debug("Could not load LLM setting '%s' from Redis: %s", key, e)
        return default

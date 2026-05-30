"""
LLM Client - Unified wrapper for OpenAI SDK and generic HTTP API.
Supports both async and sync calls with retry logic.

API key resolution order (first found wins):
1. Explicit api_key parameter passed to constructor
2. OPENAI_API_KEY environment variable
3. LLM_API_KEY environment variable
4. Redis key settings:*:openrouter_api_key (configured via UI Settings page)
"""
import logging
import os
import threading
import time
from dataclasses import dataclass

from config.constants import LLM_AGENT_COST_PER_1K_INPUT, LLM_AGENT_COST_PER_1K_OUTPUT
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
        # Auto-detect OpenRouter: if key was loaded from Redis openrouter key or starts with sk-or-
        if self.api_key and self.api_key.startswith("sk-or-"):
            self.provider = "generic"
            self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        else:
            self.api_url = api_url or os.getenv("LLM_API_URL",
                "https://api.openai.com/v1/chat/completions" if self.provider == "openai" else ""
            )

        # OpenAI SDK client (lazy init)
        self._openai_client = None

        # Rate limiting: max 60 requests per minute per provider
        # Uses Redis sorted-set sliding window for cross-worker coordination.
        # Falls back to in-process rate limiter when Redis is unavailable.
        self._rate_limit_max = 60
        self._rate_limit_window = 60.0
        self._request_timestamps: list[float] = []
        self._redis_url = redis_url

        # Circuit breaker: after N consecutive failures, skip calls for cooldown
        # threshold must be <= max_retries + 1 to actually prevent retries (H-v4-09)
        self._circuit_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_threshold = 1  # Open after 1 failure — prevents wasted retries
        self._circuit_cooldown = 60.0
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

            if getattr(self, '_user_email', None):
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
                        logger.info("Loaded API key from database for user %s (redacted)", self._user_email)
                        return row[1]
            else:
                # Unscoped fallback — cross-tenant risk (M-v5-01)
                logger.warning(
                    "No user_email set for LLMClient — loading API key from any tenant. "
                    "Set user_email to prevent cross-tenant key leakage."
                )
                with db_cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT DISTINCT ON (key) key, value
                        FROM user_settings
                        WHERE key = ANY(%s)
                          AND value IS NOT NULL
                          AND value != ''
                        ORDER BY key, updated_at DESC
                        """,
                        (list(key_names),),
                    )
                    for _key, value in cursor.fetchall():
                        if value and len(str(value)) > 10:
                            logger.info("Loaded API key from database settings (%s)", "redacted")
                            return value
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

            r = redis_module.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)

            if getattr(self, '_user_email', None):
                # Tenant-scoped lookup (M-v5-01): exact key for this user
                key = f"settings:{self._user_email}:openrouter_api_key"
                value = r.get(key)
                if value and isinstance(value, (str, bytes)) and len(str(value)) > 10:
                    api_key = value.decode() if isinstance(value, bytes) else value
                    logger.info("Loaded API key from Redis for user %s (redacted)", self._user_email)
                    return api_key
            else:
                # Unscoped fallback — cross-tenant risk (M-v5-01)
                logger.warning(
                    "No user_email set for LLMClient — scanning all Redis keys for API key. "
                    "Set user_email to prevent cross-tenant key leakage."
                )
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor=cursor, match="settings:*:openrouter_api_key", count=20)
                    for key in keys:
                        value = r.get(key)
                        if value and isinstance(value, (str, bytes)) and len(str(value)) > 10:
                            api_key = value.decode() if isinstance(value, bytes) else value
                            logger.info("Loaded API key from Redis (key redacted)")
                            return api_key
                    if cursor == 0:
                        break

            logger.debug("No API key found in Redis settings")
            return None

        except Exception as e:
            logger.debug(f"Could not load API key from Redis: {e}")
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

    def _check_rate_limit(self):
        """Rate limiter: max 60 requests/min per provider.

        Uses Redis sorted-set sliding window for cross-worker coordination.
        Falls back to in-process rate limiter when Redis is unavailable.
        """
        now = time.time()
        window_start = now - self._rate_limit_window

        # Try Redis-based rate limiter first for cross-worker coordination
        if self._redis_url:
            try:
                import uuid

                import redis as redis_module

                r = redis_module.from_url(self._redis_url, socket_connect_timeout=1, socket_timeout=1)
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
                            logger.warning("LLM rate limit hit (cross-worker) — sleeping %.1fs", sleep_time)
                            time.sleep(sleep_time)

                # Record this request
                member = f"{uuid.uuid4()}:{now}"
                r.zadd(rate_key, {member: now})
                r.expire(rate_key, int(self._rate_limit_window) + 10)
                return
            except (ConnectionError, OSError, ValueError) as e:
                logger.debug("Redis rate limiter unavailable — falling back to in-process: %s", e)

        # Fallback: in-process rate limiter
        with self._rate_lock:
            self._request_timestamps = [t for t in self._request_timestamps if t > window_start]
            if len(self._request_timestamps) >= self._rate_limit_max:
                sleep_time = self._request_timestamps[0] + self._rate_limit_window - now
                if sleep_time > 0:
                    logger.warning("LLM rate limit hit (in-process) — sleeping %.1fs", sleep_time)
                    time.sleep(sleep_time)
            self._request_timestamps.append(now)

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
    ) -> str:
        """
        Send chat completion request (async).

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
        slog = ScanLogger("llm_client")
        slog.llm_start(self.model, messages[0]["content"][:60] if messages else "chat")
        start = time.time()

        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")

        # Circuit breaker: skip if too many recent failures
        with self._circuit_lock:
            if self._circuit_failures >= self._circuit_threshold:
                if time.time() < self._circuit_open_until:
                    raise LLMUnavailableError(
                        f"LLM circuit breaker open — skipping call for "
                        f"{self._circuit_open_until - time.time():.0f}s "
                        f"({self._circuit_failures} consecutive failures)"
                    )
                self._circuit_failures = 0

        # Rate limit: ensure we don't exceed 60 req/min per worker
        self._check_rate_limit()

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.provider == "openai" and self._get_openai_client():
                    kwargs = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format

                    import asyncio
                    response = await asyncio.wait_for(
                        self._async_openai_client.chat.completions.create(**kwargs),
                        timeout=30
                    )
                    self._circuit_failures = 0
                    duration_ms = int((time.time() - start) * 1000)
                    slog.llm_complete(self.model, duration_ms=duration_ms)
                    return response.choices[0].message.content
                else:
                    # Generic HTTP API
                    import certifi
                    import httpx
                    async with httpx.AsyncClient(timeout=30, verify=certifi.where()) as client:
                        payload = {
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

                        resp = await client.post(self.api_url, json=payload, headers=headers)
                        resp.raise_for_status()
                        data = resp.json()
                        self._circuit_failures = 0
                        duration_ms = int((time.time() - start) * 1000)
                        slog.llm_complete(self.model, duration_ms=duration_ms)

                        # Try common response formats
                        if "choices" in data and len(data["choices"]) > 0:
                            return data["choices"][0]["message"]["content"]
                        elif "content" in data:
                            return data["content"]
                        else:
                            return str(data)

            except LLMUnavailableError:
                # Don't retry — propagate immediately
                raise
            except Exception as e:
                last_error = e
                with self._circuit_lock:
                    self._circuit_failures += 1
                    if self._circuit_failures >= self._circuit_threshold:
                        self._circuit_open_until = time.time() + self._circuit_cooldown
                        logger.warning(
                            "LLM circuit breaker OPEN after %d failures — cooling down for %.0fs",
                            self._circuit_failures, self._circuit_cooldown,
                        )
                logger.warning(f"LLM chat attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    if self._circuit_open_until and time.time() < self._circuit_open_until:
                        logger.warning("Circuit breaker still open — aborting retries")
                        break
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

        raise LLMUnavailableError(f"LLM call failed after {self.max_retries + 1} retries: {last_error}")

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

        Same parameters as chat(), plus:
        timeout: Per-request timeout in seconds. Defaults to 30.

        Returns:
            LLMResponse with .text, .input_tokens, .output_tokens, .cost_usd
        """
        slog = ScanLogger("llm_client")
        action_desc = messages[0].get("content", "")[:60] if messages else "chat_sync"
        slog.llm_start(self.model, action_desc)
        start = time.time()

        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")

        # Circuit breaker: skip if too many recent failures
        with self._circuit_lock:
            if self._circuit_failures >= self._circuit_threshold:
                if time.time() < self._circuit_open_until:
                    raise LLMUnavailableError(
                        f"LLM circuit breaker open — skipping call for "
                        f"{self._circuit_open_until - time.time():.0f}s "
                        f"({self._circuit_failures} consecutive failures)"
                    )
                self._circuit_failures = 0

        # Rate limit: ensure we don't exceed 60 req/min per worker
        self._check_rate_limit()

        req_timeout = timeout or 30
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.provider == "openai" and self._get_openai_client():
                    kwargs = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "timeout": req_timeout,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format

                    response = self._openai_client.chat.completions.create(**kwargs)
                    self._circuit_failures = 0  # reset on success
                    usage = response.usage
                    input_tokens = usage.prompt_tokens if usage else 0
                    output_tokens = usage.completion_tokens if usage else 0
                    cost = (
                        (input_tokens / 1000 * LLM_AGENT_COST_PER_1K_INPUT)
                        + (output_tokens / 1000 * LLM_AGENT_COST_PER_1K_OUTPUT)
                    )
                    duration_ms = int((time.time() - start) * 1000)
                    slog.llm_complete(self.model, duration_ms=duration_ms, tokens=input_tokens + output_tokens, cost=cost)
                    return LLMResponse(
                        text=response.choices[0].message.content,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost,
                    )
                else:
                    import certifi
                    import httpx
                    with httpx.Client(timeout=req_timeout, verify=certifi.where()) as client:
                        payload = {
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

                        resp = client.post(self.api_url, json=payload, headers=headers)
                        resp.raise_for_status()
                        data = resp.json()
                        self._circuit_failures = 0

                        input_tokens = 0
                        output_tokens = 0
                        if "usage" in data:
                            input_tokens = data["usage"].get("prompt_tokens", 0)
                            output_tokens = data["usage"].get("completion_tokens", 0)
                        cost = (
                            (input_tokens / 1000 * LLM_AGENT_COST_PER_1K_INPUT)
                            + (output_tokens / 1000 * LLM_AGENT_COST_PER_1K_OUTPUT)
                        )
                        duration_ms = int((time.time() - start) * 1000)
                        slog.llm_complete(self.model, duration_ms=duration_ms, tokens=input_tokens + output_tokens, cost=cost)

                        if "choices" in data and len(data["choices"]) > 0:
                            text = data["choices"][0]["message"]["content"]
                        elif "content" in data:
                            text = data["content"]
                        else:
                            text = str(data)

                        return LLMResponse(
                            text=text,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cost_usd=cost,
                        )

            except LLMUnavailableError:
                # Don't retry — propagate immediately
                raise
            except Exception as e:
                last_error = e
                with self._circuit_lock:
                    self._circuit_failures += 1
                    if self._circuit_failures >= self._circuit_threshold:
                        self._circuit_open_until = time.time() + self._circuit_cooldown
                        logger.warning(
                            "LLM circuit breaker OPEN after %d failures — cooling down for %.0fs",
                            self._circuit_failures, self._circuit_cooldown,
                        )
                logger.warning(f"LLM chat_sync attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    if self._circuit_open_until and time.time() < self._circuit_open_until:
                        logger.warning("Circuit breaker still open — aborting retries")
                        break
                    time.sleep(2 ** attempt)

        raise LLMUnavailableError(f"LLM call failed after {self.max_retries + 1} retries: {last_error}")

    def is_available(self) -> bool:
        """Check if the LLM client is configured and potentially reachable."""
        return bool(self.api_key)


class LLMUnavailableError(Exception):
    """Raised when LLM is not configured or all retries fail."""
    pass


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
                    logger.debug("Loaded LLM setting '%s' for user '%s' from Redis", key, user_email)
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

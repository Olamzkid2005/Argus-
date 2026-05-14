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
import time
from dataclasses import dataclass

from config.constants import LLM_AGENT_COST_PER_1K_INPUT, LLM_AGENT_COST_PER_1K_OUTPUT

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
    ):
        """
        Initialize LLM client.

        API key resolution order:
        1. Explicit api_key parameter
        2. OPENAI_API_KEY environment variable
        3. LLM_API_KEY environment variable
        4. Redis key settings:*:openrouter_api_key (from UI Settings page)

        Args:
            provider: "openai" or "generic". Auto-detects from env if None.
            model: Model name. Defaults to env LLM_MODEL or "gpt-4o-mini".
            api_key: API key. Pass explicitly to override env/Redis.
            api_url: Base URL for generic provider. Defaults to env LLM_API_URL.
            max_retries: Max retry attempts on failure (default 2).
            redis_url: Redis URL for loading key from UI Settings (defaults to REDIS_URL env).
        """
        self.provider = provider or os.getenv("LLM_PROVIDER", "openai")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.max_retries = max_retries

        # Resolve API key: explicit > env var > Redis (UI Settings)
        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
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
        self._rate_limit_max = 60
        self._rate_limit_window = 60.0
        self._request_timestamps: list[float] = []

        # Circuit breaker: after N consecutive failures, skip calls for cooldown
        self._circuit_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_threshold = 3
        self._circuit_cooldown = 60.0

    def _load_key_from_redis(self, redis_url: str | None = None) -> str | None:
        """
        Load API key from Redis, where the UI Settings page stores it.

        Looks up keys matching settings:*:openrouter_api_key pattern.
        This allows users to configure the API key once via the UI
        and have it picked up by the worker processes automatically.

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

            # Scan for any settings key matching the pattern
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor=cursor, match="settings:*:openrouter_api_key", count=20)
                for key in keys:
                    value = r.get(key)
                    if value and isinstance(value, (str, bytes)) and len(str(value)) > 10:
                        api_key = value.decode() if isinstance(value, bytes) else value
                        logger.info(f"Loaded API key from Redis (key: {key.decode() if isinstance(key, bytes) else key})")
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
        """Simple in-process rate limiter: max 60 requests/min."""
        now = time.time()
        window_start = now - self._rate_limit_window
        # Remove timestamps outside the current window
        self._request_timestamps = [t for t in self._request_timestamps if t > window_start]
        if len(self._request_timestamps) >= self._rate_limit_max:
            sleep_time = self._request_timestamps[0] + self._rate_limit_window - now
            if sleep_time > 0:
                logger.warning("LLM rate limit hit — sleeping %.1fs", sleep_time)
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
        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")

        # Circuit breaker: skip if too many recent failures
        import time as _time
        if self._circuit_failures >= self._circuit_threshold:
            if _time.time() < self._circuit_open_until:
                raise LLMUnavailableError(
                    f"LLM circuit breaker open — skipping call for "
                    f"{self._circuit_open_until - _time.time():.0f}s "
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

                        # Try common response formats
                        if "choices" in data and len(data["choices"]) > 0:
                            return data["choices"][0]["message"]["content"]
                        elif "content" in data:
                            return data["content"]
                        else:
                            return str(data)

            except Exception as e:
                last_error = e
                self._circuit_failures += 1
                if self._circuit_failures >= self._circuit_threshold:
                    self._circuit_open_until = _time.time() + self._circuit_cooldown
                    logger.warning(
                        "LLM circuit breaker OPEN after %d failures — cooling down for %.0fs",
                        self._circuit_failures, self._circuit_cooldown,
                    )
                logger.warning(f"LLM chat attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

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
        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")

        # Circuit breaker: skip if too many recent failures
        import time as _time
        if self._circuit_failures >= self._circuit_threshold:
            if _time.time() < self._circuit_open_until:
                raise LLMUnavailableError(
                    f"LLM circuit breaker open — skipping call for "
                    f"{self._circuit_open_until - _time.time():.0f}s "
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

            except Exception as e:
                last_error = e
                self._circuit_failures += 1
                if self._circuit_failures >= self._circuit_threshold:
                    self._circuit_open_until = _time.time() + self._circuit_cooldown
                    logger.warning(
                        "LLM circuit breaker OPEN after %d failures — cooling down for %.0fs",
                        self._circuit_failures, self._circuit_cooldown,
                    )
                logger.warning(f"LLM chat_sync attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    _time.sleep(2 ** attempt)

        raise LLMUnavailableError(f"LLM call failed after {self.max_retries + 1} retries: {last_error}")

    def is_available(self) -> bool:
        """Check if the LLM client is configured and potentially reachable."""
        return bool(self.api_key)


class LLMUnavailableError(Exception):
    """Raised when LLM is not configured or all retries fail."""
    pass


def load_llm_setting(key: str, default: str = "") -> str:
    """
    Load an LLM feature setting from Redis.

    Scans Redis keys matching settings:*:{key} to find the setting value.
    These are set by the UI Settings page when users configure LLM features.

    This allows users to toggle LLM features (review, payload generation)
    from the UI without restarting worker processes.

    Args:
        key: Setting key name (e.g., "llm_review_enabled", "llm_payload_generation_enabled")
        default: Default value if not found in Redis

    Returns:
        Setting value string, or default if not found
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return default

    try:
        import redis as redis_module

        r = redis_module.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)

        # Scan for any user's setting
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=f"settings:*:{key}", count=20)
            for redis_key in keys:
                value = r.get(redis_key)
                if value is not None:
                    val = value.decode() if isinstance(value, bytes) else value
                    if val:
                        logger.debug(f"Loaded LLM setting '{key}' from Redis")
                        return val
            if cursor == 0:
                break

        return default

    except Exception as e:
        logger.debug(f"Could not load LLM setting '{key}' from Redis: {e}")
        return default

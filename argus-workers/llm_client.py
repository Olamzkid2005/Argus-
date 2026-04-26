"""
LLM Client - Unified wrapper for OpenAI SDK and generic HTTP API.
Supports both async and sync calls with retry logic.

API key resolution order (first found wins):
1. Explicit api_key parameter passed to constructor
2. OPENAI_API_KEY environment variable
3. LLM_API_KEY environment variable
4. Redis key settings:*:openrouter_api_key (configured via UI Settings page)
"""
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM client supporting OpenAI SDK and generic HTTP API.
    
    Automatically detects provider from environment. Provides both
    async and sync methods. Implements retry with exponential backoff.
    Graceful degradation: is_available() returns False if not configured.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        max_retries: int = 2,
        redis_url: Optional[str] = None,
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
        self.api_url = api_url or os.getenv("LLM_API_URL", 
            "https://api.openai.com/v1/chat/completions" if self.provider == "openai" else ""
        )
        
        # OpenAI SDK client (lazy init)
        self._openai_client = None
    
    def _load_key_from_redis(self, redis_url: Optional[str] = None) -> Optional[str]:
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
    
    def _build_messages(self, system_prompt: str, user_prompt: str) -> List[Dict]:
        """Build messages list for chat completion."""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def chat(
        self,
        messages: List[Dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None,
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
                    return response.choices[0].message.content
                else:
                    # Generic HTTP API
                    import httpx
                    async with httpx.AsyncClient(timeout=30) as client:
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
                        
                        # Try common response formats
                        if "choices" in data and len(data["choices"]) > 0:
                            return data["choices"][0]["message"]["content"]
                        elif "content" in data:
                            return data["content"]
                        else:
                            return str(data)
            
            except Exception as e:
                last_error = e
                logger.warning(f"LLM chat attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        raise LLMUnavailableError(f"LLM call failed after {self.max_retries + 1} retries: {last_error}")

    def chat_sync(
        self,
        messages: List[Dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None,
    ) -> str:
        """
        Send chat completion request (synchronous).
        Used by scan-phase code that can't use async.
        
        Same parameters as chat().
        """
        if not self.is_available():
            raise LLMUnavailableError("LLM client not configured (no API key)")
        
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
                    
                    response = self._openai_client.chat.completions.create(**kwargs)
                    return response.choices[0].message.content
                else:
                    import httpx
                    with httpx.Client(timeout=30) as client:
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
                        
                        if "choices" in data and len(data["choices"]) > 0:
                            return data["choices"][0]["message"]["content"]
                        elif "content" in data:
                            return data["content"]
                        else:
                            return str(data)
            
            except Exception as e:
                last_error = e
                logger.warning(f"LLM chat_sync attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)
        
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

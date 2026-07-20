"""
CveEpssCache — Redis-backed cache for CVE/EPSS threat intelligence data.

Provides cross-worker sharing of NVD and EPSS API responses so that:
  - One worker's NVD/EPSS lookup is immediately available to all other workers
  - Long TTLs (no expiry for NVD data, 24h for EPSS) prevent redundant API calls
  - NVD rate limits (5 req / 30 s without API key) are respected
  - Graceful degradation to an in-memory dict when Redis is unavailable

Usage:
    cache = CveEpssCache()
    nvd_data = cache.get_nvd_data(cve_ids=["CVE-2024-1234"])
    epss_scores = cache.get_epss_scores(cve_ids=["CVE-2024-1234"])
    cache.set_nvd_data({"CVE-2024-1234": {...}})
    cache.set_epss_scores({"CVE-2024-1234": 0.95})
"""

import json
import logging
import os
import threading
import time as _time

logger = logging.getLogger(__name__)

# ── Redis configuration ──

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_DB_NVD = int(os.getenv("CVE_CACHE_REDIS_DB", "3"))  # Dedicated DB for isolation
CACHE_DB_EPSS = int(os.getenv("EPSS_CACHE_REDIS_DB", "4"))
CVE_REDIS_URL = os.getenv("CVE_CACHE_REDIS_URL", f"{_REDIS_URL}/{CACHE_DB_NVD}")
EPSS_REDIS_URL = os.getenv("EPSS_CACHE_REDIS_URL", f"{_REDIS_URL}/{CACHE_DB_EPSS}")

# ── Key namespace ──

NVD_KEY_PREFIX = "threat_intel:nvd:{cve_ids}"
EPSS_KEY_PREFIX = "threat_intel:epss:{cve_ids}"

# ── TTL constants ──

# CVE descriptions from NVD are immutable — once published they never change.
# Cache them with no expiry (sentinel value <= 0).
NVD_CACHE_TTL = -1  # No expiry

# EPSS scores are updated daily by FIRST.org.
# 24-hour TTL is safe; the dataset changes slowly (~1% of CVEs shift score per day).
EPSS_CACHE_TTL = 86400  # 24 hours

# In-memory fallback max size to prevent unbounded growth
_IN_MEMORY_MAX_SIZE = 5000


def _normalize_cve_ids(cve_ids: list[str]) -> str:
    """Sort and deduplicate CVE IDs to produce a stable cache key."""
    return ",".join(sorted(set(cve_ids)))


class CveEpssCache:
    """Redis-backed cache for CVE/EPSS threat intelligence data.

    Provides two cache namespaces:
      - nvd:  NVD CVE details (no expiry)
      - epss: EPSS exploit-probability scores (24-hour TTL)

    Falls back to an in-memory dict when Redis is unavailable.
    """

    def __init__(self) -> None:
        self._nvd_client = _LazyRedisClient(CACHE_DB_NVD)
        self._epss_client = _LazyRedisClient(CACHE_DB_EPSS)
        # In-memory fallback caches: {key: (expiry, value)}
        self._nvd_memory: dict[str, tuple[float, dict]] = {}
        self._epss_memory: dict[str, tuple[float, dict]] = {}
        self._mem_lock = threading.Lock()

    # ── NVD CVE details ──

    def get_nvd_data(self, cve_ids: list[str]) -> dict | None:
        """Fetch cached NVD data for the given CVE IDs.

        Args:
            cve_ids: List of CVE IDs (e.g. ["CVE-2024-1234", "CVE-2024-5678"]).

        Returns:
            Cached dict mapping CVE ID → details, or None if not cached.
        """
        if not cve_ids:
            return None
        key = _normalize_cve_ids(cve_ids)
        redis_key = NVD_KEY_PREFIX.format(cve_ids=key)

        # Redis — primary cache
        result = self._nvd_client.get(redis_key)
        if result is not None:
            return result

        # In-memory — fallback
        with self._mem_lock:
            entry = self._nvd_memory.get(key)
            if entry is not None:
                expiry, value = entry
                if _time.time() < expiry:
                    return value
                del self._nvd_memory[key]
        return None

    def set_nvd_data(self, cve_ids: list[str], data: dict) -> None:
        """Cache NVD data for the given CVE IDs.

        Args:
            cve_ids: List of CVE IDs.
            data: Dict mapping CVE ID → details.
        """
        if not cve_ids or not data:
            return
        key = _normalize_cve_ids(cve_ids)
        redis_key = NVD_KEY_PREFIX.format(cve_ids=key)

        # Redis — primary cache (no expiry for immutable NVD data)
        self._nvd_client.set(redis_key, data, ttl=NVD_CACHE_TTL)

        # In-memory — fallback (no expiry for NVD)
        with self._mem_lock:
            self._nvd_memory[key] = (float("inf"), data)
            self._evict_if_needed(self._nvd_memory)

    # ── EPSS scores ──

    def get_epss_scores(self, cve_ids: list[str]) -> dict | None:
        """Fetch cached EPSS scores for the given CVE IDs.

        Args:
            cve_ids: List of CVE IDs.

        Returns:
            Cached dict mapping CVE ID → EPSS score (0.0-1.0), or None.
        """
        if not cve_ids:
            return None
        key = _normalize_cve_ids(cve_ids)
        redis_key = EPSS_KEY_PREFIX.format(cve_ids=key)

        # Redis — primary cache
        result = self._epss_client.get(redis_key)
        if result is not None:
            return result

        # In-memory — fallback
        with self._mem_lock:
            entry = self._epss_memory.get(key)
            if entry is not None:
                expiry, value = entry
                if _time.time() < expiry:
                    return value
                del self._epss_memory[key]
        return None

    def set_epss_scores(self, cve_ids: list[str], scores: dict) -> None:
        """Cache EPSS scores for the given CVE IDs.

        Args:
            cve_ids: List of CVE IDs.
            scores: Dict mapping CVE ID → EPSS score.
        """
        if not cve_ids or not scores:
            return
        key = _normalize_cve_ids(cve_ids)
        redis_key = EPSS_KEY_PREFIX.format(cve_ids=key)

        # Redis — primary cache (24-hour TTL)
        self._epss_client.set(redis_key, scores, ttl=EPSS_CACHE_TTL)

        # In-memory — fallback
        with self._mem_lock:
            self._epss_memory[key] = (_time.time() + EPSS_CACHE_TTL, scores)
            self._evict_if_needed(self._epss_memory)

    # ── Utility ──

    @property
    def is_available(self) -> bool:
        """Check if Redis is reachable for at least one cache namespace."""
        return self._nvd_client.is_available or self._epss_client.is_available

    def _evict_if_needed(self, cache: dict) -> None:
        """Evict oldest entry when cache exceeds max size."""
        if len(cache) > _IN_MEMORY_MAX_SIZE:
            # Remove expired entries first
            now = _time.time()
            expired = [k for k, (exp, _) in cache.items() if now >= exp]
            for k in expired:
                del cache[k]
            # If still over limit, remove oldest (dict preserves insertion order)
            while len(cache) > _IN_MEMORY_MAX_SIZE:
                cache.pop(next(iter(cache)))


class _LazyRedisClient:
    """Lazy-init Redis client with auto-reconnect and graceful degradation."""

    def __init__(self, db: int) -> None:
        self._db = db
        self._client = None
        self._available = False
        self._lock = threading.Lock()

    def _get_redis_url(self) -> str:
        return f"{_REDIS_URL}/{self._db}"

    def _ensure_client(self):
        with self._lock:
            if self._client is not None:
                try:
                    self._client.ping()
                    return self._client
                except Exception:
                    logger.warning("CVE cache Redis connection lost — reconnecting")
                    self._client = None
                    self._available = False

            try:
                import redis as redis_module

                self._client = redis_module.from_url(
                    self._get_redis_url(),
                    socket_connect_timeout=3,
                    socket_timeout=3,
                    decode_responses=True,
                )
                self._client.ping()
                self._available = True
                return self._client
            except Exception as e:
                if self._available:
                    logger.warning("CVE cache Redis unavailable: %s", e)
                self._available = False
                return None

    @property
    def is_available(self) -> bool:
        return self._ensure_client() is not None

    def get(self, key: str) -> dict | None:
        client = self._ensure_client()
        if not client:
            return None
        try:
            raw = client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.debug("CVE cache get error: %s", e)
            return None

    def set(self, key: str, value: dict, ttl: int = -1) -> bool:
        client = self._ensure_client()
        if not client:
            return False
        try:
            serialized = json.dumps(value, default=str)
            if ttl <= 0:
                client.set(key, serialized)
            else:
                # Use set() with ex=ttl instead of setex() — redis 5+ deprecates setex
                client.set(key, serialized, ex=ttl)
            return True
        except Exception as e:
            logger.debug("CVE cache set error: %s", e)
            return False

    def delete(self, key: str) -> bool:
        client = self._ensure_client()
        if not client:
            return False
        try:
            client.delete(key)
            return True
        except Exception as e:
            logger.debug("CVE cache delete error: %s", e)
            return False


# ── Module-level convenience instance ──

_cve_cache: CveEpssCache | None = None
_cve_cache_lock = threading.Lock()


def get_cve_cache() -> CveEpssCache:
    """Get or create the global CveEpssCache singleton."""
    global _cve_cache
    if _cve_cache is None:
        with _cve_cache_lock:
            if _cve_cache is None:
                _cve_cache = CveEpssCache()
    return _cve_cache


def get_nvd_data(cve_ids: list[str]) -> dict | None:
    """Convenience: fetch cached NVD data."""
    return get_cve_cache().get_nvd_data(cve_ids)


def set_nvd_data(cve_ids: list[str], data: dict) -> None:
    """Convenience: cache NVD data."""
    get_cve_cache().set_nvd_data(cve_ids, data)


def get_epss_scores(cve_ids: list[str]) -> dict | None:
    """Convenience: fetch cached EPSS scores."""
    return get_cve_cache().get_epss_scores(cve_ids)


def set_epss_scores(cve_ids: list[str], scores: dict) -> None:
    """Convenience: cache EPSS scores."""
    get_cve_cache().set_epss_scores(cve_ids, scores)

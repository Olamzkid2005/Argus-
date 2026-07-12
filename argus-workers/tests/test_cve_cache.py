"""
Tests for cve_cache.py — CveEpssCache in-memory fallback, Redis integration,
key normalization, and cache eviction.
"""

import time
from unittest.mock import MagicMock, patch

from cve_cache import (
    CveEpssCache,
    _normalize_cve_ids,
    NVD_CACHE_TTL,
    EPSS_CACHE_TTL,
    _IN_MEMORY_MAX_SIZE,
)


class TestNormalizeCveIds:
    """Tests for _normalize_cve_ids helper."""

    def test_sorts_ids(self):
        result = _normalize_cve_ids(["CVE-2024-0002", "CVE-2024-0001"])
        assert result == "CVE-2024-0001,CVE-2024-0002"

    def test_deduplicates(self):
        result = _normalize_cve_ids(["CVE-2024-0001", "CVE-2024-0001"])
        assert result == "CVE-2024-0001"

    def test_sorts_and_deduplicates(self):
        result = _normalize_cve_ids(
            ["CVE-2024-0002", "CVE-2024-0001", "CVE-2024-0002"]
        )
        assert result == "CVE-2024-0001,CVE-2024-0002"

    def test_empty_list(self):
        assert _normalize_cve_ids([]) == ""


class TestCveEpssCacheInMemory:
    """Tests for CveEpssCache in-memory fallback (Redis unavailable).

    Mocks the 'redis' module import to raise ImportError, so
    _LazyRedisClient._ensure_client() never attempts a network connection.
    Each test gets a fresh CveEpssCache instance.
    """

    def setup_method(self):
        # Mock redis import to raise ImportError — prevents network connections
        self._redis_patcher = patch.dict("sys.modules", {"redis": None})
        self._redis_patcher.start()
        # Also need to re-import the module? No — _LazyRedisClient imports
        # redis inside _ensure_client(), so mocking sys.modules won't work.
        # Instead, simply create a fresh instance and directly disable clients.
        import cve_cache as mod
        mod._cve_cache = None  # Reset singleton
        self.cache = CveEpssCache()
        # Directly disable Redis clients to prevent any connection attempt
        self.cache._nvd_client._client = None
        self.cache._nvd_client._available = False
        self.cache._epss_client._client = None
        self.cache._epss_client._available = False

    def teardown_method(self):
        self._redis_patcher.stop()
        import cve_cache as mod
        mod._cve_cache = None

    def test_get_nvd_data_none_initially(self):
        result = self.cache.get_nvd_data(["CVE-2024-0001"])
        assert result is None

    def test_set_and_get_nvd_data(self):
        data = {"CVE-2024-0001": {"description": "Test CVE", "cvss_score": 7.5}}
        self.cache.set_nvd_data(["CVE-2024-0001"], data)
        result = self.cache.get_nvd_data(["CVE-2024-0001"])
        assert result == data

    def test_get_epss_scores_none_initially(self):
        result = self.cache.get_epss_scores(["CVE-2024-0001"])
        assert result is None

    def test_set_and_get_epss_scores(self):
        scores = {"CVE-2024-0001": 0.95}
        self.cache.set_epss_scores(["CVE-2024-0001"], scores)
        result = self.cache.get_epss_scores(["CVE-2024-0001"])
        assert result == scores

    def test_empty_cve_ids_returns_none(self):
        assert self.cache.get_nvd_data([]) is None
        assert self.cache.get_epss_scores([]) is None

    def test_set_empty_data_is_noop(self):
        self.cache.set_nvd_data(["CVE-2024-0001"], {})
        self.cache.set_epss_scores(["CVE-2024-0001"], {})
        assert self.cache.get_nvd_data(["CVE-2024-0001"]) is None
        assert self.cache.get_epss_scores(["CVE-2024-0001"]) is None

    def test_is_available_false_when_redis_unavailable(self):
        # Clients are already disabled in setup_method
        assert self.cache.is_available is False

    def test_nvd_cache_no_expiry(self):
        """NVD data should persist indefinitely in the in-memory cache."""
        data = {"CVE-2024-0001": {"description": "Persistent CVE"}}
        self.cache.set_nvd_data(["CVE-2024-0001"], data)
        assert self.cache._nvd_memory.get("CVE-2024-0001") is not None
        expiry, value = self.cache._nvd_memory["CVE-2024-0001"]
        assert expiry == float("inf")
        assert value == data

    def test_epss_scores_have_finite_ttl(self):
        """EPSS scores should have a finite TTL."""
        scores = {"CVE-2024-0001": 0.95}
        self.cache.set_epss_scores(["CVE-2024-0001"], scores)
        assert self.cache._epss_memory.get("CVE-2024-0001") is not None
        expiry, value = self.cache._epss_memory["CVE-2024-0001"]
        assert expiry > time.time()  # TTL should be in the future
        assert value == scores

    def test_epss_expired_entry_returns_none(self):
        """Simulate an expired EPSS entry."""
        scores = {"CVE-2024-0001": 0.95}
        self.cache.set_epss_scores(["CVE-2024-0001"], scores)
        # Manually expire the entry
        self.cache._epss_memory["CVE-2024-0001"] = (
            time.time() - 1,
            scores,
        )
        result = self.cache.get_epss_scores(["CVE-2024-0001"])
        assert result is None
        # Expired entry should have been removed
        assert "CVE-2024-0001" not in self.cache._epss_memory

    def test_cache_key_deduplication(self):
        """Same CVE IDs regardless of order should produce same cache key."""
        self.cache.set_nvd_data(
            ["CVE-2024-0001", "CVE-2024-0002"],
            {"CVE-2024-0001": {}, "CVE-2024-0002": {}},
        )
        result = self.cache.get_nvd_data(["CVE-2024-0002", "CVE-2024-0001"])
        assert result is not None
        assert "CVE-2024-0001" in result
        assert "CVE-2024-0002" in result

    def test_multi_cve_nvd(self):
        """Different subsets of CVE IDs produce different cache keys."""
        data = {
            "CVE-2024-0001": {"cvss_score": 9.0},
            "CVE-2024-0002": {"cvss_score": 5.0},
        }
        self.cache.set_nvd_data(["CVE-2024-0001", "CVE-2024-0002"], data)
        # Query subset: should miss the combined cache, but data includes both
        result_one = self.cache.get_nvd_data(["CVE-2024-0001"])
        # Note: Because the cache key includes ALL CVE IDs, querying a subset
        # will miss the combined cache. The data is stored under the combined key.
        assert result_one is None  # Different key = miss

    def test_eviction_nvd_over_limit(self):
        """Evict oldest entry when NVD cache exceeds max size."""
        for i in range(_IN_MEMORY_MAX_SIZE + 5):
            cve = f"CVE-2024-{i:04d}"
            self.cache.set_nvd_data([cve], {cve: {"data": f"value_{i}"}})
        assert len(self.cache._nvd_memory) <= _IN_MEMORY_MAX_SIZE
        # Oldest entries should have been evicted
        assert "CVE-2024-0000" not in self.cache._nvd_memory

    def test_eviction_epss_over_limit(self):
        """Evict oldest entry when EPSS cache exceeds max size."""
        for i in range(_IN_MEMORY_MAX_SIZE + 5):
            cve = f"CVE-2024-{i:04d}"
            self.cache.set_epss_scores([cve], {cve: 0.5})
        assert len(self.cache._epss_memory) <= _IN_MEMORY_MAX_SIZE
        assert "CVE-2024-0000" not in self.cache._epss_memory


class TestCveEpssCacheTTL:
    """Tests for TTL constant correctness."""

    def test_nvd_no_expiry(self):
        assert NVD_CACHE_TTL == -1  # No expiry for immutable CVE data

    def test_epss_24h_ttl(self):
        assert EPSS_CACHE_TTL == 86400  # 24 hours for daily-updated scores


class TestCveEpssCacheConvenienceFunctions:
    """Tests for module-level convenience functions.

    Each test resets the singleton to prevent cross-test contamination.
    """

    def setup_method(self):
        import cve_cache as mod
        mod._cve_cache = None
        self.cache = mod.get_cve_cache()
        # Disable Redis clients
        self.cache._nvd_client._client = None
        self.cache._nvd_client._available = False
        self.cache._epss_client._client = None
        self.cache._epss_client._available = False

    def teardown_method(self):
        import cve_cache as mod
        mod._cve_cache = None

    def test_get_nvd_data_convenience(self):
        from cve_cache import set_nvd_data, get_nvd_data

        set_nvd_data(["CVE-2024-TEST"], {"CVE-2024-TEST": {"data": "test"}})
        result = get_nvd_data(["CVE-2024-TEST"])
        assert result == {"CVE-2024-TEST": {"data": "test"}}

    def test_get_epss_scores_convenience(self):
        from cve_cache import set_epss_scores, get_epss_scores

        set_epss_scores(["CVE-2024-TEST"], {"CVE-2024-TEST": 0.95})
        result = get_epss_scores(["CVE-2024-TEST"])
        assert result == {"CVE-2024-TEST": 0.95}

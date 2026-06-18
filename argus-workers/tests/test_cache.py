"""
Tests for cache.py — CacheMode, CachePolicy, TTL sentinel, and metrics.
"""

import json
from unittest.mock import MagicMock, patch

from cache import CacheMode, CachePolicy, WorkerCache


class TestCacheMode:
    """Tests for CacheMode enum."""

    def test_normal_mode(self):
        assert CacheMode.NORMAL.value == "normal"

    def test_no_cache_mode(self):
        assert CacheMode.NO_CACHE.value == "no_cache"

    def test_refresh_mode(self):
        assert CacheMode.REFRESH.value == "refresh"

    def test_all_modes_distinct(self):
        modes = {m.value for m in CacheMode}
        assert len(modes) == 3


class TestCachePolicy:
    """Tests for CachePolicy TTL constants."""

    def test_tool_query_ttl(self):
        assert CachePolicy.TOOL_QUERY == 300  # 5 min

    def test_tool_detail_ttl(self):
        assert CachePolicy.TOOL_DETAIL == 86400 * 7  # 7 days

    def test_advisory_query_ttl(self):
        assert CachePolicy.ADVISORY_QUERY == 1800  # 30 min

    def test_advisory_detail_no_expiry(self):
        assert CachePolicy.ADVISORY_DETAIL == -1  # No expiry sentinel

    def test_engagement_state_ttl(self):
        assert CachePolicy.ENGAGEMENT_STATE == 300  # 5 min


class TestWorkerCacheTTLSentinel:
    """Tests for -1 TTL sentinel (no-expiry)."""

    @patch("cache._get_redis")
    def test_set_with_no_expiry_uses_set_not_setex(self, mock_get_redis):
        """TTL <= 0 uses Redis SET (no TTL) instead of SETEX."""
        mock_client = MagicMock()
        mock_get_redis.return_value = mock_client
        wc = WorkerCache(ttl=300)

        result = wc.set("test_key", {"data": "persistent"}, ttl=-1)

        assert result is True
        # Should call set() not setex()
        mock_client.set.assert_called_once()
        mock_client.setex.assert_not_called()

    @patch("cache._get_redis")
    def test_set_with_positive_ttl_uses_setex(self, mock_get_redis):
        """Positive TTL uses Redis SETEX."""
        mock_client = MagicMock()
        mock_get_redis.return_value = mock_client
        wc = WorkerCache(ttl=300)

        result = wc.set("test_key", {"data": "ephemeral"}, ttl=300)

        assert result is True
        mock_client.setex.assert_called_once()
        mock_client.set.assert_not_called()


class TestWorkerCacheMetrics:
    """Tests for cache observability counters."""

    def test_initial_metrics_zero(self):
        wc = WorkerCache(ttl=300)
        metrics = wc.get_metrics()
        assert metrics["hit_count"] == 0
        assert metrics["miss_count"] == 0
        assert metrics["bypass_count"] == 0
        assert metrics["refresh_count"] == 0
        assert metrics["hit_rate"] == 0.0

    @patch("cache._get_redis")
    def test_get_tracks_hits(self, mock_get_redis):
        mock_client = MagicMock()
        mock_client.get.return_value = json.dumps({"data": "cached"})
        mock_get_redis.return_value = mock_client
        wc = WorkerCache(ttl=300)

        result = wc.get("existing_key")
        assert result == {"data": "cached"}
        metrics = wc.get_metrics()
        assert metrics["hit_count"] == 1
        assert metrics["miss_count"] == 0

    @patch("cache._get_redis")
    def test_get_tracks_misses(self, mock_get_redis):
        mock_client = MagicMock()
        mock_client.get.return_value = None
        mock_get_redis.return_value = mock_client
        wc = WorkerCache(ttl=300)

        result = wc.get("missing_key")
        assert result is None
        metrics = wc.get_metrics()
        assert metrics["hit_count"] == 0
        assert metrics["miss_count"] == 1

    def test_record_bypass(self):
        wc = WorkerCache(ttl=300)
        wc.record_bypass()
        wc.record_bypass()
        metrics = wc.get_metrics()
        assert metrics["bypass_count"] == 2

    def test_record_refresh(self):
        wc = WorkerCache(ttl=300)
        wc.record_refresh()
        metrics = wc.get_metrics()
        assert metrics["refresh_count"] == 1

    @patch("cache._get_redis")
    def test_get_stats_includes_metrics(self, mock_get_redis):
        mock_client = MagicMock()
        mock_client.info.return_value = {"db1": {"keys": 10, "expires": 5}}
        mock_get_redis.return_value = mock_client
        # Override CACHE_DB to match mock
        import cache as cache_module

        cache_module.CACHE_DB = 1
        wc = WorkerCache(ttl=300)

        wc.record_bypass()
        stats = wc.get_stats()

        assert stats["status"] == "available"
        assert stats["bypass_count"] == 1
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "refresh_count" in stats

    @patch("cache._get_redis")
    def test_get_stats_unavailable(self, mock_get_redis):
        """When Redis is unavailable, metrics are still returned."""
        mock_get_redis.return_value = None
        wc = WorkerCache(ttl=300)

        wc.record_bypass()
        wc.record_refresh()
        stats = wc.get_stats()

        assert stats["status"] == "unavailable"
        assert stats["bypass_count"] == 1
        assert stats["refresh_count"] == 1

    @patch("cache._get_redis")
    def test_hit_rate_calculation(self, mock_get_redis):
        mock_client = MagicMock()
        mock_get_redis.return_value = mock_client

        # 3 hits, 1 miss = 75% hit rate
        def mock_get(key):
            return json.dumps({"data": "val"})

        mock_client.get.side_effect = [
            mock_get("k"),
            mock_get("k"),
            mock_get("k"),
            None,
        ]
        wc = WorkerCache(ttl=300)

        wc.get("a")
        wc.get("b")
        wc.get("c")
        wc.get("d")  # miss

        metrics = wc.get_metrics()
        assert metrics["hit_count"] == 3
        assert metrics["miss_count"] == 1
        assert metrics["hit_rate"] == 0.75

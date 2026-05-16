"""
Tests for cache.py (enhanced cache features)
"""
import hashlib
import json
from unittest.mock import patch

import pytest

from cache import WorkerCache, cache, cached, cached_query


class TestWorkerCache:
    """Test suite for WorkerCache"""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client"""
        with patch("cache._redis_client_instance") as mock_client:
            with patch("cache._redis_available", True):
                yield mock_client

    def test_get_success(self, mock_redis):
        """Test getting cached value"""
        mock_redis.get.return_value = json.dumps({"data": "test"})

        result = cache.get("key-001")

        assert result == {"data": "test"}
        mock_redis.get.assert_called_once_with("cache:key-001")

    def test_get_not_found(self, mock_redis):
        """Test getting non-existent key"""
        mock_redis.get.return_value = None

        result = cache.get("key-002")

        assert result is None

    def test_get_redis_error(self, mock_redis):
        """Test get handles Redis errors"""
        mock_redis.get.side_effect = Exception("Redis error")

        result = cache.get("key-003")

        assert result is None

    def test_set_success(self, mock_redis):
        """Test setting cache value"""
        result = cache.set("key-004", {"data": "value"}, ttl=300)

        assert result is True
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[0] == "cache:key-004"
        assert args[1] == 300
        assert json.loads(args[2]) == {"data": "value"}

    def test_set_default_ttl(self, mock_redis):
        """Test set uses default TTL"""
        cache.set("key-005", "value")

        args = mock_redis.setex.call_args[0]
        assert args[1] == cache.ttl

    def test_set_redis_error(self, mock_redis):
        """Test set handles Redis errors"""
        mock_redis.setex.side_effect = Exception("Redis error")

        result = cache.set("key-006", "value")

        assert result is False

    def test_delete_success(self, mock_redis):
        """Test deleting cache key"""
        result = cache.delete("key-007")

        assert result is True
        mock_redis.delete.assert_called_once_with("cache:key-007")

    def test_delete_redis_error(self, mock_redis):
        """Test delete handles Redis errors"""
        mock_redis.delete.side_effect = Exception("Redis error")

        result = cache.delete("key-008")

        assert result is False

    def test_clear_pattern(self, mock_redis):
        """Test clearing keys by pattern"""
        mock_redis.scan.return_value = (0, [b"cache:key:1", b"cache:key:2"])
        mock_redis.delete.return_value = 2

        result = cache.clear_pattern("key:*")

        assert result == 2
        mock_redis.scan.assert_called_once_with(0, match="cache:key:*", count=100)
        mock_redis.delete.assert_called_once_with(b"cache:key:1", b"cache:key:2")

    def test_clear_pattern_no_keys(self, mock_redis):
        """Test clearing pattern with no matching keys"""
        mock_redis.scan.return_value = (0, [])

        result = cache.clear_pattern("key:*")

        assert result == 0
        mock_redis.delete.assert_not_called()

    def test_get_query_result(self, mock_redis):
        """Test getting cached query result"""
        mock_redis.get.return_value = json.dumps({"rows": [[1, 2, 3]]})

        result = cache.get_query_result("SELECT * FROM findings", params=("ENG-001",))

        assert result == {"rows": [[1, 2, 3]]}
        # Verify key generation
        expected_key_data = 'SELECT * FROM findings:["ENG-001"]'
        expected_hash = hashlib.sha256(expected_key_data.encode()).hexdigest()[:16]
        mock_redis.get.assert_called_once_with(f"cache:query:{expected_hash}")

    def test_set_query_result(self, mock_redis):
        """Test caching query result"""
        result = cache.set_query_result(
            "SELECT * FROM findings",
            params=("ENG-001",),
            result={"rows": []},
            ttl=600
        )

        assert result is True
        mock_redis.setex.assert_called_once()

    def test_invalidate_query(self, mock_redis):
        """Test invalidating queries by pattern"""
        mock_redis.scan.return_value = (0, [b"cache:query:abc123", b"cache:query:def456"])
        mock_redis.delete.return_value = 2

        result = cache.invalidate_query("findings")

        assert result == 2
        mock_redis.scan.assert_called_once_with(0, match="cache:query:*findings*", count=100)

    def test_invalidate_table(self, mock_redis):
        """Test invalidating cached queries for a table"""
        mock_redis.scan.return_value = (0, [b"cache:table:findings:suffix"])
        mock_redis.delete.return_value = 1

        result = cache.invalidate_table("findings")

        assert result == 1
        mock_redis.scan.assert_called_once_with(0, match="cache:*table:findings*", count=100)

    def test_get_stats_available(self, mock_redis):
        """Test getting cache stats when available"""
        mock_redis.info.return_value = {"db1": {"keys": 42, "expires": 30}}

        with patch("cache.CACHE_DB", 1):
            stats = cache.get_stats()

        assert stats["status"] == "available"
        assert stats["keys"] == 42
        assert stats["expires"] == 30

    def test_get_stats_error(self, mock_redis):
        """Test getting cache stats on error"""
        mock_redis.info.side_effect = Exception("Redis error")

        stats = cache.get_stats()

        assert stats["status"] == "error"
        assert "error" in stats

    def test_redis_unavailable(self):
        """Test operations when Redis is unavailable"""
        with patch("cache._redis_available", False), patch("cache._get_redis", return_value=None):
            assert cache.get("key") is None
            assert cache.set("key", "value") is False
            assert cache.delete("key") is False
            assert cache.clear_pattern("*") == 0
            assert cache.get_stats() == {"status": "unavailable"}


class TestCachedDecorator:
    """Test suite for cached decorator"""

    @pytest.fixture
    def mock_redis(self):
        with patch("cache._redis_client_instance") as mock_client:
            with patch("cache._redis_available", True):
                yield mock_client

    def test_cached_decorator_cache_hit(self, mock_redis):
        """Test cached decorator returns cached value"""
        mock_redis.get.return_value = json.dumps("cached_result")

        @cached(key_prefix="test_func")
        def expensive_function(arg1, arg2):
            return f"computed_{arg1}_{arg2}"

        result = expensive_function("a", "b")

        assert result == "cached_result"
        mock_redis.get.assert_called_once_with("cache:test_func:a:b")

    def test_cached_decorator_cache_miss(self, mock_redis):
        """Test cached decorator computes and stores on miss"""
        mock_redis.get.return_value = None

        @cached(key_prefix="test_func2", ttl=120)
        def expensive_function(arg1):
            return f"computed_{arg1}"

        result = expensive_function("x")

        assert result == "computed_x"
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[0] == "cache:test_func2:x"
        assert args[1] == 120
        assert json.loads(args[2]) == "computed_x"

    def test_cached_decorator_invalidation(self, mock_redis):
        """Test cached decorator invalidation helper"""
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])

        @cached(key_prefix="invalidate_test")
        def my_func():
            return 42

        my_func()
        my_func.cache_invalidate()

        mock_redis.scan.assert_called_once_with(0, match="cache:invalidate_test:*", count=100)


class TestCachedQueryDecorator:
    """Test suite for cached_query decorator"""

    @pytest.fixture
    def mock_redis(self):
        with patch("cache._redis_client_instance") as mock_client:
            with patch("cache._redis_available", True):
                yield mock_client

    def test_cached_query_hit(self, mock_redis):
        """Test cached_query returns cached result"""
        mock_redis.get.return_value = json.dumps([{"id": 1}])

        @cached_query(ttl=300)
        def get_findings(engagement_id):
            return [{"id": 1, "type": "XSS"}]

        result = get_findings("ENG-001")

        assert result == [{"id": 1}]
        # Verify key is based on function name and args
        expected_key_data = 'get_findings:["ENG-001"]:{}'
        expected_hash = hashlib.sha256(expected_key_data.encode()).hexdigest()[:16]
        mock_redis.get.assert_called_once_with(f"cache:query:{expected_hash}")

    def test_cached_query_miss(self, mock_redis):
        """Test cached_query computes and stores on miss"""
        mock_redis.get.return_value = None

        @cached_query(ttl=600)
        def get_findings(engagement_id, severity="HIGH"):
            return [{"id": 1}]

        result = get_findings("ENG-001", severity="CRITICAL")

        assert result == [{"id": 1}]
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[1] == 600

    def test_cached_query_invalidate(self, mock_redis):
        """Test cached_query invalidation helper"""
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])

        @cached_query(ttl=300)
        def get_findings():
            return []

        get_findings()
        get_findings.cache_invalidate()

        mock_redis.scan.assert_called_once_with(0, match="cache:query:*", count=100)


class TestCacheTTLPresets:
    """Test suite for TTL preset constants"""

    def test_ttl_constants(self):
        """Test TTL preset values"""
        assert WorkerCache.TTL_SHORT == 60
        assert WorkerCache.TTL_MEDIUM == 300
        assert WorkerCache.TTL_LONG == 3600
        assert WorkerCache.TTL_EXTENDED == 86400

    def test_default_ttl(self):
        """Test default TTL in cache instance"""
        test_cache = WorkerCache()
        assert test_cache.ttl == 300

    def test_custom_ttl(self):
        """Test custom TTL initialization"""
        test_cache = WorkerCache(ttl=600)
        assert test_cache.ttl == 600

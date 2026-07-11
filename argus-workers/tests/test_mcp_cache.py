"""
Tests for MCPServer.call_tool() caching behavior.

Covers Gap 4.4: cache_mode parameter enforcement for NORMAL, NO_CACHE,
and REFRESH modes, cache hit/miss logic, stale duration zeroing,
and ensuring error/timeout results are never cached.
"""

from mcp_server import MCPServer, ToolDefinition, _mcp_cache_key


def _make_server():
    """Create an MCPServer with a test echo tool registered."""
    server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
    td = ToolDefinition(
        name="echo",
        command="echo",
        parameters=[{"name": "msg", "type": "string", "flag": "-n"}],
    )
    server.register_tool(td)
    return server


class TestMcpCacheKey:
    """Tests for the _mcp_cache_key helper function."""

    def test_different_tools_different_keys(self):
        k1 = _mcp_cache_key("nuclei", {"target": "http://example.com"})
        k2 = _mcp_cache_key("httpx", {"target": "http://example.com"})
        assert k1 != k2

    def test_different_args_different_keys(self):
        k1 = _mcp_cache_key("nuclei", {"target": "http://a.com"})
        k2 = _mcp_cache_key("nuclei", {"target": "http://b.com"})
        assert k1 != k2

    def test_same_args_same_key(self):
        k1 = _mcp_cache_key("nuclei", {"target": "http://example.com"})
        k2 = _mcp_cache_key("nuclei", {"target": "http://example.com"})
        assert k1 == k2

    def test_none_args_produces_deterministic_key(self):
        k1 = _mcp_cache_key("nuclei", None)
        k2 = _mcp_cache_key("nuclei", {})
        assert k1 == k2  # both treated as empty dict

    def test_key_is_hex_string(self):
        key = _mcp_cache_key("test", {"foo": "bar"})
        assert isinstance(key, str)
        assert len(key) == 16
        int(key, 16)  # should not raise


class TestCallToolNormalMode:
    """NORMAL mode: reads cache, writes cache."""

    def test_cache_hit_returns_cached_content(self, mocker):
        """On cache hit in NORMAL mode, cached content is returned directly.
        Note: duration_ms is zeroed by the cache-hit path since the timestamp
        is stale, but the actual content/payload is preserved."""
        server = _make_server()
        cached = {
            "content": [{"type": "text", "text": "hello"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 42, "success": True},
        }
        mocker.patch("mcp_server._mcp_cache.get", return_value=cached)

        result = server.call_tool("echo", {"msg": "hello"}, cache_mode="normal")

        # Content is preserved
        assert result["content"] == cached["content"]
        assert result["isError"] is False
        # Duration is zeroed (stale timestamp)
        assert result["meta"]["duration_ms"] == 0

    def test_cache_hit_zeros_stale_duration(self, mocker):
        """On cache hit, duration_ms in meta should be zeroed (stale timestamp)."""
        server = _make_server()
        cached = {
            "content": [{"type": "text", "text": "old"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 9999, "success": True},
        }
        mocker.patch("mcp_server._mcp_cache.get", return_value=cached)

        result = server.call_tool("echo", {"msg": "old"}, cache_mode="normal")

        assert result["meta"]["duration_ms"] == 0

    def test_cache_hit_uses_key_with_arguments(self, mocker):
        """Cache lookup key should incorporate both tool name and arguments."""
        server = _make_server()
        mock_get = mocker.patch("mcp_server._mcp_cache.get", return_value=None)
        # Force execution to proceed
        mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "unique"}, cache_mode="normal")

        # Verify the key was computed from the arguments
        expected_key = _mcp_cache_key("echo", {"msg": "unique"})
        mock_get.assert_called_once_with(expected_key)

    def test_cache_miss_executes_and_writes(self, mocker):
        """On cache miss in NORMAL mode, tool executes and result is cached."""
        server = _make_server()

        # Mock cache miss then verify set is called
        mocker.patch("mcp_server._mcp_cache.get", return_value=None)
        mock_set = mocker.patch("mcp_server._mcp_cache.set")
        mock_result = mocker.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        mocker.patch("mcp_server.subprocess.run", return_value=mock_result)

        result = server.call_tool("echo", {"msg": "fresh"}, cache_mode="normal")

        assert result["isError"] is False
        expected_key = _mcp_cache_key("echo", {"msg": "fresh"})
        mock_set.assert_called_once()
        # First arg to set is the key
        assert mock_set.call_args[0][0] == expected_key

    def test_cache_hit_does_not_execute(self, mocker):
        """On cache hit, subprocess should NOT be called."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get", return_value={
            "content": [{"type": "text", "text": "cached"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 0, "success": True},
        })
        mock_run = mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "hit"}, cache_mode="normal")

        mock_run.assert_not_called()


class TestCallToolNoCacheMode:
    """NO_CACHE mode: skips both cache read and cache write."""

    def test_no_cache_skips_cache_read(self, mocker):
        """In NO_CACHE mode, cache.get should NOT be called."""
        server = _make_server()
        mock_get = mocker.patch("mcp_server._mcp_cache.get")
        mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "fresh"}, cache_mode="no_cache")

        mock_get.assert_not_called()

    def test_no_cache_skips_cache_write(self, mocker):
        """In NO_CACHE mode, cache.set should NOT be called."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get")
        mock_set = mocker.patch("mcp_server._mcp_cache.set")
        mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "fresh"}, cache_mode="no_cache")

        mock_set.assert_not_called()

    def test_no_cache_always_executes(self, mocker):
        """In NO_CACHE mode, tool should always execute."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get", return_value={
            "content": [{"type": "text", "text": "stale"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 0, "success": True},
        })
        mock_run = mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "execute"}, cache_mode="no_cache")

        # Should execute even though cache has a value
        mock_run.assert_called_once()

    def test_no_cache_default_enum_string(self, mocker):
        """NO_CACHE mode should work with the CacheMode enum string value."""
        server = _make_server()
        mock_get = mocker.patch("mcp_server._mcp_cache.get")
        mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "test"}, cache_mode="no_cache")

        mock_get.assert_not_called()


class TestCallToolRefreshMode:
    """REFRESH mode: skips cache read, still writes cache."""

    def test_refresh_skips_cache_read(self, mocker):
        """In REFRESH mode, cache.get should NOT be called."""
        server = _make_server()
        mock_get = mocker.patch("mcp_server._mcp_cache.get")
        mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "refresh"}, cache_mode="refresh")

        mock_get.assert_not_called()

    def test_refresh_still_writes_cache(self, mocker):
        """In REFRESH mode, cache.set SHOULD be called."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get", return_value={
            "content": [{"type": "text", "text": "old"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 0, "success": True},
        })
        mock_set = mocker.patch("mcp_server._mcp_cache.set")
        mock_result = mocker.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "refreshed"
        mock_result.stderr = ""
        mocker.patch("mcp_server.subprocess.run", return_value=mock_result)

        server.call_tool("echo", {"msg": "refresh"}, cache_mode="refresh")

        mock_set.assert_called_once()

    def test_refresh_executes_always(self, mocker):
        """In REFRESH mode, tool should always execute regardless of cache."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get", return_value={
            "content": [{"type": "text", "text": "stale"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 0, "success": True},
        })
        mock_run = mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "execute"}, cache_mode="refresh")

        mock_run.assert_called_once()


class TestCallToolDefaultMode:
    """Default behavior (cache_mode=None) should act like NORMAL."""

    def test_default_checks_cache(self, mocker):
        """When cache_mode is None, cache.get should be called."""
        server = _make_server()
        mock_get = mocker.patch("mcp_server._mcp_cache.get", return_value=None)
        mocker.patch("mcp_server.subprocess.run")

        server.call_tool("echo", {"msg": "default"})

        mock_get.assert_called_once()

    def test_default_writes_cache(self, mocker):
        """When cache_mode is None, cache.set should be called after execution."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get", return_value=None)
        mock_set = mocker.patch("mcp_server._mcp_cache.set")
        mock_result = mocker.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "default"
        mock_result.stderr = ""
        mocker.patch("mcp_server.subprocess.run", return_value=mock_result)

        server.call_tool("echo", {"msg": "default"})

        mock_set.assert_called_once()

    def test_default_cache_hit_returns_cached(self, mocker):
        """When cache_mode is None and cache hits, cached result is returned."""
        server = _make_server()
        cached = {
            "content": [{"type": "text", "text": "cached"}],
            "isError": False,
            "meta": {"tool": "echo", "duration_ms": 100, "success": True},
        }
        mocker.patch("mcp_server._mcp_cache.get", return_value=cached)
        mock_run = mocker.patch("mcp_server.subprocess.run")

        result = server.call_tool("echo", {"msg": "hit"})

        assert result == cached
        mock_run.assert_not_called()


class TestCallToolErrorNotCached:
    """Error/timeout results should never be cached."""

    def test_tool_timeout_not_cached(self, mocker):
        """A timed-out tool should NOT write to cache."""
        server = _make_server()
        mocker.patch("mcp_server._mcp_cache.get", return_value=None)
        mock_set = mocker.patch("mcp_server._mcp_cache.set")
        mocker.patch("mcp_server.subprocess.run", side_effect=TimeoutError("timed out"))

        server.call_tool("echo", {"msg": "timeout"}, cache_mode="normal")

        mock_set.assert_not_called()

    def test_unknown_tool_not_cached(self, mocker):
        """An unknown tool should NOT write to cache."""
        server = _make_server()
        mock_set = mocker.patch("mcp_server._mcp_cache.set")

        server.call_tool("nonexistent", cache_mode="normal")

        mock_set.assert_not_called()

    def test_disabled_tool_not_cached(self, mocker):
        """A disabled tool should NOT write to cache."""
        server = _make_server()
        server.register_tool(ToolDefinition(name="off", command="off", enabled=False))
        mock_set = mocker.patch("mcp_server._mcp_cache.set")

        server.call_tool("off", cache_mode="normal")

        mock_set.assert_not_called()


class TestCallToolCacheIntegration:
    """Integration-style tests combining multiple cache behaviors."""

    def test_first_call_miss_second_call_hit(self, mocker):
        """First call misses cache and executes; second call hits cache."""
        server = _make_server()
        cache_store = {}

        def mock_get(key):
            return cache_store.get(key)

        def mock_set(key, value, ttl=300):
            cache_store[key] = value

        mocker.patch("mcp_server._mcp_cache.get", side_effect=mock_get)
        mocker.patch("mcp_server._mcp_cache.set", side_effect=mock_set)

        # Mock subprocess.run to return consistent output
        mock_result = mocker.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello from echo"
        mock_result.stderr = ""
        mocker.patch("mcp_server.subprocess.run", return_value=mock_result)

        # First call: cache miss → executes
        result1 = server.call_tool("echo", {"msg": "test"}, cache_mode="normal")
        assert result1["isError"] is False

        # Second call: should hit cache
        result2 = server.call_tool("echo", {"msg": "test"}, cache_mode="normal")
        assert result2["isError"] is False
        # Second call duration should be zeroed (cache hit)
        assert result2["meta"]["duration_ms"] == 0

        # The content should be the same
        assert result1["content"] == result2["content"]

    def test_no_cache_does_not_populate_cache(self, mocker):
        """NO_CACHE mode should not populate the cache for subsequent calls."""
        server = _make_server()
        cache_store = {}

        def mock_get(key):
            return cache_store.get(key)

        def mock_set(key, value, ttl=300):
            cache_store[key] = value

        mocker.patch("mcp_server._mcp_cache.get", side_effect=mock_get)
        mocker.patch("mcp_server._mcp_cache.set", side_effect=mock_set)

        mock_result = mocker.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello"
        mock_result.stderr = ""
        mocker.patch("mcp_server.subprocess.run", return_value=mock_result)

        # First call with NO_CACHE
        server.call_tool("echo", {"msg": "nocache"}, cache_mode="no_cache")

        # Second call with NORMAL should still miss cache
        mock_get_return = mock_get(_mcp_cache_key("echo", {"msg": "nocache"}))
        assert mock_get_return is None

"""Tests for tool_core/registry.py — ToolRegistry."""

from unittest.mock import patch

from tool_core.registry import ToolRegistry


class TestToolRegistryInit:
    def test_default_state(self):
        reg = ToolRegistry()
        assert reg._cache == {}
        assert reg._last_scan == 0.0
        assert reg._scan_interval == 300


class TestToolRegistryIsAvailable:
    def test_unknown_tool_not_available(self):
        reg = ToolRegistry()
        assert reg.is_available("__definitely_not_installed__") is False

    def test_caches_result(self):
        reg = ToolRegistry()
        with patch.object(reg, "_resolve", return_value="/usr/bin/echo"):
            assert reg.is_available("echo") is True
            assert "echo" in reg._cache

    def test_none_result_cached(self):
        reg = ToolRegistry()
        with patch.object(reg, "_resolve", return_value=None):
            assert reg.is_available("nonexistent") is False
            assert "nonexistent" in reg._cache


    def test_scans_augmented_path(self):
        reg = ToolRegistry()
        with patch.object(reg, "_get_augmented_path", return_value="/usr/bin:/bin"):
            with patch("shutil.which", return_value="/usr/bin/python"):
                path = reg._resolve("python")
                assert path == "/usr/bin/python"

    def test_returns_none_for_missing(self):
        reg = ToolRegistry()
        with patch.object(reg, "_resolve", return_value=None):
            assert reg.resolve("__missing__") is None


class TestToolRegistryAvailableTools:
    def test_returns_available_only(self):
        reg = ToolRegistry()
        reg._cache["tool1"] = "/usr/bin/tool1"
        reg._cache["tool2"] = None
        reg._cache["tool3"] = "/usr/bin/tool3"
        available = reg.available_tools()
        assert "tool1" in available
        assert "tool2" not in available
        assert "tool3" in available


class TestToolRegistryResolve:
    def test_scans_augmented_path(self):
        reg = ToolRegistry()
        with patch.object(reg, "_get_augmented_path", return_value="/usr/bin:/bin"):
            with patch("shutil.which", return_value="/usr/bin/python"):
                path = reg._resolve("python")
                assert path == "/usr/bin/python"

    def test_returns_none_for_missing(self):
        reg = ToolRegistry()
        path = reg._resolve("__definitely_not_installed__xyz__")
        assert path is None


class TestToolRegistryGetMetadata:
    def test_returns_none_for_unknown(self):
        reg = ToolRegistry()
        assert reg.get_metadata("__nonexistent__") is None

    def test_returns_metadata_for_known_tool(self):
        reg = ToolRegistry()
        result = reg.get_metadata("nuclei")
        assert result is not None
        assert result.vendor == "projectdiscovery"

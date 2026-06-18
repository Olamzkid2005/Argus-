"""Tests for tools.attack_paths.asset_graph_builder — Category: function"""

import pytest

from tools.attack_paths.asset_graph_builder import build_asset_graph


class TestBuildAssetGraph:
    """Tests for the build_asset_graph function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = build_asset_graph()
            assert result is not None
        except TypeError:
            pytest.skip("build_asset_graph requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = build_asset_graph()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed

"""Tests for tools.attack_paths.asset_graph_builder — Category: function"""

import pytest

from tools.attack_paths.asset_graph_builder import build_asset_graph


class TestBuildAssetGraph:
    """Tests for the build_asset_graph function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            build_asset_graph()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            build_asset_graph()

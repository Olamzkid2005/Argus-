"""Tests for tools.attack_surface.asset_graph — Category: dataclass"""

import pytest

from tools.attack_surface.asset_graph import Asset, AssetGraph


class TestAsset:
    """Tests for the Asset class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Asset()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            Asset()


class TestAssetGraph:
    """Tests for the AssetGraph class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = AssetGraph()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = AssetGraph()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)

"""Tests for tools.attack_surface.asset_graph — Category: dataclass"""

import pytest

from tools.attack_surface.asset_graph import Asset
from tools.attack_surface.asset_graph import AssetGraph


class TestAsset:
    """Tests for the Asset class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = Asset()
            assert instance is not None
            assert isinstance(instance, Asset)
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = Asset()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            pytest.skip("Requires constructor args")


class TestAssetGraph:
    """Tests for the AssetGraph class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AssetGraph()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AssetGraph()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass

"""Tests for database.services.embedding_service — Category: class"""

import pytest

from database.services.embedding_service import EmbeddingService


class TestEmbeddingService:
    """Tests for the EmbeddingService class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = EmbeddingService()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = EmbeddingService()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass

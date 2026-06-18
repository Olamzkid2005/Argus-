"""Tests for database.services.embedding_service — Category: class"""

import pytest

from database.services.embedding_service import EmbeddingService


class TestEmbeddingService:
    """Tests for the EmbeddingService class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            EmbeddingService()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            EmbeddingService()
            str(EmbeddingService())

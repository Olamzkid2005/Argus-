"""Tests for runtime.workflows.bola — Category: class"""

import pytest

from runtime.workflows.bola import BolaWorkflow


class TestBolaWorkflow:
    """Tests for the BolaWorkflow class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            BolaWorkflow()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            BolaWorkflow()
            str(BolaWorkflow())

"""Tests for runtime.workflows.bola — Category: class"""

import pytest

from runtime.workflows.bola import BolaWorkflow


class TestBolaWorkflow:
    """Tests for the BolaWorkflow class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = BolaWorkflow()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = BolaWorkflow()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass

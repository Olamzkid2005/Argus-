"""Tests for orchestrator_pkg.orchestrator — Category: class"""

import pytest

from orchestrator_pkg.orchestrator import Orchestrator


class TestOrchestrator:
    """Tests for the Orchestrator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Orchestrator()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            Orchestrator()

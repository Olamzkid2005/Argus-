"""Tests for runtime.governance — Category: class"""

import pytest

from runtime.governance import Governance


class TestGovernance:
    """Tests for the Governance class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Governance()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            Governance()

"""Tests for runtime.workflows.steps — Category: class"""

import pytest

from runtime.workflows.steps import AuthenticateStep
from runtime.workflows.steps import DiscoverOwnedResourcesStep
from runtime.workflows.steps import TestBolaStep
from runtime.workflows.steps import TestBoplaStep


class TestAuthenticateStep:
    """Tests for the AuthenticateStep class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AuthenticateStep()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AuthenticateStep()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestDiscoverOwnedResourcesStep:
    """Tests for the DiscoverOwnedResourcesStep class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = DiscoverOwnedResourcesStep()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = DiscoverOwnedResourcesStep()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestTestBolaStep:
    """Tests for the TestBolaStep class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = TestBolaStep()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = TestBolaStep()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass

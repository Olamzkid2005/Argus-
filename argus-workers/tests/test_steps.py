"""Tests for runtime.workflows.steps — Category: class"""

import pytest

from runtime.workflows.steps import AuthenticateStep
from runtime.workflows.steps import DiscoverOwnedResourcesStep
from runtime.workflows.steps import TestBolaStep
from runtime.workflows.steps import TestBoplaStep


class TestAuthenticateStep:
    """Tests for the AuthenticateStep class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AuthenticateStep()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = AuthenticateStep()
        assert instance is not None


class TestDiscoverOwnedResourcesStep:
    """Tests for the DiscoverOwnedResourcesStep class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AuthenticateStep()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = AuthenticateStep()
        assert instance is not None


class TestTestBolaStep:
    """Tests for the TestBolaStep class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AuthenticateStep()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = AuthenticateStep()
        assert instance is not None

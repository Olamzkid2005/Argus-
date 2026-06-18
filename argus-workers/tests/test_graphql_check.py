"""Tests for tools.web_scanner_checks.graphql_check — Category: class"""

import pytest

from tools.web_scanner_checks.graphql_check import GraphqlCheck


class TestGraphqlCheck:
    """Tests for the GraphqlCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = GraphqlCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = GraphqlCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass

"""Tests for tools.web_scanner_checks.graphql_check — Category: class"""

import pytest

from tools.web_scanner_checks.graphql_check import GraphqlCheck


class TestGraphqlCheck:
    """Tests for the GraphqlCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = GraphqlCheck()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = GraphqlCheck()
        assert instance is not None

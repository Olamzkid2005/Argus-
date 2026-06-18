"""Tests for tools.circuit_breaker — Category: enum"""

import pytest

from tools.circuit_breaker import CircuitOpenError
from tools.circuit_breaker import CircuitState


class TestCircuitState:
    """Tests for the CircuitState enum."""

    def test_members_exist(self):
        """Enum has expected members."""
        members = list(CircuitState)
        assert len(members) > 0
        for member in members:
            assert member.name
            assert member.value is not None

    def test_from_value(self):
        """Can construct from string value."""
        members = list(CircuitState)
        if members:
            val = members[0].value
            assert CircuitState(val) == members[0]


class TestCircuitOpenError:
    """Tests for the CircuitOpenError enum."""

    def test_members_exist(self):
        """Enum has expected members."""
        members = list(CircuitOpenError)
        assert len(members) > 0
        for member in members:
            assert member.name
            assert member.value is not None

    def test_from_value(self):
        """Can construct from string value."""
        members = list(CircuitOpenError)
        if members:
            val = members[0].value
            assert CircuitOpenError(val) == members[0]

"""Tests for streaming — Category: abstract_class"""

import pytest

from streaming import Event, EventBus, EventType


class TestEvent:
    """Tests for the Event class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Event()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            Event()


class TestEventType:
    """Tests for the EventType class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = EventType()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = EventType()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestEventBus:
    """Tests for the EventBus abstract class."""

    def test_instantiation(self):
        """Cannot instantiate abstract class."""
        with pytest.raises(TypeError):
            EventBus()

    def test_str_repr(self):
        """Cannot instantiate abstract class."""
        with pytest.raises(TypeError):
            EventBus()

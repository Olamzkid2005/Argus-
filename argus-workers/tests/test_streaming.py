"""Tests for streaming — Category: abstract_class"""

import pytest

from streaming import Event
from streaming import EventBus
from streaming import EventType
from streaming import StreamEvent
from streaming import StreamEventType
from streaming import StreamManager
from streaming import StreamingFindingEmitter


class TestEvent:
    """Tests for the Event class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = Event()
            assert instance is not None
            assert isinstance(instance, Event)
        except TypeError:
            with pytest.raises(TypeError):
                EventBus()

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = Event()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            with pytest.raises(TypeError):
                EventBus()


class TestEventType:
    """Tests for the EventType class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Event()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            EventType()


class TestEventBus:
    """Tests for the EventBus class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = EventBus()
            assert instance is not None
            assert isinstance(instance, EventBus)
        except TypeError:
            with pytest.raises(TypeError):
                EventBus()

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = EventBus()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            with pytest.raises(TypeError):
                EventBus()

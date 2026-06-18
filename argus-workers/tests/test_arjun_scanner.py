"""Tests for tools.arjun_scanner — Category: class"""


from tools.arjun_scanner import ArjunScanner


class TestArjunScanner:
    """Tests for the ArjunScanner class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ArjunScanner()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ArjunScanner()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)

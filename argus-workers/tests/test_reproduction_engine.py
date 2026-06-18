"""Tests for tools.verification.reproduction_engine — Category: class"""


from tools.verification.reproduction_engine import ReproductionEngine


class TestReproductionEngine:
    """Tests for the ReproductionEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ReproductionEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ReproductionEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)

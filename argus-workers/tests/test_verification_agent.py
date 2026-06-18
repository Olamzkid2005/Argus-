"""Tests for tools.verification_agent — Category: class"""


from tools.verification_agent import VerificationAgent


class TestVerificationAgent:
    """Tests for the VerificationAgent class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = VerificationAgent()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = VerificationAgent()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)

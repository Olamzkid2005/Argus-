"""Tests for models.candidate_list — Category: dataclass"""

import pytest

from models.candidate_list import Candidate, CandidateList, CandidateSource


class TestCandidateSource:
    """Tests for the CandidateSource enum."""

    def test_members_exist(self):
        """Enum has expected members."""
        members = list(CandidateSource)
        assert len(members) > 0
        for member in members:
            assert member.name
            assert member.value is not None


class TestCandidate:
    """Tests for the Candidate class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Candidate()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            Candidate()


class TestCandidateList:
    """Tests for the CandidateList class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            CandidateList()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            CandidateList()

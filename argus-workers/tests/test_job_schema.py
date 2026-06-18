"""Tests for job_schema — Category: dataclass"""

import pytest

from job_schema import JobMessage


class TestJobMessage:
    """Tests for the JobMessage class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = JobMessage()
            assert instance is not None
            assert isinstance(instance, JobMessage)
        except TypeError:
            instance = JobMessage()
            assert instance is not None

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = JobMessage()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            instance = JobMessage()
            assert instance is not None

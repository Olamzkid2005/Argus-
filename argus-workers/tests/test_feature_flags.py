"""Tests for feature_flags.py

Covers:
  - FeatureFlags initialization and caching
  - is_enabled / get_flag / get_flag_source with env, DB, and defaults
  - _parse_value type coercion
  - get_all_flags from environment
  - clear_cache
  - Convenience functions: is_enabled, get_flag, get_feature_flags
  - Phase-specific flag name constants
  - Singleton pattern
  - Thread safety
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from feature_flags import (
    FEATURE_ATTACK_GRAPH_V2,
    FEATURE_CLEAN_ORCHESTRATOR,
    FEATURE_ENGAGEMENT_STATE,
    FEATURE_GOVERNANCE_V2,
    FEATURE_MEMORY_RETRIEVAL,
    FEATURE_TRANSACTIONAL_EVENTS,
    FEATURE_TRUE_REACT_LOOP,
    FeatureFlags,
    get_feature_flags,
    get_flag,
    is_enabled,
)


class TestFeatureFlags:
    """Tests for the FeatureFlags class."""

    def test_init_no_db(self):
        flags = FeatureFlags()
        assert flags.db is None
        assert flags._cache == {}

    def test_init_with_db(self):
        mock_db = MagicMock()
        flags = FeatureFlags(db_connection=mock_db)
        assert flags.db is mock_db

    def test_is_enabled_default_false(self):
        flags = FeatureFlags()
        assert flags.is_enabled("NONEXISTENT") is False

    def test_is_enabled_default_true(self):
        flags = FeatureFlags()
        assert flags.is_enabled("NONEXISTENT", default=True) is True

    def test_get_flag_default_none(self):
        flags = FeatureFlags()
        assert flags.get_flag("NONEXISTENT") is None

    def test_get_flag_default_custom(self):
        flags = FeatureFlags()
        assert flags.get_flag("NONEXISTENT", "fallback") == "fallback"

    def test_get_flag_source_default(self):
        flags = FeatureFlags()
        assert flags.get_flag_source("NONEXISTENT") == "default"

    def test_env_var_true(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_NEW_FEATURE": "true"}, clear=False):
            assert flags.is_enabled("NEW_FEATURE") is True
            assert flags.get_flag_source("NEW_FEATURE") == "environment"

    def test_env_var_false(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_NEW_FEATURE": "false"}, clear=False):
            assert flags.is_enabled("NEW_FEATURE") is False

    def test_env_var_numeric(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_THREAD_COUNT": "42"}, clear=False):
            assert flags.get_flag("THREAD_COUNT") == 42
            assert flags.is_enabled("THREAD_COUNT") is True  # 42 is truthy

    def test_env_var_float(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_RATE": "3.14"}, clear=False):
            assert flags.get_flag("RATE") == 3.14

    def test_env_var_string(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_MODE": "strict"}, clear=False):
            assert flags.get_flag("MODE") == "strict"

    def test_env_overrides_default(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_NEW_FEATURE": "true"}, clear=False):
            assert flags.is_enabled("NEW_FEATURE", default=False) is True

    def test_cache_hits(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_TEST_FLAG": "true"}, clear=False):
            # First access sets cache
            assert flags.is_enabled("TEST_FLAG") is True
            # Second access should use cache, not re-read env
            with patch.dict(os.environ, {"ARGUS_FF_TEST_FLAG": "false"}, clear=False):
                assert flags.is_enabled("TEST_FLAG") is True  # Cached value

    def test_clear_cache(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {"ARGUS_FF_TEST_FLAG": "true"}, clear=False):
            assert flags.is_enabled("TEST_FLAG") is True
            flags.clear_cache()
        # After clear, env var is gone, should fall back to default
        assert flags.is_enabled("TEST_FLAG") is False

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("enabled", True),
            ("TRUE", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            ("disabled", False),
            ("42", 42),
            ("3.14", 3.14),
            ("hello", "hello"),
            ("", ""),
        ],
    )
    def test_parse_value(self, raw, expected):
        flags = FeatureFlags()
        assert flags._parse_value(raw) == expected

    def test_get_all_flags_empty(self):
        flags = FeatureFlags()
        with patch.dict(os.environ, {}, clear=True):
            result = flags.get_all_flags()
        assert result == {}

    def test_get_all_flags_with_env(self):
        flags = FeatureFlags()
        with patch.dict(
            os.environ,
            {
                "ARGUS_FF_FEATURE_A": "true",
                "ARGUS_FF_FEATURE_B": "false",
                "OTHER_VAR": "ignored",
            },
            clear=False,
        ):
            result = flags.get_all_flags()
        assert "feature_a" in result
        assert "feature_b" in result
        assert "other_var" not in result
        assert result["feature_a"]["enabled"] is True
        assert result["feature_b"]["enabled"] is False

    def test_db_fallback(self):
        """Test that DB is queried when no env var is set."""
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (True,)
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        with patch("database.connection.get_db", return_value=mock_db):
            # Must pass db_connection (truthy) so _get_value enters the DB branch
            flags = FeatureFlags(db_connection=MagicMock())
            result = flags.is_enabled("DB_FLAG")
            assert result is True
            assert flags.get_flag_source("DB_FLAG") == "database"

    def test_db_connection_failure_uses_default(self):
        """Test graceful degradation when DB query fails."""
        mock_db = MagicMock()
        mock_db.cursor.side_effect = Exception("DB down")

        with patch("database.connection.get_db", return_value=mock_db):
            flags = FeatureFlags()
            result = flags.is_enabled("DB_FLAG", default=False)
            assert result is False
            assert flags.get_flag_source("DB_FLAG") == "default"

    def test_phase_flag_constants(self):
        """Verify all phase-specific flag names are defined."""
        assert FEATURE_ENGAGEMENT_STATE == "ENGAGEMENT_STATE"
        assert FEATURE_TRUE_REACT_LOOP == "TRUE_REACT_LOOP"
        assert FEATURE_CLEAN_ORCHESTRATOR == "CLEAN_ORCHESTRATOR"
        assert FEATURE_ATTACK_GRAPH_V2 == "ATTACK_GRAPH_V2"
        assert FEATURE_MEMORY_RETRIEVAL == "MEMORY_RETRIEVAL"
        assert FEATURE_GOVERNANCE_V2 == "GOVERNANCE_V2"
        assert FEATURE_TRANSACTIONAL_EVENTS == "TRANSACTIONAL_EVENTS"


class TestSingleton:
    """Tests for the get_feature_flags singleton."""

    def test_singleton_returns_same_instance(self):
        ff1 = get_feature_flags()
        ff2 = get_feature_flags()
        assert ff1 is ff2

    def test_singleton_is_shared(self):
        ff = get_feature_flags()
        assert ff is get_feature_flags()


class TestConvenienceFunctions:
    """Tests for the top-level is_enabled and get_flag functions."""

    def test_is_enabled_convenience(self):
        with patch.dict(os.environ, {"ARGUS_FF_TEST": "true"}, clear=False):
            assert is_enabled("TEST") is True

    def test_is_enabled_default(self):
        assert is_enabled("NONEXISTENT") is False

    def test_get_flag_convenience(self):
        with patch.dict(os.environ, {"ARGUS_FF_MODE": "strict"}, clear=False):
            assert get_flag("MODE") == "strict"

    def test_get_flag_default(self):
        flags = FeatureFlags()
        assert flags.get_flag("NONEXISTENT", 42) == 42

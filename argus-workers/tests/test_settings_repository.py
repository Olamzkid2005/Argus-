"""
Unit tests for SettingsRepository and its wiring into llm_client.py.

Tests the repository CRUD methods (mocked connection) and the wiring path
that loads API keys from the user_settings table as fallback in LLMClient.
"""

from unittest.mock import MagicMock, patch

import pytest

from database.settings_repository import SettingsRepository, get_user_api_keys

# ═══════════════════════════════════════════════════════════════════════════
# SettingsRepository unit tests (mocked DB connection)
# ═══════════════════════════════════════════════════════════════════════════


class TestSettingsRepositoryGetUserSetting:
    """Tests for SettingsRepository.get_user_setting()."""

    @patch("database.settings_repository.connect")
    def test_get_user_setting_executes_correct_query(self, mock_connect):
        """Verifies the correct SELECT query is executed with user_email and key."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("sk-openrouter-key123",)
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.get_user_setting("admin@example.com", "openrouter_api_key")

        assert result == "sk-openrouter-key123"
        mock_cursor.execute.assert_called_once_with(
            "SELECT value FROM user_settings WHERE user_email = %s AND key = %s",
            ("admin@example.com", "openrouter_api_key"),
        )

    @patch("database.settings_repository.connect")
    def test_get_user_setting_returns_none_when_not_found(self, mock_connect):
        """No row found returns None, not an exception."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.get_user_setting("nonexistent@example.com", "openai_api_key")

        assert result is None

    @patch("database.settings_repository.connect")
    def test_get_user_setting_handles_db_error_gracefully(self, mock_connect):
        """DB errors return None instead of raising."""
        mock_connect.side_effect = Exception("Connection refused")

        repo = SettingsRepository("postgresql://invalid/test")
        result = repo.get_user_setting("admin@example.com", "api_key")

        assert result is None

    @patch("database.settings_repository.connect")
    def test_get_user_setting_reuses_connection_string(self, mock_connect):
        """Connection string from constructor is passed to connect()."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://custom:pass@db:5432/argus")
        repo.get_user_setting("user@test.com", "llm_api_key")

        mock_connect.assert_called_once_with("postgresql://custom:pass@db:5432/argus")


class TestSettingsRepositoryGetUserSettings:
    """Tests for SettingsRepository.get_user_settings()."""

    @patch("database.settings_repository.connect")
    def test_get_user_settings_returns_dict_of_all_settings(self, mock_connect):
        """All rows are returned as a dict of key -> value."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("openai_api_key", "sk-openai-xxx"),
            ("openrouter_api_key", "sk-or-v1-yyy"),
            ("llm_api_key", "sk-llm-zzz"),
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.get_user_settings("admin@example.com")

        assert result == {
            "openai_api_key": "sk-openai-xxx",
            "openrouter_api_key": "sk-or-v1-yyy",
            "llm_api_key": "sk-llm-zzz",
        }

    @patch("database.settings_repository.connect")
    def test_get_user_settings_filters_none_values(self, mock_connect):
        """Rows with None values are excluded from the result dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("openai_api_key", "sk-valid-key"),
            ("empty_key", None),
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.get_user_settings("admin@example.com")

        assert "empty_key" not in result
        assert result["openai_api_key"] == "sk-valid-key"

    @patch("database.settings_repository.connect")
    def test_get_user_settings_empty_returns_empty_dict(self, mock_connect):
        """No settings returns empty dict, not None."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.get_user_settings("newuser@example.com")

        assert result == {}

    @patch("database.settings_repository.connect")
    def test_get_user_settings_db_error_returns_empty_dict(self, mock_connect):
        """DB errors are caught and empty dict returned."""
        mock_connect.side_effect = Exception("Timeout")

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.get_user_settings("admin@example.com")

        assert result == {}


class TestSettingsRepositorySetUserSetting:
    """Tests for SettingsRepository.set_user_setting()."""

    @patch("database.settings_repository.connect")
    def test_set_user_setting_uses_upsert(self, mock_connect):
        """set_user_setting uses INSERT ... ON CONFLICT DO UPDATE."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.set_user_setting("admin@example.com", "openrouter_api_key", "sk-or-v1-new")

        assert result is True
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO user_settings" in sql
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql
        mock_conn.commit.assert_called_once()

    @patch("database.settings_repository.connect")
    def test_set_user_setting_handles_error_gracefully(self, mock_connect):
        """DB errors return False."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Unique violation")
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.set_user_setting("admin@example.com", "openai_api_key", "sk-xxx")

        assert result is False


class TestSettingsRepositoryDeleteUserSetting:
    """Tests for SettingsRepository.delete_user_setting()."""

    @patch("database.settings_repository.connect")
    def test_delete_user_setting_executes_delete(self, mock_connect):
        """delete_user_setting runs a DELETE query with correct params."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.delete_user_setting("admin@example.com", "openai_api_key")

        assert result is True
        mock_cursor.execute.assert_called_once_with(
            "DELETE FROM user_settings WHERE user_email = %s AND key = %s",
            ("admin@example.com", "openai_api_key"),
        )
        mock_conn.commit.assert_called_once()

    @patch("database.settings_repository.connect")
    def test_delete_user_setting_error_returns_false(self, mock_connect):
        """DB errors return False."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Delete failed")
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        repo = SettingsRepository("postgresql://localhost/test")
        result = repo.delete_user_setting("admin@example.com", "some_key")

        assert result is False


class TestSettingsRepositoryGetUserApiKeys:
    """Tests for the get_user_api_keys convenience function."""

    @patch("database.settings_repository.SettingsRepository.get_user_settings")
    def test_get_user_api_keys_extracts_openai_and_opencode(self, mock_get_settings):
        """The convenience function extracts the two expected key names."""
        mock_get_settings.return_value = {
            "openai_api_key": "sk-openai-xxx",
            "opencode_api_key": "oc-key-yyy",
            "unrelated_key": "irrelevant",
        }

        result = get_user_api_keys("admin@example.com")

        assert result["openai_api_key"] == "sk-openai-xxx"
        assert result["opencode_api_key"] == "oc-key-yyy"
        # Unrelated key is NOT included
        assert "unrelated_key" not in result

    @patch("database.settings_repository.SettingsRepository.get_user_settings")
    def test_get_user_api_keys_missing_keys_are_none(self, mock_get_settings):
        """Missing keys are None in the returned dict."""
        mock_get_settings.return_value = {}

        result = get_user_api_keys("admin@example.com")

        assert result["openai_api_key"] is None
        assert result["opencode_api_key"] is None


# ═══════════════════════════════════════════════════════════════════════════
# LLMClient wiring tests — SettingsRepository fallback
# ═══════════════════════════════════════════════════════════════════════════


class TestLLMClientSettingsRepositoryWiring:
    """Tests for the SettingsRepository wiring in LLMClient._load_key_from_db()."""

    @patch("database.connection.db_cursor")
    def test_load_key_from_db_queries_all_users(self, mock_db_cursor):
        """_load_key_from_db queries DISTINCT ON (key) across ALL users."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("openrouter_api_key", "sk-or-v1-valid-key-here-12345"),
        ]
        mock_db_cursor.return_value.__enter__.return_value = mock_cursor

        from llm_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        result = client._load_key_from_db()

        assert result == "sk-or-v1-valid-key-here-12345"
        sql = mock_cursor.execute.call_args[0][0]
        assert "DISTINCT ON (key)" in sql
        assert "key = ANY(%s)" in sql
        assert "updated_at DESC" in sql

    @patch("database.connection.db_cursor")
    def test_load_key_from_db_returns_first_valid_key(self, mock_db_cursor):
        """First non-None key with len > 10 is returned."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("llm_api_key", "sk-llm-test-key-abcdef123"),
            ("openai_api_key", "sk-proj-valid-long-key-here"),
        ]
        mock_db_cursor.return_value.__enter__.return_value = mock_cursor

        from llm_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        result = client._load_key_from_db()

        # Returns the first valid key (llm_api_key comes first in results)
        assert result == "sk-llm-test-key-abcdef123"

    @patch("database.connection.db_cursor")
    def test_load_key_from_db_filters_short_values(self, mock_db_cursor):
        """Keys with len <= 10 are skipped (likely placeholders)."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("openrouter_api_key", "short"),
            ("openai_api_key", "sk-valid-long-key-abcdef123456"),
        ]
        mock_db_cursor.return_value.__enter__.return_value = mock_cursor

        from llm_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        result = client._load_key_from_db()

        # "short" is skipped, returns the second valid key
        assert result == "sk-valid-long-key-abcdef123456"

    @patch("database.connection.db_cursor")
    def test_load_key_from_db_returns_none_when_no_keys(self, mock_db_cursor):
        """No valid keys returns None."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db_cursor.return_value.__enter__.return_value = mock_cursor

        from llm_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        result = client._load_key_from_db()

        assert result is None

    @patch("database.connection.db_cursor")
    def test_load_key_from_db_handles_error_gracefully(self, mock_db_cursor):
        """DB errors return None without raising."""
        mock_db_cursor.side_effect = Exception("Table does not exist")

        from llm_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        result = client._load_key_from_db()

        assert result is None

    @patch("llm_client.LLMClient._load_key_from_db", return_value="sk-or-v1-db-fallback-key-12345")
    @patch("llm_client.LLMClient._load_key_from_redis", return_value=None)
    @patch("llm_client.LLMClient.is_available", return_value=True)
    @patch("llm_client.os.getenv", side_effect=lambda k, d=None: {
        "OPENAI_API_KEY": None,
        "LLM_API_KEY": None,
        "LLM_PROVIDER": "openai",
        "LLM_MODEL": "gpt-4o-mini",
    }.get(k, d))
    def test_llm_client_calls_load_key_from_db_as_fallback(
        self, mock_getenv, mock_available, mock_redis, mock_load_db
    ):
        """When no API key in env vars or Redis, LLMClient calls _load_key_from_db()."""
        from llm_client import LLMClient

        client = LLMClient()

        mock_load_db.assert_called_once()
        assert client.api_key == "sk-or-v1-db-fallback-key-12345"
        # Ensures the fallback chain worked: env None -> _load_key_from_db() -> return patched value

    def test_load_key_from_db_import_path_valid(self):
        """The _load_key_from_db method exists and is callable on LLMClient."""
        from llm_client import LLMClient
        assert hasattr(LLMClient, "_load_key_from_db")
        assert callable(LLMClient._load_key_from_db)

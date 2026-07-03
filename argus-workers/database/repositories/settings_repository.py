"""
Settings Repository — manages per-user settings stored in the user_settings table.

The user_settings table has the following schema (created in migration 001):
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE,
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()

Settings are stored as a single JSONB blob per user, keyed by user_id.
This repository provides typed accessors for common settings like API keys
and notification preferences.
"""

import json
import logging
from typing import Any

from psycopg2.extras import RealDictCursor

from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class SettingsRepository(BaseRepository):
    """Repository for user_settings table operations.

    Stores and retrieves per-user configuration as a JSONB settings blob.
    The user_id field is a TEXT UNIQUE key (e.g. email or external user ID).

    Phase 5.2.1: Rewritten to match the actual user_settings schema
    (user_id TEXT UNIQUE, settings JSONB) rather than the old
    user_email / key / value columns that don't exist.
    """

    table_name = "user_settings"
    id_column = "id"

    def get_settings(self, user_id: str) -> dict[str, Any]:
        """Get all settings for a user.

        Args:
            user_id: User identifier (TEXT UNIQUE key)

        Returns:
            Settings dict, or empty dict if user not found
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                "SELECT settings FROM user_settings WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row["settings"] or {})
            return {}

    def get_setting(self, user_id: str, key: str, default: Any = None) -> Any:
        """Get a specific setting value for a user.

        Uses JSONB path extraction to read a single key without loading
        the entire settings blob.

        Args:
            user_id: User identifier
            key: Setting key (supports dot-notation for nested keys)
            default: Default value if key not found

        Returns:
            Setting value, or default if not found
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                """
                SELECT settings->%s AS value FROM user_settings WHERE user_id = %s
                """,
                (key, user_id),
            )
            row = cursor.fetchone()
            if row and row["value"] is not None:
                return row["value"]
            return default

    def set_setting(
        self, user_id: str, key: str, value: Any
    ) -> bool:
        """Set a specific setting value for a user.

        Upserts the full settings JSONB blob. If the user doesn't exist,
        creates a new row. Uses jsonb_set to merge the key into existing
        settings without overwriting other keys.

        Args:
            user_id: User identifier
            key: Setting key (supports dot-notation)
            value: Value to set (must be JSON-serializable)

        Returns:
            True if successful
        """
        import json as _json

        value_json = _json.dumps(value) if not isinstance(value, str) else _json.dumps(value)

        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO user_settings (user_id, settings, created_at, updated_at)
                VALUES (%s, %s::jsonb, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    settings = jsonb_set(
                        COALESCE(user_settings.settings, '{}'::jsonb),
                        %s::text[],
                        %s::jsonb,
                        true
                    ),
                    updated_at = NOW()
                """,
                (user_id, f'{{{key}: {value_json}}}', f"{{{key}}}", value_json),
            )
            return True

    def set_settings_bulk(self, user_id: str, settings: dict[str, Any]) -> bool:
        """Replace all settings for a user atomically.

        Args:
            user_id: User identifier
            settings: Complete settings dict

        Returns:
            True if successful
        """
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO user_settings (user_id, settings, created_at, updated_at)
                VALUES (%s, %s::jsonb, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    settings = %s::jsonb,
                    updated_at = NOW()
                """,
                (user_id, json.dumps(settings), json.dumps(settings)),
            )
            return True

    def delete_setting(self, user_id: str, key: str) -> bool:
        """Remove a specific setting key from a user's settings.

        Uses jsonb - operator to remove the key from the JSONB blob.

        Args:
            user_id: User identifier
            key: Setting key to remove

        Returns:
            True if key was removed, False if user/setting not found
        """
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                """
                UPDATE user_settings
                SET settings = settings - %s,
                    updated_at = NOW()
                WHERE user_id = %s
                """,
                (key, user_id),
            )
            return cursor.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """Delete a user's settings entirely.

        Args:
            user_id: User identifier

        Returns:
            True if deleted, False if not found
        """
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                "DELETE FROM user_settings WHERE user_id = %s",
                (user_id,),
            )
            return cursor.rowcount > 0

    def get_api_key(self, user_id: str) -> str | None:
        """Get the OpenAI/LLM API key for a user.

        Convenience method: reads settings->'openai_api_key' from the
        user_settings JSONB blob.

        Args:
            user_id: User identifier

        Returns:
            API key string, or None if not set
        """
        return self.get_setting(user_id, "openai_api_key")

    def set_api_key(self, user_id: str, api_key: str) -> bool:
        """Set the OpenAI/LLM API key for a user.

        Args:
            user_id: User identifier
            api_key: API key to store

        Returns:
            True if successful
        """
        return self.set_setting(user_id, "openai_api_key", api_key)

    def list_users(self) -> list[dict[str, Any]]:
        """List all users with their settings metadata.

        Returns user_id and updated_at for each user. Does NOT include
        settings values in the list response to avoid leaking sensitive data.

        Returns:
            List of user metadata dicts
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                """
                SELECT user_id, created_at, updated_at
                FROM user_settings
                ORDER BY updated_at DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

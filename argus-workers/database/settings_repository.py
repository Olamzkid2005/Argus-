"""
Settings Repository - Retrieve user API keys and settings

Uses the shared ConnectionManager pool instead of creating one-off
connections to prevent connection exhaustion (H-29).
"""
import logging
import os

from cryptography.fernet import Fernet

from database.connection import db_cursor

logger = logging.getLogger(__name__)

_SETTINGS_ENCRYPTION_KEY = None


def _get_cipher():
    global _SETTINGS_ENCRYPTION_KEY
    if _SETTINGS_ENCRYPTION_KEY is None:
        key = os.environ.get("SETTINGS_ENCRYPTION_KEY")
        if not key:
            key = Fernet.generate_key()
            os.environ["SETTINGS_ENCRYPTION_KEY"] = key.decode()
        if isinstance(key, str):
            key = key.encode()
        _SETTINGS_ENCRYPTION_KEY = key
    return Fernet(_SETTINGS_ENCRYPTION_KEY)


def _encrypt(value: str) -> str:
    try:
        return _get_cipher().encrypt(value.encode()).decode()
    except Exception:
        return value


def _decrypt(value: str) -> str:
    try:
        return _get_cipher().decrypt(value.encode()).decode()
    except Exception:
        return value


class SettingsRepository:
    """Repository for user settings and API keys

    Uses the shared ConnectionManager pool for all operations to prevent
    connection exhaustion (H-29).
    """

    def get_user_setting(self, user_email: str, key: str) -> str | None:
        """
        Get a specific setting for a user.

        Args:
            user_email: User's email address
            key: Setting key (e.g., 'openai_api_key', 'opencode_api_key')

        Returns:
            Setting value or None if not found
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT value FROM user_settings WHERE user_email = %s AND key = %s",
                    (user_email, key)
                )
                row = cursor.fetchone()
                value = row[0] if row else None
                return _decrypt(value) if value else None
        except Exception as e:
            logger.error("Failed to get user setting: %s", e)
            return None

    def get_user_settings(self, user_email: str) -> dict[str, str]:
        """
        Get all settings for a user.

        Args:
            user_email: User's email address

        Returns:
            Dictionary of settings
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT key, value FROM user_settings WHERE user_email = %s",
                    (user_email,)
                )
                rows = cursor.fetchall()
                return {row[0]: _decrypt(row[1]) for row in rows if row[1]}
        except Exception as e:
            logger.error("Failed to get user settings: %s", e)
            return {}

    def set_user_setting(self, user_email: str, key: str, value: str) -> bool:
        """
        Set a setting for a user.

        Args:
            user_email: User's email address
            key: Setting key
            value: Setting value

        Returns:
            True if successful
        """
        try:
            with db_cursor(commit=True) as cursor:
                cursor.execute("""
                    INSERT INTO user_settings (user_email, key, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_email, key)
                    DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP
                """, (user_email, key, _encrypt(value), _encrypt(value)))
                return True
        except Exception as e:
            logger.error("Failed to set user setting: %s", e)
            return False

    def delete_user_setting(self, user_email: str, key: str) -> bool:
        """
        Delete a setting for a user.

        Args:
            user_email: User's email address
            key: Setting key

        Returns:
            True if successful
        """
        try:
            with db_cursor(commit=True) as cursor:
                cursor.execute(
                    "DELETE FROM user_settings WHERE user_email = %s AND key = %s",
                    (user_email, key)
                )
                return True
        except Exception as e:
            logger.error("Failed to delete user setting: %s", e)
            return False


# Convenience function
def get_user_api_keys(user_email: str) -> dict[str, str]:
    """
    Get all API keys for a user.

    Args:
        user_email: User's email address

    Returns:
        Dictionary with 'openai_api_key' and 'opencode_api_key'
    """
    repo = SettingsRepository()
    settings = repo.get_user_settings(user_email)

    return {
        "openai_api_key": settings.get("openai_api_key"),
        "opencode_api_key": settings.get("opencode_api_key"),
    }

"""
Settings Repository - Retrieve user API keys and settings
"""
import os

from database.connection import connect


class SettingsRepository:
    """Repository for user settings and API keys"""

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")

    def get_user_setting(self, user_email: str, key: str) -> str | None:
        """
        Get a specific setting for a user.

        Args:
            user_email: User's email address
            key: Setting key (e.g., 'openai_api_key', 'opencode_api_key')

        Returns:
            Setting value or None if not found
        """
        conn = None
        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT value FROM user_settings WHERE user_email = %s AND key = %s",
                (user_email, key)
            )

            row = cursor.fetchone()
            cursor.close()

            return row[0] if row else None
        except Exception as e:
            print(f"Failed to get user setting: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_user_settings(self, user_email: str) -> dict[str, str]:
        """
        Get all settings for a user.

        Args:
            user_email: User's email address

        Returns:
            Dictionary of settings
        """
        conn = None
        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT key, value FROM user_settings WHERE user_email = %s",
                (user_email,)
            )

            rows = cursor.fetchall()
            cursor.close()

            return {row[0]: row[1] for row in rows if row[1]}
        except Exception as e:
            print(f"Failed to get user settings: {e}")
            return {}
        finally:
            if conn:
                conn.close()

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
        conn = None
        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO user_settings (user_email, key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_email, key)
                DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP
            """, (user_email, key, value, value))

            conn.commit()
            cursor.close()

            return True
        except Exception as e:
            print(f"Failed to set user setting: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def delete_user_setting(self, user_email: str, key: str) -> bool:
        """
        Delete a setting for a user.

        Args:
            user_email: User's email address
            key: Setting key

        Returns:
            True if successful
        """
        conn = None
        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()

            cursor.execute(
                "DELETE FROM user_settings WHERE user_email = %s AND key = %s",
                (user_email, key)
            )

            conn.commit()
            cursor.close()

            return True
        except Exception as e:
            print(f"Failed to delete user setting: {e}")
            return False
        finally:
            if conn:
                conn.close()


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

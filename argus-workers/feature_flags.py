"""
Feature Flags System

Simple feature flag system for gradual rollout of new features.
Checks environment variables first, then falls back to database values.

Usage:
    from feature_flags import is_enabled, get_flag

    if is_enabled("new_scanner"):
        run_new_scanner()

Requirements: 4.9
"""

import logging
import os
import threading
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class FlagSource(Enum):
    """Source of the feature flag value."""

    ENV = "environment"
    DB = "database"
    DEFAULT = "default"


class FeatureFlags:
    """
    Feature flag manager.

    Priority:
    1. Environment variable (ARGUS_FF_<name>)
    2. Database value (if db_connection provided)
    3. Default value
    """

    def __init__(self, db_connection=None):
        """
        Initialize feature flags manager.

        Args:
            db_connection: Optional database connection for persistent flags
        """
        self.db = db_connection
        self._cache: dict[str, tuple] = {}  # name -> (value, source)

    def is_enabled(self, flag_name: str, default: bool = False) -> bool:
        """
        Check if a feature flag is enabled.

        Args:
            flag_name: Name of the feature flag
            default: Default value if not configured

        Returns:
            True if enabled, False otherwise
        """
        value, _ = self._get_value(flag_name, default)
        return bool(value)

    def get_flag(self, flag_name: str, default: Any = None) -> Any:
        """
        Get the raw value of a feature flag.

        Args:
            flag_name: Name of the feature flag
            default: Default value if not configured

        Returns:
            Flag value or default
        """
        value, _ = self._get_value(flag_name, default)
        return value

    def get_flag_source(self, flag_name: str) -> str | None:
        """Get the source of a flag value."""
        _, source = self._get_value(flag_name, None)
        return source.value if source else None

    def _get_value(self, flag_name: str, default: Any) -> tuple:
        """
        Get flag value and source.

        Returns:
            Tuple of (value, source)
        """
        # Check cache
        if flag_name in self._cache:
            return self._cache[flag_name]

        # 1. Check environment variable
        env_name = f"ARGUS_FF_{flag_name.upper()}"
        env_value = os.environ.get(env_name)
        if env_value is not None:
            parsed = self._parse_value(env_value)
            self._cache[flag_name] = (parsed, FlagSource.ENV)
            logger.debug("Feature flag %s=%s from env", flag_name, parsed)
            return self._cache[flag_name]

        # 2. Check database
        if self.db:
            try:
                db_value = self._load_flag_from_db(flag_name)
                if db_value is not None:
                    self._cache[flag_name] = (db_value, FlagSource.DB)
                    logger.debug("Feature flag %s=%s from db", flag_name, db_value)
                    return self._cache[flag_name]
            except Exception as e:
                logger.warning("Failed to read feature flag from DB: %s", e)

        # 3. Use default
        self._cache[flag_name] = (default, FlagSource.DEFAULT)
        return self._cache[flag_name]

    def _parse_value(self, value: str) -> Any:
        """Parse a string value into appropriate type."""
        value = value.strip().lower()
        if value in ("1", "true", "yes", "on", "enabled"):
            return True
        if value in ("0", "false", "no", "off", "disabled"):
            return False
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value

    def _load_flag_from_db(self, flag_name: str) -> bool | None:
        """Load flag value from database. Returns None if not found."""
        try:
            from database.connection import get_db

            db = get_db()
            conn = db.get_connection()
            cursor = None
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT enabled FROM feature_flags WHERE flag_name = %s",
                    (flag_name,),
                )
                row = cursor.fetchone()
                return row[0] if row else None
            finally:
                if cursor:
                    cursor.close()
                db.release_connection(conn)
        except Exception as e:
            logger.debug("Failed to load feature flag '%s' from DB: %s", flag_name, e)
            return None

    def clear_cache(self):
        """Clear the flag cache to force re-read."""
        self._cache.clear()

    def get_all_flags(self) -> dict[str, dict[str, Any]]:
        """
        Get all configured flags.

        Returns:
            Dictionary of flag_name -> {value, source}
        """
        # Get all ARGUS_FF_* env vars
        flags = {}
        for key, value in os.environ.items():
            if key.startswith("ARGUS_FF_"):
                name = key[9:].lower()  # Remove ARGUS_FF_ prefix
                parsed = self._parse_value(value)
                flags[name] = {
                    "value": parsed,
                    "source": "environment",
                    "enabled": bool(parsed),
                }
        return flags


# ── Phase-specific feature flag names ──
# These are the canonical flag names used across the codebase
# to gate the Agent Runtime Refactor phases.

FEATURE_ENGAGEMENT_STATE = "ENGAGEMENT_STATE"
FEATURE_TRUE_REACT_LOOP = "TRUE_REACT_LOOP"
FEATURE_CLEAN_ORCHESTRATOR = "CLEAN_ORCHESTRATOR"
FEATURE_ATTACK_GRAPH_V2 = "ATTACK_GRAPH_V2"
FEATURE_MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
FEATURE_GOVERNANCE_V2 = "GOVERNANCE_V2"
FEATURE_TRANSACTIONAL_EVENTS = "TRANSACTIONAL_EVENTS"

# Global instance for convenience
_global_flags: FeatureFlags | None = None
_global_flags_lock = threading.Lock()


def get_feature_flags(db_connection=None) -> FeatureFlags:
    """Get or create the global FeatureFlags instance."""
    global _global_flags
    if _global_flags is None:
        with _global_flags_lock:
            if _global_flags is None:
                _global_flags = FeatureFlags(db_connection)
    return _global_flags


def is_enabled(flag_name: str, default: bool = False) -> bool:
    """Check if a feature flag is enabled (convenience function)."""
    return get_feature_flags().is_enabled(flag_name, default)


def get_flag(flag_name: str, default: Any = None) -> Any:
    """Get a feature flag value (convenience function)."""
    return get_feature_flags().get_flag(flag_name, default)

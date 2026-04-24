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
import os
import logging
from typing import Dict, Optional, Any
from enum import Enum

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
        self._cache: Dict[str, tuple] = {}  # name -> (value, source)

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

    def get_flag_source(self, flag_name: str) -> Optional[str]:
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
            logger.debug(f"Feature flag {flag_name}={parsed} from env")
            return self._cache[flag_name]

        # 2. Check database
        if self.db:
            try:
                db_value = self._get_from_db(flag_name)
                if db_value is not None:
                    self._cache[flag_name] = (db_value, FlagSource.DB)
                    logger.debug(f"Feature flag {flag_name}={db_value} from db")
                    return self._cache[flag_name]
            except Exception as e:
                logger.warning(f"Failed to read feature flag from DB: {e}")

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

    def _get_from_db(self, flag_name: str) -> Optional[Any]:
        """Get flag value from database."""
        # This would query a feature_flags table
        # For now, return None to use default
        return None

    def clear_cache(self):
        """Clear the flag cache to force re-read."""
        self._cache.clear()

    def get_all_flags(self) -> Dict[str, Dict[str, Any]]:
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


# Global instance for convenience
_global_flags: Optional[FeatureFlags] = None


def get_feature_flags(db_connection=None) -> FeatureFlags:
    """Get or create the global FeatureFlags instance."""
    global _global_flags
    if _global_flags is None:
        _global_flags = FeatureFlags(db_connection)
    return _global_flags


def is_enabled(flag_name: str, default: bool = False) -> bool:
    """Check if a feature flag is enabled (convenience function)."""
    return get_feature_flags().is_enabled(flag_name, default)


def get_flag(flag_name: str, default: Any = None) -> Any:
    """Get a feature flag value (convenience function)."""
    return get_feature_flags().get_flag(flag_name, default)

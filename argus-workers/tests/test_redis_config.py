"""Tests for config/redis.py

Covers:
  - REDIS_URL default when no env var set
  - REDIS_URL from environment variable
  - Module-level initialization
"""

from __future__ import annotations

# We need to reload the module to test different env states
import importlib
import os
from unittest.mock import patch


class TestRedisConfig:
    """Tests for config/redis module."""

    def test_default_url_when_not_set(self):
        """When REDIS_URL is not set, should default to localhost."""
        with patch.dict(os.environ, {}, clear=True):
            import config.redis as redis_config

            importlib.reload(redis_config)
            assert redis_config.REDIS_URL == "redis://localhost:6379"

    def test_url_from_env_var(self):
        """When REDIS_URL is set, should use the env var value."""
        with patch.dict(
            os.environ, {"REDIS_URL": "redis://myredis:6380/1"}, clear=True
        ):
            import config.redis as redis_config

            importlib.reload(redis_config)
            assert redis_config.REDIS_URL == "redis://myredis:6380/1"

"""
Secrets Management

Wraps HashiCorp Vault and AWS Secrets Manager for secure secret retrieval.
Falls back to environment variables for local development.
"""

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


class SecretsManager:
    """
    Unified secrets manager supporting multiple backends.

    Priority:
    1. HashiCorp Vault (if VAULT_ADDR configured)
    2. AWS Secrets Manager (if AWS_REGION configured)
    3. Environment variables (fallback)
    """

    def __init__(self):
        self._vault_client = None
        self._aws_client = None
        self._cache: dict[str, Any] = {}

    def _get_vault_client(self):
        """Lazy init Vault client"""
        if self._vault_client is None:
            try:
                import hvac
                self._vault_client = hvac.Client(
                    url=os.getenv("VAULT_ADDR", "http://localhost:8200"),
                    token=os.getenv("VAULT_TOKEN")
                )
            except ImportError:
                logger.warning("hvac not installed, Vault unavailable")
        return self._vault_client

    def _get_aws_client(self):
        """Lazy init AWS Secrets Manager client"""
        if self._aws_client is None:
            try:
                import boto3
                self._aws_client = boto3.client(
                    "secretsmanager",
                    region_name=os.getenv("AWS_REGION", "us-east-1")
                )
            except ImportError:
                logger.warning("boto3 not installed, AWS Secrets Manager unavailable")
        return self._aws_client

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        """
        Retrieve a secret by key.

        Args:
            key: Secret key/name
            default: Default value if secret not found

        Returns:
            Secret value or default
        """
        # Check cache first
        if key in self._cache:
            return self._cache[key]

        # Try Vault
        vault = self._get_vault_client()
        if vault and vault.is_authenticated():
            try:
                path = os.getenv("VAULT_SECRET_PATH", "secret/argus")
                response = vault.secrets.kv.v2.read_secret_version(
                    path=f"{path}/{key}"
                )
                value = response["data"]["data"]["value"]
                self._cache[key] = value
                return value
            except Exception as e:
                logger.debug("Vault secret lookup failed for %s: %s", key, e)

        # Try AWS Secrets Manager
        aws = self._get_aws_client()
        if aws:
            try:
                response = aws.get_secret_value(SecretId=f"argus/{key}")
                value = response.get("SecretString", default)
                self._cache[key] = value
                return value
            except Exception as e:
                logger.debug("AWS Secrets Manager lookup failed for %s: %s", key, e)

        # Fall back to environment variable
        env_value = os.getenv(key)
        if env_value:
            return env_value

        return default

    def get_database_url(self) -> str:
        """Get database URL from secrets or env"""
        return self.get_secret(
            "DATABASE_URL",
            os.getenv("DATABASE_URL", "postgresql://localhost/argus")
        )

    def get_redis_url(self) -> str:
        """Get Redis URL from secrets or env"""
        return self.get_secret(
            "REDIS_URL",
            os.getenv("REDIS_URL", "redis://localhost:6379")
        )

    def get_api_key(self, service: str) -> str | None:
        """Get API key for external service"""
        return self.get_secret(f"{service.upper()}_API_KEY")

    def invalidate_cache(self, key: str | None = None):
        """Invalidate secret cache"""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


# Singleton instance
_secrets_manager: SecretsManager | None = None
_secrets_lock = threading.Lock()


def get_secrets_manager() -> SecretsManager:
    """Get singleton secrets manager (thread-safe)"""
    global _secrets_manager
    if _secrets_manager is None:
        with _secrets_lock:
            if _secrets_manager is None:
                _secrets_manager = SecretsManager()
    return _secrets_manager

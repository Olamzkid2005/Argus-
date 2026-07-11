"""
Secrets Management

Wraps HashiCorp Vault and AWS Secrets Manager for secure secret retrieval.
Falls back to environment variables for local development.

Security notes:
- Default Vault URL uses HTTPS (not HTTP) to enforce TLS
- Set VAULT_SKIP_VERIFY=true only for development with self-signed certs
- Secrets are cached in-memory with optional Fernet encryption (Gap 7.8)
- Use invalidate_cache() to clear the cache
"""

import base64
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Gap 7.8: Lazy Fernet cipher for optional at-rest encryption of cached secrets.
# Enabled when FERNET_SECRET_KEY env var is set. The key must be 32 URL-safe
# base64-encoded bytes (44 chars). Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_FERNET_UNAVAILABLE = object()  # Sentinel to cache failed init
_fernet_cipher = None
_fernet_lock = threading.Lock()


def _get_fernet():
    """Get the Fernet cipher from FERNET_SECRET_KEY env var.

    Returns None if the env var is not set, cryptography is not installed,
    or the key is invalid. The failure is cached so we don't retry the
    import on every call.
    """
    global _fernet_cipher
    if _fernet_cipher is None:
        key = os.getenv("FERNET_SECRET_KEY")
        if not key:
            _fernet_cipher = _FERNET_UNAVAILABLE
            return None
        with _fernet_lock:
            if _fernet_cipher is None or _fernet_cipher is _FERNET_UNAVAILABLE:
                try:
                    from cryptography.fernet import Fernet
                    _fernet_cipher = Fernet(key.encode() if isinstance(key, str) else key)
                except Exception:
                    logger.warning(
                        "Fernet encryption unavailable: cryptography not installed "
                        "or invalid FERNET_SECRET_KEY. Secrets will be cached in plaintext."
                    )
                    _fernet_cipher = _FERNET_UNAVAILABLE
                    return None
    if _fernet_cipher is _FERNET_UNAVAILABLE:
        return None
    return _fernet_cipher


def _encrypt_value(value: str) -> str:
    """Encrypt a secret value with Fernet. Falls back to plaintext if unavailable."""
    cipher = _get_fernet()
    if cipher is None:
        return value
    encrypted = cipher.encrypt(value.encode())
    return f"__enc__:{encrypted.decode()}"


def _decrypt_value(value: str) -> str:
    """Decrypt a cached secret value. Passes through plaintext values unchanged."""
    if not isinstance(value, str) or not value.startswith("__enc__:"):
        return value
    cipher = _get_fernet()
    if cipher is None:
        return value
    try:
        encrypted = value[len("__enc__:"):].encode()
        return cipher.decrypt(encrypted).decode()
    except Exception:
        logger.warning("Failed to decrypt cached secret — returning as-is")
        return value


class SecretsManager:
    """
    Unified secrets manager supporting multiple backends.

    Priority:
    1. HashiCorp Vault (if VAULT_ADDR configured)
    2. AWS Secrets Manager (if AWS_REGION configured)
    3. Environment variables (fallback)

    Gap 7.8: All secrets stored in the in-memory cache are encrypted at rest
    using Fernet (symmetric AES-128-CBC with HMAC) when FERNET_SECRET_KEY is set.
    """

    def __init__(self):
        self._vault_client = None
        self._aws_client = None
        self._cache: dict[str, Any] = {}

    def _get_vault_client(self):
        """Lazy init Vault client with TLS enforcement"""
        if self._vault_client is None:
            try:
                import hvac

                vault_addr = os.getenv("VAULT_ADDR", "https://localhost:8200")
                vault_token = os.getenv("VAULT_TOKEN")

                # Warn if using HTTP without skip_verify
                if vault_addr.startswith("http://"):
                    skip_verify = os.getenv("VAULT_SKIP_VERIFY", "").lower() in (
                        "true",
                        "1",
                        "yes",
                    )
                    if not skip_verify:
                        logger.warning(
                            "Vault URL uses HTTP (not HTTPS): %s. "
                            "Set VAULT_ADDR to an HTTPS URL in production, "
                            "or set VAULT_SKIP_VERIFY=true for local dev only.",
                            vault_addr,
                        )

                verify = os.getenv("VAULT_SKIP_VERIFY", "").lower() not in (
                    "true",
                    "1",
                    "yes",
                )

                self._vault_client = hvac.Client(
                    url=vault_addr,
                    token=vault_token,
                    verify=verify,
                    timeout=tuple(
                        int(x) for x in os.getenv("VAULT_TIMEOUT", "10,30").split(",")
                    )
                    if os.getenv("VAULT_TIMEOUT")
                    else None,
                )
            except ImportError:
                logger.warning("hvac not installed, Vault unavailable")
        return self._vault_client

    def _get_aws_client(self):
        """Lazy init AWS Secrets Manager client"""
        if self._aws_client is None:
            try:
                import boto3
                from botocore.config import Config as BotoConfig

                aws_timeout = float(os.getenv("AWS_TIMEOUT", "10"))
                self._aws_client = boto3.client(
                    "secretsmanager",
                    region_name=os.getenv("AWS_REGION", "us-east-1"),
                    config=BotoConfig(
                        connect_timeout=aws_timeout,
                        read_timeout=aws_timeout,
                        retries={"max_attempts": 2},
                    ),
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
        # Check cache first (decrypt if stored encrypted)
        if key in self._cache:
            return _decrypt_value(self._cache[key])

        # Try Vault
        vault = self._get_vault_client()
        if vault and vault.is_authenticated():
            try:
                path = os.getenv("VAULT_SECRET_PATH", "secret/argus")
                # Normalize key for Vault path — replace special chars with underscore
                # to support keys with dots, spaces, or other characters that are
                # uncommon in Vault paths while keeping the path readable.
                import re

                vault_path_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", key)
                response = vault.secrets.kv.v2.read_secret_version(
                    path=f"{path}/{vault_path_key}"
                )
                data = response.get("data", {}).get("data", {})
                # Try the original key first, then the vault_path_key, then 'value'
                value = data.get(key) or data.get(vault_path_key) or data.get("value") or ""
                self._cache[key] = _encrypt_value(value)
                return value
            except Exception as e:
                logger.debug("Vault secret lookup failed for %s: %s", key, e)

        # Try AWS Secrets Manager
        aws = self._get_aws_client()
        if aws:
            try:
                response = aws.get_secret_value(SecretId=f"argus/{key}")
                if "SecretString" in response:
                    value = response["SecretString"]
                elif "SecretBinary" in response:
                    value = base64.b64decode(response["SecretBinary"]).decode()
                else:
                    value = default
                self._cache[key] = _encrypt_value(value)
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
            "DATABASE_URL", os.getenv("DATABASE_URL", "postgresql://localhost/argus")
        ) or ""

    def get_redis_url(self) -> str:
        """Get Redis URL from secrets or env"""
        return self.get_secret(
            "REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379")
        ) or ""

    def get_api_key(self, service: str) -> str | None:
        """Get API key for external service"""
        return self.get_secret(f"{service.upper()}_API_KEY")

    def invalidate_cache(self, key: str | None = None):
        """Invalidate secret cache"""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def is_cache_encrypted(self) -> bool:
        """Check if the cache is using Fernet encryption.

        Returns True if FERNET_SECRET_KEY is configured and cryptography is available.
        """
        return _get_fernet() is not None


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

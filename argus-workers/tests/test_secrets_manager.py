"""
Tests for secrets_manager.py

Validates: Vault retrieval, AWS retrieval, caching, environment fallback
"""
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from secrets_manager import SecretsManager, get_secrets_manager


class TestSecretsManager:
    """Tests for SecretsManager class"""

    @pytest.fixture
    def manager(self):
        """Fixture providing a SecretsManager with no pre-initialized clients"""
        sm = SecretsManager()
        sm._vault_client = None
        sm._aws_client = None
        sm._cache = {}
        return sm

    def test_init(self, manager):
        """Test secrets manager initialization"""
        assert manager._vault_client is None
        assert manager._aws_client is None
        assert manager._cache == {}

    def test_get_vault_client(self, manager):
        """Test lazy initialization of Vault client"""
        mock_hvac = Mock()
        mock_client = MagicMock()
        mock_hvac.Client.return_value = mock_client

        with (
            patch.dict(os.environ, {"VAULT_ADDR": "http://vault:8200", "VAULT_TOKEN": "token123"}, clear=False),
            patch("builtins.__import__", side_effect=lambda name, *args, **kwargs: mock_hvac if name == "hvac" else __builtins__.__import__(name, *args, **kwargs)),
        ):
            client = manager._get_vault_client()

        assert client is mock_client
        mock_hvac.Client.assert_called_once_with(url="http://vault:8200", token="token123")

    def test_get_vault_client_import_error(self, manager):
        """Test Vault client handles missing hvac gracefully"""
        with patch("builtins.__import__", side_effect=ImportError("No module named hvac")):
            client = manager._get_vault_client()
        assert client is None

    def test_get_aws_client(self, manager):
        """Test lazy initialization of AWS Secrets Manager client"""
        mock_boto3 = Mock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        with (
            patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=False),
            patch("builtins.__import__", side_effect=lambda name, *args, **kwargs: mock_boto3 if name == "boto3" else __builtins__.__import__(name, *args, **kwargs)),
        ):
            client = manager._get_aws_client()

        assert client is mock_client
        mock_boto3.client.assert_called_once_with("secretsmanager", region_name="us-west-2")

    def test_get_aws_client_import_error(self, manager):
        """Test AWS client handles missing boto3 gracefully"""
        with patch("builtins.__import__", side_effect=ImportError("No module named boto3")):
            client = manager._get_aws_client()
        assert client is None

    def test_get_secret_from_vault(self, manager):
        """Test retrieving secret from Vault"""
        mock_vault = MagicMock()
        mock_vault.is_authenticated.return_value = True
        mock_vault.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"value": "vault-secret-value"}}
        }
        manager._vault_client = mock_vault

        with patch.dict(os.environ, {"VAULT_SECRET_PATH": "secret/argus"}, clear=False):
            result = manager.get_secret("my-key")

        assert result == "vault-secret-value"
        assert manager._cache["my-key"] == "vault-secret-value"
        mock_vault.secrets.kv.v2.read_secret_version.assert_called_once_with(path="secret/argus/my-key")

    def test_get_secret_from_aws(self, manager):
        """Test retrieving secret from AWS Secrets Manager"""
        mock_aws = MagicMock()
        mock_aws.get_secret_value.return_value = {"SecretString": "aws-secret-value"}
        manager._aws_client = mock_aws
        # Ensure vault is not used
        manager._vault_client = None

        result = manager.get_secret("my-key")

        assert result == "aws-secret-value"
        assert manager._cache["my-key"] == "aws-secret-value"
        mock_aws.get_secret_value.assert_called_once_with(SecretId="argus/my-key")

    def test_get_secret_from_cache(self, manager):
        """Test secret is returned from cache when available"""
        manager._cache["cached-key"] = "cached-value"

        result = manager.get_secret("cached-key")

        assert result == "cached-value"

    def test_get_secret_fallback_env(self, manager):
        """Test falling back to environment variable"""
        with patch.dict(os.environ, {"MY_SECRET": "env-value"}, clear=False):
            result = manager.get_secret("MY_SECRET")

        assert result == "env-value"

    def test_get_secret_default(self, manager):
        """Test returning default when secret not found anywhere"""
        result = manager.get_secret("nonexistent-key", default="fallback")
        assert result == "fallback"

    def test_get_secret_no_default(self, manager):
        """Test returning None when no secret and no default"""
        result = manager.get_secret("nonexistent-key")
        assert result is None

    def test_get_database_url(self, manager):
        """Test get_database_url retrieves DATABASE_URL"""
        with patch.object(manager, "get_secret", return_value="postgres://db") as mock_get:
            result = manager.get_database_url()

        assert result == "postgres://db"
        mock_get.assert_called_once_with("DATABASE_URL", os.getenv("DATABASE_URL", "postgresql://localhost/argus"))

    def test_get_redis_url(self, manager):
        """Test get_redis_url retrieves REDIS_URL"""
        with patch.object(manager, "get_secret", return_value="redis://cache") as mock_get:
            result = manager.get_redis_url()

        assert result == "redis://cache"
        mock_get.assert_called_once_with("REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379"))

    def test_get_api_key(self, manager):
        """Test get_api_key constructs correct key name"""
        with patch.object(manager, "get_secret", return_value="api-key-123") as mock_get:
            result = manager.get_api_key("stripe")

        assert result == "api-key-123"
        mock_get.assert_called_once_with("STRIPE_API_KEY")

    def test_invalidate_cache_single_key(self, manager):
        """Test invalidating cache for a single key"""
        manager._cache = {"key1": "val1", "key2": "val2"}
        manager.invalidate_cache("key1")

        assert "key1" not in manager._cache
        assert "key2" in manager._cache

    def test_invalidate_cache_all(self, manager):
        """Test invalidating entire cache"""
        manager._cache = {"key1": "val1", "key2": "val2"}
        manager.invalidate_cache()

        assert manager._cache == {}

    def test_get_secret_vault_unauthenticated(self, manager):
        """Test Vault fallback when not authenticated"""
        mock_vault = MagicMock()
        mock_vault.is_authenticated.return_value = False
        manager._vault_client = mock_vault
        manager._aws_client = None

        with patch.dict(os.environ, {"MY_KEY": "env-val"}, clear=False):
            result = manager.get_secret("MY_KEY")

        assert result == "env-val"

    def test_get_secret_vault_exception(self, manager):
        """Test Vault exception falls through to next backend"""
        mock_vault = MagicMock()
        mock_vault.is_authenticated.return_value = True
        mock_vault.secrets.kv.v2.read_secret_version.side_effect = Exception("Vault error")
        manager._vault_client = mock_vault
        manager._aws_client = None

        with patch.dict(os.environ, {"MY_KEY": "env-val"}, clear=False):
            result = manager.get_secret("MY_KEY")

        assert result == "env-val"

    def test_get_secret_aws_exception(self, manager):
        """Test AWS exception falls through to environment"""
        mock_aws = MagicMock()
        mock_aws.get_secret_value.side_effect = Exception("AWS error")
        manager._vault_client = None
        manager._aws_client = mock_aws

        with patch.dict(os.environ, {"MY_KEY": "env-val"}, clear=False):
            result = manager.get_secret("MY_KEY")

        assert result == "env-val"


class TestSingleton:
    """Tests for singleton accessor"""

    def test_get_secrets_manager_returns_same_instance(self):
        """Test get_secrets_manager returns a singleton"""
        sm1 = get_secrets_manager()
        sm2 = get_secrets_manager()
        assert sm1 is sm2

    def test_get_secrets_manager_returns_manager(self):
        """Test get_secrets_manager returns correct type"""
        sm = get_secrets_manager()
        assert isinstance(sm, SecretsManager)

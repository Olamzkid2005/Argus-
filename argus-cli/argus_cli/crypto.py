"""
B.08: Secrets encryption at rest — machine-local Fernet symmetric encryption.

Key management:
  - Auto-generated machine key stored at ~/.argus/.key (0600 permissions)
  - Uses cryptography.fernet (AES-128-CBC with HMAC-SHA256)
  - No passphrase required — the key IS the secret

Usage:
    from argus_cli.crypto import encrypt_value, decrypt_value

    ciphertext = encrypt_value(plaintext)
    plaintext = decrypt_value(ciphertext)
"""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """Raised when decryption of a value fails."""

_KEY_DIR = Path.home() / ".argus"
_KEY_FILE = _KEY_DIR / ".key"


def _ensure_key() -> bytes:
    """Load the machine-local key, generating it if necessary."""
    if not _KEY_DIR.exists():
        _KEY_DIR.mkdir(parents=True, exist_ok=True)
        _KEY_DIR.chmod(0o700)

    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
        # Validate key format (44 base64-encoded bytes)
        if len(key) != 44:
            logger.warning("Invalid key file at %s — regenerating", _KEY_FILE)
            key = Fernet.generate_key()
            _KEY_FILE.write_bytes(key)
            _KEY_FILE.chmod(0o600)
        return key

    # Generate a new key
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    _KEY_FILE.chmod(0o600)
    logger.info("Generated new encryption key at %s", _KEY_FILE)
    return key


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns a base64-encoded ciphertext string."""
    if not plaintext:
        return ""
    key = _ensure_key()
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns the original plaintext."""
    if not ciphertext:
        return ""
    try:
        key = _ensure_key()
        f = Fernet(key)
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception) as e:
        logger.warning("Failed to decrypt value: %s", e)
        # Backward compat: previously returned ciphertext as plaintext;
        # now raises so callers handle the error explicitly.
        raise DecryptionError(f"Failed to decrypt value: {e}") from e

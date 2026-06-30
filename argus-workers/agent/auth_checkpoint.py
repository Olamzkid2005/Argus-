"""
AuthContext checkpoint persistence — survives Celery worker restarts.

After register() or login() succeeds, the AuthContext is serialized and
stored in the agent_decision_log table with action_id='auth_context'.
On worker retry, the checkpoint is loaded and the session is re-established
via login() with the stored credentials.
"""

from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet

from agent.auth_context import AuthContext

logger = logging.getLogger(__name__)

# Checkpoint action_id used to identify auth context entries
AUTH_CHECKPOINT_ACTION_ID = "auth_context"


def _get_fernet() -> Fernet:
    """Get a Fernet cipher from the AUTH_CHECKPOINT_KEY env var.

    The key MUST be set and must be a valid Fernet key (44 URL-safe base64 chars).
    At worker startup, this is checked so the failure is loud and early (C-v4-02).

    Returns:
        A ``cryptography.fernet.Fernet`` instance.

    Raises:
        RuntimeError: If ``AUTH_CHECKPOINT_KEY`` is missing or invalid.
    """
    import os

    enc_key = os.environ.get("AUTH_CHECKPOINT_KEY")
    if not enc_key:
        raise RuntimeError(
            "AUTH_CHECKPOINT_KEY environment variable is required for auth checkpoint encryption. "
            "Auth checkpoints contain session tokens (cookies, Bearer tokens, CSRF tokens) "
            "that MUST be encrypted at rest. Set AUTH_CHECKPOINT_KEY to a valid Fernet key "
            "(generate one with: python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\")."
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(enc_key.encode())
    except Exception as e:
        raise RuntimeError(
            f"Invalid AUTH_CHECKPOINT_KEY: {e}. "
            "Generate a valid Fernet key with: python3 -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\""
        ) from e


def _encrypt_payload(data: dict) -> str:
    """Serialize and encrypt a checkpoint payload.

    The entire dict is serialized to JSON and encrypted with AES-256
    via Fernet (authenticated encryption). Only the encrypted blob is
    stored in the database.

    Args:
        data: The dict to encrypt.

    Returns:
        Encrypted base64-encoded string suitable for DB storage.
    """
    cipher = _get_fernet()
    payload_bytes = json.dumps(data, default=str).encode("utf-8")
    return cipher.encrypt(payload_bytes).decode()


def _decrypt_payload(encrypted: str) -> dict:
    """Decrypt a checkpoint payload that was encrypted with ``_encrypt_payload``.

    Args:
        encrypted: The encrypted base64-encoded blob from the database.

    Returns:
        The decrypted dict.

    Raises:
        ValueError: If the blob cannot be decrypted (wrong key or corrupted).
    """
    cipher = _get_fernet()
    try:
        payload_bytes = cipher.decrypt(encrypted.encode())
    except Exception as e:
        raise ValueError(
            f"Failed to decrypt auth checkpoint: {e}. "
            "The AUTH_CHECKPOINT_KEY may have changed or the data is corrupted."
        ) from e
    return json.loads(payload_bytes.decode("utf-8"))


def save_auth_checkpoint(engagement_id: str, ctx: AuthContext) -> bool:
    """Persist the AuthContext to a checkpoint.

    The entire serializable state (email, password, cookie_string,
    authorization tokens, CSRF token, etc.) is encrypted with
    AES-256-GCM via Fernet before storage. The live
    ``requests.Session`` is excluded (cannot be serialized).

    Requires ``AUTH_CHECKPOINT_KEY`` to be set. Fails loudly if
    missing — credentials and session tokens must never be stored
    in plaintext (C-v4-02).

    Args:
        engagement_id: The engagement UUID.
        ctx: The AuthContext to persist.

    Returns:
        True if saved successfully.
    """
    if not ctx or not ctx.email:
        logger.debug("Auth checkpoint: nothing to save (no credentials)")
        return False

    data = ctx.to_dict()
    data["_checkpoint_type"] = "auth_context"

    # Encrypt the entire payload — not just the password field.
    # cookie_string, authorization, and csrf_token are also highly
    # sensitive and could allow session hijacking (C-v4-02).
    try:
        encrypted_blob = _encrypt_payload(data)
    except Exception as exc:
        logger.error(
            "Failed to encrypt auth checkpoint for engagement %s: %s",
            engagement_id,
            exc,
        )
        return False

    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_decision_log
                    (engagement_id, action_id, selected_tool, arguments,
                     execution_success, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    engagement_id,
                    AUTH_CHECKPOINT_ACTION_ID,
                    "auth_context",
                    encrypted_blob,
                    True,
                ),
            )
        logger.info(
            "Auth checkpoint saved for engagement %s (email=%s)",
            engagement_id,
            ctx.email,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to save auth checkpoint: %s", exc)
        return False


def load_auth_checkpoint(engagement_id: str) -> AuthContext | None:
    """Load the most recent AuthContext checkpoint for an engagement.

    The entire stored payload is encrypted with Fernet; on load it
    is decrypted and deserialized. The resulting AuthContext will
    have ``session=None`` — the caller must re-establish the session
    via login() with the stored email/password.

    Args:
        engagement_id: The engagement UUID.

    Returns:
        AuthContext with stored credentials, or None if not found.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                """
                SELECT arguments FROM agent_decision_log
                WHERE engagement_id = %s
                  AND action_id = %s
                  AND execution_success = true
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (engagement_id, AUTH_CHECKPOINT_ACTION_ID),
            )
            row = cursor.fetchone()
            if not row:
                logger.debug("Auth checkpoint: not found for %s", engagement_id)
                return None

            encrypted_blob = row[0]
            if not encrypted_blob:
                return None

            # Decrypt the entire payload
            data = _decrypt_payload(encrypted_blob)

            if data.get("_checkpoint_type") != "auth_context":
                return None

            ctx = AuthContext.from_dict(data)
            logger.info(
                "Auth checkpoint loaded for engagement %s (email=%s)",
                engagement_id,
                ctx.email,
            )
            return ctx
    except Exception as exc:
        logger.warning("Failed to load auth checkpoint: %s", exc)
        return None


def clear_auth_checkpoint(engagement_id: str) -> bool:
    """Remove all auth context checkpoints for an engagement.

    Called when the engagement completes or is cancelled.

    Args:
        engagement_id: The engagement UUID.

    Returns:
        True if cleared successfully.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM agent_decision_log
                WHERE engagement_id = %s
                  AND action_id = %s
                """,
                (engagement_id, AUTH_CHECKPOINT_ACTION_ID),
            )
        logger.debug("Auth checkpoint cleared for engagement %s", engagement_id)
        return True
    except Exception as exc:
        logger.warning("Failed to clear auth checkpoint: %s", exc)
        return False

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
from typing import Any

from agent.auth_context import AuthContext

logger = logging.getLogger(__name__)

# Checkpoint action_id used to identify auth context entries
AUTH_CHECKPOINT_ACTION_ID = "auth_context"


def save_auth_checkpoint(engagement_id: str, ctx: AuthContext) -> bool:
    """Persist the AuthContext to a checkpoint.

    Only the serializable fields (email, password, cookie_string, etc.)
    are stored. The live ``requests.Session`` is excluded.

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

    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_decision_log
                    (engagement_id, action_id, selected_tool, arguments,
                     execution_success, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    engagement_id,
                    AUTH_CHECKPOINT_ACTION_ID,
                    "auth_context",
                    json.dumps(data),
                    True,
                ),
            )
        logger.info(
            "Auth checkpoint saved for engagement %s (email=%s)",
            engagement_id, ctx.email,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to save auth checkpoint: %s", exc)
        return False


def load_auth_checkpoint(engagement_id: str) -> AuthContext | None:
    """Load the most recent AuthContext checkpoint for an engagement.

    The returned AuthContext will have ``session=None`` — the caller must
    re-establish the session via login() with the stored email/password.

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

            data = row[0]
            if isinstance(data, str):
                data = json.loads(data)

            if data.get("_checkpoint_type") != "auth_context":
                return None

            ctx = AuthContext.from_dict(data)
            logger.info(
                "Auth checkpoint loaded for engagement %s (email=%s)",
                engagement_id, ctx.email,
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

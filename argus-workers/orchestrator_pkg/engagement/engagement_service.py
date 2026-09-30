"""EngagementService — DB queries for engagement state and configuration.

Extracted from Orchestrator to reduce orchestrator.py's scope.
All methods are @staticmethod taking ``engagement_id`` as the first parameter.
"""

from __future__ import annotations

import logging

from config.constants import HARD_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class EngagementService:
    """Static service for engagement-level DB queries and state checks.

    Every method is a pure function of ``engagement_id`` with no
    dependency on Orchestrator instance state.
    """

    @staticmethod
    def load_priority_vuln_classes(engagement_id: str) -> list[str]:
        """Load priority_vuln_classes from the engagement record."""
        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT priority_vuln_classes FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return list(row[0])
                return []
        except Exception as e:
            from database.connection import log_db_skip

            log_db_skip(
                logger, f"Failed to load priority_vuln_classes for {engagement_id}", e
            )
            return []

    @staticmethod
    def get_scan_state(engagement_id: str) -> str:
        """Return the current status of the engagement."""
        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                return row[0] if row else "recon"
        except (ValueError, OSError, KeyError) as e:
            logger.warning(
                "State check failed for engagement %s: %s — defaulting to 'failed'",
                engagement_id,
                e,
            )
            return "failed"

    @staticmethod
    def load_authorized_scope(engagement_id: str) -> dict | None:
        """Load the authorized scope from the engagement record.

        The scope is stored inside the ``metadata`` JSONB column as
        ``metadata->>'authorized_scope'`` (a JSON string of the form
        ``{"domains": [...], "ipRanges": [...]}``).

        Returns the parsed scope dict or ``None`` if the engagement
        has no explicit scope configured.
        """
        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT metadata->>'authorized_scope' FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    import json

                    scope_str = row[0]
                    if isinstance(scope_str, str):
                        return json.loads(scope_str)
                    return dict(scope_str)
                return None
        except Exception as e:
            from database.connection import log_db_skip

            log_db_skip(logger, f"Failed to load authorized_scope for {engagement_id}", e)
            return None

    @staticmethod
    def store_scope_config(engagement_id: str, scope_config: dict, repo=None) -> None:
        """Persist scope config to the engagement record.

        Stores the scope payload dict as ``metadata->'scope_config'`` in the
        engagements JSONB column. This is a separate key from the legacy
        ``metadata->'authorized_scope'`` (which stores ``domains``/``ipRanges``
        for the ScopeValidator agent path).

        The stored format matches the job payload::

            {"mode": "allowlist", "allowed_targets": [...], "blocked_targets": [...]}

        Once persisted, ``load_scope_config()`` can retrieve it across worker
        restarts and phase boundaries (recon → scan).

        Args:
            engagement_id: Engagement UUID
            scope_config: Scope dict from the job payload
            repo: Optional engagement repository. The local/SQLite path passes the
                repo it is already using, so the scope lands in the engagement
                record that run reads (its ``metadata`` column). Without a repo
                the Postgres JSONB statement below is used, which is how the
                Docker path persists — and which fails wherever that column is
                absent, which is why the fallback exists.
        """
        if not scope_config or not isinstance(scope_config, dict):
            return
        import json

        if repo is not None:
            try:
                metadata = (repo.find_by_id(engagement_id) or {}).get("metadata") or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                metadata["scope_config"] = scope_config
                repo.update_by_id(engagement_id, {"metadata": metadata})
                logger.info(
                    "Scope config persisted to the engagement record (local backend): "
                    "mode=%s",
                    scope_config.get("mode", "unknown"),
                )
            except Exception as e:
                from database.connection import log_db_skip

                log_db_skip(
                    logger,
                    f"Failed to persist scope config for {engagement_id}",
                    e,
                )
            return

        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE engagements
                    SET metadata = jsonb_set(
                        COALESCE(metadata, '{}'::jsonb),
                        '{scope_config}',
                        %s::jsonb
                    )
                    WHERE id = %s
                    """,
                    (json.dumps(scope_config), engagement_id),
                )
                logger.info(
                    "Scope config persisted for engagement %s: mode=%s",
                    engagement_id,
                    scope_config.get("mode", "unknown"),
                )
        except Exception as e:
            from database.connection import log_db_skip

            log_db_skip(logger, f"Failed to persist scope config for {engagement_id}", e)

    @staticmethod
    def load_scope_config(engagement_id: str, repo=None) -> dict | None:
        """Load the scope config from the engagement record.

        Reads ``metadata->'scope_config'`` from the engagements JSONB column.
        This is the scope payload format (``mode``/``allowed_targets``/``blocked_targets``),
        distinct from the legacy ``authorized_scope`` format (``domains``/``ipRanges``).

        Args:
            engagement_id: Engagement UUID
            repo: Optional engagement repository (see ``store_scope_config``); the
                local/SQLite path reads back from the repo it persisted into.

        Returns:
            The parsed scope dict or ``None`` if no scope config was stored.
        """
        import json

        if repo is not None:
            try:
                stored = ((repo.find_by_id(engagement_id) or {}).get("metadata") or {}).get(
                    "scope_config"
                )
                if isinstance(stored, str):
                    stored = json.loads(stored)
                return dict(stored) if isinstance(stored, dict) else None
            except Exception as e:
                from database.connection import log_db_skip

                log_db_skip(
                    logger, f"Failed to load scope config for {engagement_id}", e
                )
                return None

        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT metadata->'scope_config' FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    raw = row[0]
                    if isinstance(raw, str):
                        return json.loads(raw)
                    if isinstance(raw, dict):
                        return dict(raw)
                return None
        except Exception as e:
            from database.connection import log_db_skip

            log_db_skip(logger, f"Failed to load scope config for {engagement_id}", e)
            return None

    @staticmethod
    def log_timeout_event(engagement_id: str, elapsed_seconds: float) -> None:
        """Log a hard timeout event for the engagement."""
        logger.warning(
            "Engagement %s exceeded hard timeout. Elapsed: %.2fs, Limit: %ds",
            engagement_id,
            elapsed_seconds,
            HARD_TIMEOUT_SECONDS,
        )

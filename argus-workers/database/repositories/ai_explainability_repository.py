"""
Repository for AI explainability data.

Uses standard psycopg2 cursor pattern (compatible with the rest of the codebase).

Transaction safety: This repository does NOT call commit() or rollback() on
shared connections to avoid interfering with caller-managed transactions.
Instead, it manages its own isolated connection from the connection pool.
H-v3-21.
"""

import json
import logging

from database.connection import get_db

logger = logging.getLogger(__name__)


class AIExplainabilityRepository:
    """Repository for managing AI explanations and traces.

    Manages its own isolated database connection (not a shared one) so that
    commit() and rollback() calls inside this repository do not interfere
    with caller transactions (H-v3-21).
    """

    def __init__(self, db_connection=None):
        """
        Initialize repository.

        Args:
            db_connection: Deprecated. If provided, a warning is logged but
                           the repository uses its own isolated connection.
                           Pass None to use the connection pool.
        """
        self._db = None
        self._pool = None
        if db_connection is not None:
            logger.warning(
                "AIExplainabilityRepository received a shared connection — "
                "using isolated connection from pool instead to avoid "
                "transaction interference (H-v3-21). The passed connection "
                "will be ignored."
            )

    @property
    def db(self):
        """Get an isolated database connection (lazy, per-instance)."""
        if self._db is None or self._db.closed:
            self._db = get_db().get_connection()
        return self._db

    def close(self):
        """Return the connection to the pool."""
        if self._db is not None and not self._db.closed:
            get_db().release_connection(self._db)
            self._db = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            logger.warning(
                "Failed to close AI explainability repository connection during shutdown",
                exc_info=True,
            )

    def create_explanation(
        self, cluster_id: str, explanation: str, model_version: str, token_count: int
    ) -> dict | None:
        query = """
            INSERT INTO ai_explanations (
                cluster_id, explanation, model_version, token_count, created_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id, cluster_id, explanation, model_version, token_count, created_at
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    query, (cluster_id, explanation, model_version, token_count)
                )
                result = cursor.fetchone()
                self.db.commit()
                return (
                    dict(
                        zip(
                            [desc[0] for desc in cursor.description],
                            result,
                            strict=False,
                        )
                    )
                    if result
                    else None
                )
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create AI explanation: %s", e)
            raise

    def create_trace(self, cluster_id: str, trace_data: dict) -> dict | None:
        query = """
            INSERT INTO ai_explainability_traces (
                cluster_id, trace_data, created_at
            )
            VALUES (%s, %s, NOW())
            RETURNING id, cluster_id, trace_data, created_at
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(query, (cluster_id, json.dumps(trace_data)))
                result = cursor.fetchone()
                self.db.commit()
                return (
                    dict(
                        zip(
                            [desc[0] for desc in cursor.description],
                            result,
                            strict=False,
                        )
                    )
                    if result
                    else None
                )
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create explainability trace: %s", e)
            raise

    def get_explanation(self, cluster_id: str) -> dict | None:
        query = """
            SELECT id, cluster_id, explanation, model_version, token_count, created_at
            FROM ai_explanations
            WHERE cluster_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(query, (cluster_id,))
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, row, strict=False))
                return None
        except Exception as e:
            logger.error("Failed to get AI explanation: %s", e)
            raise

    def get_trace(self, cluster_id: str) -> dict | None:
        query = """
            SELECT id, cluster_id, trace_data, created_at
            FROM ai_explainability_traces
            WHERE cluster_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(query, (cluster_id,))
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    record = dict(zip(columns, row, strict=False))
                    if isinstance(record.get("trace_data"), str):
                        record["trace_data"] = json.loads(record["trace_data"])
                    return record
                return None
        except Exception as e:
            logger.error("Failed to get AI explainability trace: %s", e)
            raise

"""
Repository for AI explainability data.

Uses standard psycopg2 cursor pattern (compatible with the rest of the codebase).
"""

import json
import logging

logger = logging.getLogger(__name__)


class AIExplainabilityRepository:
    """Repository for managing AI explanations and traces."""

    def __init__(self, db_connection):
        """
        Initialize repository.

        Args:
            db_connection: psycopg2 connection (not asyncpg)
        """
        self.db = db_connection

    def create_explanation(
        self,
        cluster_id: str,
        explanation: str,
        model_version: str,
        token_count: int
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
                cursor.execute(query, (cluster_id, explanation, model_version, token_count))
                result = cursor.fetchone()
                self.db.commit()
                return dict(zip([desc[0] for desc in cursor.description], result, strict=False)) if result else None
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create AI explanation: %s", e)
            raise

    def create_trace(
        self,
        cluster_id: str,
        trace_data: dict
    ) -> dict | None:
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
                return dict(zip([desc[0] for desc in cursor.description], result, strict=False)) if result else None
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

"""
Repository for AI explainability data.
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
            db_connection: Database connection
        """
        self.db = db_connection

    def create_explanation(
        self,
        cluster_id: str,
        explanation: str,
        model_version: str,
        token_count: int
    ) -> dict:
        """
        Create AI explanation record.

        Args:
            cluster_id: Vulnerability cluster ID
            explanation: Generated explanation text
            model_version: LLM model version used
            token_count: Approximate token count

        Returns:
            Created explanation record
        """
        query = """
            INSERT INTO ai_explanations (
                cluster_id,
                explanation,
                model_version,
                token_count,
                created_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id, cluster_id, explanation, model_version, token_count, created_at
        """

        try:
            result = self.db.fetchrow(
                query,
                cluster_id,
                explanation,
                model_version,
                token_count
            )

            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to create AI explanation: {e}")
            raise

    def create_trace(
        self,
        cluster_id: str,
        trace_data: dict
    ) -> dict:
        """
        Create explainability trace record.

        Args:
            cluster_id: Vulnerability cluster ID
            trace_data: Trace data including input/output fields

        Returns:
            Created trace record
        """
        query = """
            INSERT INTO ai_explainability_traces (
                cluster_id,
                trace_data,
                created_at
            )
            VALUES (%s, %s, NOW())
            RETURNING id, cluster_id, trace_data, created_at
        """

        try:
            result = self.db.fetchrow(
                query,
                cluster_id,
                json.dumps(trace_data)
            )

            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to create explainability trace: {e}")
            raise

    def get_explanation(self, cluster_id: str) -> dict | None:
        """
        Get AI explanation for cluster.

        Args:
            cluster_id: Vulnerability cluster ID

        Returns:
            Explanation record or None
        """
        query = """
            SELECT id, cluster_id, explanation, model_version, token_count, created_at
            FROM ai_explanations
            WHERE cluster_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = self.db.fetchrow(query, cluster_id)
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to get AI explanation: {e}")
            raise

    def get_trace(self, cluster_id: str) -> dict | None:
        """
        Get explainability trace for cluster.

        Args:
            cluster_id: Vulnerability cluster ID

        Returns:
            Trace record or None
        """
        query = """
            SELECT id, cluster_id, trace_data, created_at
            FROM ai_explainability_traces
            WHERE cluster_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = self.db.fetchrow(query, cluster_id)
            if result:
                record = dict(result)
                # Parse JSON trace_data
                if isinstance(record['trace_data'], str):
                    record['trace_data'] = json.loads(record['trace_data'])
                return record
            return None
        except Exception as e:
            logger.error(f"Failed to get AI explainability trace: {e}")
            raise

    async def get_explanation(self, cluster_id: str) -> dict | None:
        """
        Get AI explanation for cluster.

        Args:
            cluster_id: Vulnerability cluster ID

        Returns:
            Explanation record or None
        """
        query = """
            SELECT id, cluster_id, explanation, model_version, token_count, created_at
            FROM ai_explanations
            WHERE cluster_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = await self.db.fetchrow(query, cluster_id)
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to get AI explanation: {e}")
            raise

    async def get_trace(self, cluster_id: str) -> dict | None:
        """
        Get explainability trace for cluster.

        Args:
            cluster_id: Vulnerability cluster ID

        Returns:
            Trace record or None
        """
        query = """
            SELECT id, cluster_id, trace_data, created_at
            FROM ai_explainability_traces
            WHERE cluster_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = await self.db.fetchrow(query, cluster_id)
            if result:
                record = dict(result)
                # Parse JSON trace_data
                if isinstance(record['trace_data'], str):
                    record['trace_data'] = json.loads(record['trace_data'])
                return record
            return None
        except Exception as e:
            logger.error(f"Failed to get explainability trace: {e}")
            raise

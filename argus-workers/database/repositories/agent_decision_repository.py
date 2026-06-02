"""
Agent Decision Repository - Persists LLM agent decisions for auditability.

Every LLM tool selection is logged to the agent_decisions table.
This is the data source for debugging bad agent choices and
for the cost guard to track cumulative spend.
"""
import json
import logging

from config.constants import LLM_AGENT_COST_PER_1K_INPUT, LLM_AGENT_COST_PER_1K_OUTPUT
from database.connection import db_cursor

logger = logging.getLogger(__name__)


class AgentDecisionRepository:
    """
    Repository for the agent_decisions table.

    Logs every LLM tool selection decision, including fallback events.
    Provides queries for cost tracking and decision history.
    """

    def __init__(self, db_conn: str | None = None):
        """
        Args:
            db_conn: Database connection string. Defaults to DATABASE_URL env var.
        """
        import os
        self.db_conn = db_conn or os.getenv("DATABASE_URL")

    def log_decision(
        self,
        engagement_id: str,
        phase: str,
        iteration: int,
        tool_selected: str,
        arguments: dict,
        reasoning: str = "",
        was_fallback: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> str | None:
        """
        Insert one row into agent_decisions.

        Args:
            engagement_id: Engagement UUID
            phase: 'scan' or 'recon'
            iteration: Iteration number in the agent loop
            tool_selected: Name of the tool selected
            arguments: Tool arguments dict
            reasoning: LLM's reasoning for selecting this tool
            was_fallback: True if deterministic fallback ran instead of LLM
            input_tokens: LLM input token count (if LLM was used)
            output_tokens: LLM output token count (if LLM was used)

        Returns:
            Decision ID string, or None on failure
        """
        cost = self._estimate_cost(input_tokens, output_tokens)

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_decisions
                        (engagement_id, phase, iteration, tool_selected,
                         arguments, reasoning, was_fallback,
                         input_tokens, output_tokens, cost_usd)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        engagement_id,
                        phase,
                        iteration,
                        tool_selected,
                        json.dumps(arguments),
                        reasoning,
                        was_fallback,
                        input_tokens,
                        output_tokens,
                        cost,
                    ),
                )
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except Exception as e:
            logger.warning(f"Failed to log agent decision: {e}")
            return None

    def get_decisions(self, engagement_id: str) -> list[dict]:
        """
        Fetch all decisions for an engagement, ordered by created_at.

        Args:
            engagement_id: Engagement UUID

        Returns:
            List of decision dicts
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, engagement_id, phase, iteration, tool_selected,
                           arguments, reasoning, was_fallback,
                           input_tokens, output_tokens, cost_usd, created_at
                    FROM agent_decisions
                    WHERE engagement_id = %s
                    ORDER BY created_at ASC
                    """,
                    (engagement_id,),
                )
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Failed to get decisions: {e}")
            return []

    def get_total_cost(self, engagement_id: str) -> float:
        """
        Sum cost_usd for all decisions in this engagement.

        Args:
            engagement_id: Engagement UUID

        Returns:
            Total cost in USD
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(cost_usd), 0) as total_cost
                    FROM agent_decisions
                    WHERE engagement_id = %s
                    """,
                    (engagement_id,),
                )
                row = cursor.fetchone()
                return float(row[0]) if row else 0.0
        except Exception as e:
            logger.warning(f"Failed to get total cost: {e}")
            return 0.0

    def get_stats_since(self, since_hours: int = 24) -> dict:
        """
        Get aggregate agent decision stats for system health.

        Args:
            since_hours: Lookback window in hours

        Returns:
            Dict with total_decisions, total_cost_usd, fallback_count, llm_count
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) as total_decisions,
                        COALESCE(SUM(cost_usd), 0) as total_cost_usd,
                        COALESCE(SUM(CASE WHEN was_fallback THEN 1 ELSE 0 END), 0) as fallback_count,
                        COALESCE(SUM(CASE WHEN NOT was_fallback THEN 1 ELSE 0 END), 0) as llm_count
                    FROM agent_decisions
                    WHERE created_at > NOW() - INTERVAL '%s hours'
                    """,
                    (since_hours,),
                )
                columns = [desc[0] for desc in cursor.description]
                row = cursor.fetchone()
                return dict(zip(columns, row, strict=False)) if row else {
                    "total_decisions": 0,
                    "total_cost_usd": 0.0,
                    "fallback_count": 0,
                    "llm_count": 0,
                }
        except Exception as e:
            logger.warning(f"Failed to get agent stats: {e}")
            return {
                "total_decisions": 0,
                "total_cost_usd": 0.0,
                "fallback_count": 0,
                "llm_count": 0,
            }

    def get_recent_decisions(self, limit: int = 10) -> list[dict]:
        """
        Get most recent decisions across all engagements.

        Args:
            limit: Number of decisions to return

        Returns:
            List of recent decision dicts
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, engagement_id, phase, iteration, tool_selected,
                           arguments, reasoning, was_fallback,
                           input_tokens, output_tokens, cost_usd, created_at
                    FROM agent_decisions
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Failed to get recent decisions: {e}")
            return []

    def _estimate_cost(self, input_tokens: int | None, output_tokens: int | None) -> float:
        """Estimate cost based on token counts."""
        if not input_tokens and not output_tokens:
            return 0.0
        inp = input_tokens or 0
        out = output_tokens or 0
        return (inp / 1000 * LLM_AGENT_COST_PER_1K_INPUT) + (out / 1000 * LLM_AGENT_COST_PER_1K_OUTPUT)

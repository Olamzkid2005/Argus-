"""
Repository for tool_accuracy table — per-org, per-tool false-positive rate tracking.
Thread-safe: each method acquires its own connection from the pool.

Part of the Self-Calibrating Confidence feature (Steps 1-3).
"""

import contextlib
import logging

logger = logging.getLogger(__name__)


class ToolAccuracyRepository:
    """Per-org, per-tool false-positive rate tracking.

    Records analyst verdicts and atomically recalculates per-tool FP rates
    using a Bayesian prior: (fp_count + 0.5) / (total + 1).
    This prevents degenerate rates (0.0 or 1.0) when data is sparse.
    """

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string

    # ── Record a verdict ────────────────────────────────────────────

    def record_verdict(
        self,
        org_id: str,
        source_tool: str,
        is_true_positive: bool,
    ) -> bool:
        """Record a single analyst verdict and atomically recalculate fp_rate.

        Uses PostgreSQL upsert (ON CONFLICT DO UPDATE) so concurrent calls
        are serialized at the row level. Never raises on failure — returns False.

        Args:
            org_id: Organization ID
            source_tool: Tool name (e.g. 'nuclei', 'sqlmap')
            is_true_positive: True if the finding was a real vulnerability

        Returns:
            True if the verdict was recorded successfully
        """
        from database.connection import connect

        if not org_id or not source_tool:
            return False

        conn = None
        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tool_accuracy
                    (org_id, source_tool, total_verdicts,
                     true_positives, false_positives, fp_rate)
                VALUES
                    (%s, %s, 1,
                     CASE WHEN %s THEN 1 ELSE 0 END,
                     CASE WHEN %s THEN 0 ELSE 1 END,
                     -- Bayesian prior: (fp + 0.5) / (total + 1)
                     CASE WHEN %s THEN 0.5 / 2.0 ELSE 1.5 / 2.0 END)
                ON CONFLICT (org_id, source_tool) DO UPDATE SET
                    total_verdicts  = tool_accuracy.total_verdicts + 1,
                    true_positives  = tool_accuracy.true_positives
                                      + EXCLUDED.true_positives,
                    false_positives = tool_accuracy.false_positives
                                      + EXCLUDED.false_positives,
                    -- Weighted fp_rate: (fp_count + 0.5) / (total + 1)
                    fp_rate = (
                        (tool_accuracy.false_positives
                         + EXCLUDED.false_positives + 0.5)::decimal
                        / NULLIF(tool_accuracy.total_verdicts + 1, 0)
                    ),
                    last_updated = NOW()
                """,
                (
                    org_id, source_tool,
                    is_true_positive,   # CASE: true_positives +1
                    is_true_positive,   # CASE: false_positives +0 or +1
                    is_true_positive,   # CASE: initial fp_rate
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("tool_accuracy record_verdict failed: %s", e)
            if conn:
                with contextlib.suppress(Exception):
                    conn.rollback()
            return False
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    # ── Read FP rates ───────────────────────────────────────────────

    def load_fp_rates(self, org_id: str) -> dict[str, float]:
        """Load per-tool fp_rates for an org.

        Returns {source_tool: fp_rate}. Falls back to empty dict on failure.
        Callers should use 0.2 default when a tool has no row.

        Args:
            org_id: Organization ID

        Returns:
            Dict mapping tool names to their learned FP rates
        """
        if not org_id:
            return {}

        from database.connection import connect

        conn = None
        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT source_tool, fp_rate FROM tool_accuracy WHERE org_id = %s",
                (org_id,),
            )
            return {row[0]: float(row[1]) for row in cursor.fetchall()}
        except Exception as e:
            logger.warning("Could not load tool_accuracy: %s", e)
            return {}
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    def get_tool_fp_rate(self, org_id: str, source_tool: str) -> float | None:
        """Get fp_rate for a single tool. Returns None if no row exists.

        Args:
            org_id: Organization ID
            source_tool: Tool name

        Returns:
            FP rate as float, or None if no data for this org+tool combination
        """
        rates = self.load_fp_rates(org_id)
        return rates.get(source_tool)

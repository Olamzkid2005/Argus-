"""
Repository for tool_accuracy table — per-org, per-tool false-positive rate tracking.
Thread-safe: each method acquires its own connection from the pool.

Part of the Self-Calibrating Confidence feature (Steps 1-3).
"""

import logging

from database.connection import db_cursor

logger = logging.getLogger(__name__)


class ToolAccuracyRepository:
    """Per-org, per-tool false-positive rate tracking.

    Records analyst verdicts and atomically recalculates per-tool FP rates
    using a Bayesian prior: (fp_count + 0.5) / (total + 1).
    This prevents degenerate rates (0.0 or 1.0) when data is sparse.
    """

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
        if not org_id or not source_tool:
            return False

        try:
            with db_cursor(commit=True) as cursor:
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
                        / NULLIF(tool_accuracy.total_verdicts + 1 + 1, 0)
                    ),
                    last_updated = NOW()
                """,
                    (
                        org_id,
                        source_tool,
                        is_true_positive,  # CASE: true_positives +1
                        is_true_positive,  # CASE: false_positives +0 or +1
                        is_true_positive,  # CASE: initial fp_rate
                    ),
                )
            return True
        except Exception as e:
            logger.error("tool_accuracy record_verdict failed: %s", e)
            return False

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

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT source_tool, fp_rate FROM tool_accuracy WHERE org_id = %s",
                    (org_id,),
                )
                return {row[0]: float(row[1]) for row in cursor.fetchall()}
        except Exception as e:
            logger.warning("Could not load tool_accuracy: %s", e)
            return {}

    # ── Save ML-estimated FP rates ──────────────────────────────────

    def save_fp_rates(self, org_id: str, tool_fp_rates: dict[str, float]) -> bool:
        """Save aggregated per-tool FP rates from Intelligence Engine estimates.

        Uses INSERT ... ON CONFLICT (upsert) so concurrent calls are serialized
        at the row level. Only updates the fp_rate column — verdict counts from
        record_verdict() remain intact and are not modified.

        The fp_rate acts as a shared signal: ML estimates from the intelligence
        engine set it directly, and analyst verdicts via record_verdict() compute
        a Bayesian prior that overwrites it on each verdict. The last-writer wins.

        Args:
            org_id: Organization ID
            tool_fp_rates: {source_tool: fp_likelihood} mapping from scored findings

        Returns:
            True if all rates were saved successfully
        """
        if not org_id or not tool_fp_rates:
            return False

        try:
            with db_cursor(commit=True) as cursor:
                for source_tool, fp_rate in tool_fp_rates.items():
                    if not source_tool:
                        continue
                    # Clamp fp_rate to [0.0, 1.0] for DB safety
                    clamped_rate = max(0.0, min(1.0, float(fp_rate)))

                    cursor.execute(
                        """
                        INSERT INTO tool_accuracy
                            (org_id, source_tool, total_verdicts,
                             true_positives, false_positives,
                             fp_rate, last_updated)
                        VALUES
                            (%s, %s, 0, 0, 0, %s, NOW())
                        ON CONFLICT (org_id, source_tool) DO UPDATE SET
                            fp_rate = %s,
                            last_updated = NOW()
                        """,
                        (org_id, source_tool, clamped_rate, clamped_rate),
                    )
            return True
        except Exception as e:
            logger.error("tool_accuracy save_fp_rates failed: %s", e)
            return False

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

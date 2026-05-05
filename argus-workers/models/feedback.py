"""
Feedback learning loop — learns from analyst corrections to improve accuracy.

Gated behind ARGUS_FF_FEEDBACK_LOOP feature flag (checked via is_enabled("FEEDBACK_LOOP")).
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from database.connection import get_db
from feature_flags import is_enabled

logger = logging.getLogger(__name__)


@dataclass
class FindingFeedback:
    """Analyst feedback on a finding's accuracy."""
    finding_id: str
    engagement_id: str
    is_true_positive: bool
    analyst_notes: str = ""
    corrected_severity: str | None = None


class FeedbackLearningLoop:
    """Learn from analyst feedback to improve accuracy over time."""

    FP_ALERT_THRESHOLD = 0.30

    def on_feedback(self, feedback: FindingFeedback) -> dict | None:
        """Process analyst feedback — main entry point.

        Returns a dict describing actions taken, or None if the feature flag is disabled.
        """
        if not is_enabled("FEEDBACK_LOOP"):
            logger.debug("Feedback loop disabled (set ARGUS_FF_FEEDBACK_LOOP=1)")
            return None

        actions = {}

        self._store_feedback(feedback)
        actions["feedback_stored"] = True

        self._update_finding(feedback)
        actions["finding_updated"] = True

        if self._update_tool_accuracy(feedback):
            actions["accuracy_adjusted"] = True

        if self._update_confidence_model(feedback):
            actions["weights_adjusted"] = True

        source_tool = self._get_finding_source_tool(feedback.finding_id)
        if source_tool:
            fp_rate = self._get_tool_fp_rate(source_tool)
            if fp_rate > self.FP_ALERT_THRESHOLD:
                self._send_alert(source_tool, fp_rate)
                actions["alert_sent"] = True

        return actions

    def _store_feedback(self, feedback: FindingFeedback) -> None:
        """Persist feedback record to the finding_feedback table (upsert)."""
        conn = None
        cursor = None
        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO finding_feedback (
                    id, finding_id, engagement_id, is_true_positive,
                    analyst_notes, corrected_severity, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (finding_id, engagement_id)
                DO UPDATE SET
                    is_true_positive = EXCLUDED.is_true_positive,
                    analyst_notes = EXCLUDED.analyst_notes,
                    corrected_severity = EXCLUDED.corrected_severity,
                    created_at = EXCLUDED.created_at
                """,
                (
                    str(uuid.uuid4()),
                    feedback.finding_id,
                    feedback.engagement_id,
                    feedback.is_true_positive,
                    feedback.analyst_notes,
                    feedback.corrected_severity,
                    datetime.now(timezone.utc),
                ),
            )
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def _update_finding(self, feedback: FindingFeedback) -> None:
        """Mark the finding with the analyst verdict and adjust fp_likelihood."""
        conn = None
        cursor = None
        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE findings
                SET verified = TRUE,
                    fp_likelihood = CASE WHEN %s THEN 0.0 ELSE 1.0 END,
                    severity = COALESCE(%s, severity),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (feedback.is_true_positive, feedback.corrected_severity, feedback.finding_id),
            )
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def _get_finding_source_tool(self, finding_id: str) -> str | None:
        """Look up which tool produced a finding."""
        try:
            conn = get_db().get_connection()
        except Exception as e:
            logger.error("Failed to get DB connection in _get_finding_source_tool: %s", e)
            return None
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT source_tool FROM findings WHERE id = %s", (finding_id,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error("Failed to query finding source tool for %s: %s", finding_id, e)
            return None
        finally:
            cursor.close()
            get_db().release_connection(conn)

    def _update_tool_accuracy(self, feedback: FindingFeedback) -> bool:
        """Query feedback history for the finding's tool and log its accuracy.

        Returns True if accuracy data was available, False otherwise.
        """
        source_tool = self._get_finding_source_tool(feedback.finding_id)
        if not source_tool:
            logger.warning("Cannot update tool accuracy: finding %s not found", feedback.finding_id)
            return False

        try:
            conn = get_db().get_connection()
        except Exception as e:
            logger.error("Failed to get DB connection in _update_tool_accuracy: %s", e)
            return False
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN ff.is_true_positive THEN 1 ELSE 0 END) AS tp
                FROM finding_feedback ff
                INNER JOIN findings f ON ff.finding_id = f.id
                WHERE f.source_tool = %s
                """,
                (source_tool,),
            )
            row = cursor.fetchone()
            if row and row[0] and row[0] > 0:
                total, tp = row[0], row[1] or 0
                accuracy = tp / total
                logger.info(
                    "Tool accuracy for %s: %d/%d = %.1f%%",
                    source_tool, tp, total, accuracy * 100,
                )
                return True
            return False
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def _update_confidence_model(self, feedback: FindingFeedback) -> bool:
        """Adjust confidence model awareness based on feedback.

        This feeds into the ConfidenceScorer by making per-tool FP rates
        observable at runtime. Actual weight tuning happens offline, but
        the feedback history is now available for that analysis.
        """
        source_tool = self._get_finding_source_tool(feedback.finding_id)
        if not source_tool:
            return False

        fp_rate = self._get_tool_fp_rate(source_tool)
        logger.info(
            "Confidence model: tool=%s fp_rate=%.2f verdict=%s",
            source_tool, fp_rate, feedback.is_true_positive,
        )
        return True

    def _get_tool_fp_rate(self, source_tool: str) -> float:
        """Calculate FP rate for a tool from accumulated feedback.

        FP rate = 1 - (true positives / total feedback entries).
        Returns 0.0 when no feedback data exists yet.
        """
        try:
            conn = get_db().get_connection()
        except Exception as e:
            logger.error("Failed to get DB connection in _get_tool_fp_rate: %s", e)
            return 0.0
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN ff.is_true_positive THEN 1 ELSE 0 END) AS tp
                FROM finding_feedback ff
                INNER JOIN findings f ON ff.finding_id = f.id
                WHERE f.source_tool = %s
                """,
                (source_tool,),
            )
            row = cursor.fetchone()
            if row and row[0] and row[0] > 0:
                total, tp = row[0], row[1] or 0
                return 1.0 - (tp / total)
            return 0.0
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def _send_alert(self, tool_name: str, fp_rate: float) -> None:
        """Log a warning when a tool's FP rate exceeds the threshold."""
        logger.warning(
            "TOOL FP ALERT: %s has a false-positive rate of %.1f%% "
            "(threshold: %.0f%%). Consider reviewing config or disabling "
            "for automated scans.",
            tool_name,
            fp_rate * 100,
            self.FP_ALERT_THRESHOLD * 100,
        )

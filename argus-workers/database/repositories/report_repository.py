"""
Report Repository - Persistence for LLM-generated penetration test reports.

Stores structured reports from the LLMReportGenerator in the reports table.
Provides upsert semantics: one report per engagement.
"""
import json
import logging

from database.connection import db_cursor

logger = logging.getLogger(__name__)


class ReportRepository:
    """
    Repository for the reports table.

    Stores and retrieves LLM-generated security reports.
    """

    def __init__(self, db_conn: str | None = None):
        import os
        self.db_conn = db_conn or os.getenv("DATABASE_URL")

    def upsert_report(
        self,
        engagement_id: str,
        report_data: dict,
        generated_by: str = "llm",
        model_used: str = None,
    ) -> str | None:
        """
        Insert or update a report for an engagement.

        Args:
            engagement_id: Engagement UUID
            report_data: Full report dict (must contain executive_summary, risk_level, etc.)
            generated_by: 'llm' or 'template'
            model_used: LLM model name used for generation

        Returns:
            Report ID string, or None on failure
        """
        findings = report_data.get("detailed_findings", [])
        if not findings:
            findings = report_data.get("findings", [])

        total = len(findings)
        critical = sum(1 for f in findings if (f.get("severity", "") or "").upper() == "CRITICAL")
        high = sum(1 for f in findings if (f.get("severity", "") or "").upper() == "HIGH")
        medium = sum(1 for f in findings if (f.get("severity", "") or "").upper() == "MEDIUM")
        low = sum(1 for f in findings if (f.get("severity", "") or "").upper() == "LOW")

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reports
                        (engagement_id, generated_by, executive_summary, full_report_json,
                         risk_level, total_findings, critical_count, high_count,
                         medium_count, low_count, model_used)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (engagement_id)
                    DO UPDATE SET
                        generated_by = EXCLUDED.generated_by,
                        executive_summary = EXCLUDED.executive_summary,
                        full_report_json = EXCLUDED.full_report_json,
                        risk_level = EXCLUDED.risk_level,
                        total_findings = EXCLUDED.total_findings,
                        critical_count = EXCLUDED.critical_count,
                        high_count = EXCLUDED.high_count,
                        medium_count = EXCLUDED.medium_count,
                        low_count = EXCLUDED.low_count,
                        model_used = EXCLUDED.model_used,
                        created_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        engagement_id,
                        generated_by,
                        report_data.get("executive_summary", ""),
                        json.dumps(report_data),
                        report_data.get("risk_level", "medium"),
                        total,
                        critical,
                        high,
                        medium,
                        low,
                        model_used,
                    ),
                )
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except Exception as e:
            logger.warning(f"Failed to upsert report: {e}")
            return None

    def get_report(self, engagement_id: str) -> dict | None:
        """
        Get the report for an engagement.

        Args:
            engagement_id: Engagement UUID

        Returns:
            Report dict or None
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, engagement_id, generated_by, executive_summary,
                           full_report_json, risk_level, total_findings,
                           critical_count, high_count, medium_count, low_count,
                           model_used, created_at
                    FROM reports
                    WHERE engagement_id = %s
                    LIMIT 1
                    """,
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                columns = [desc[0] for desc in cursor.description]
                d = dict(zip(columns, row, strict=False))
                if isinstance(d.get("full_report_json"), str):
                    d["full_report_json"] = json.loads(d["full_report_json"])
                return d
        except Exception as e:
            logger.warning(f"Failed to get report: {e}")
            return None

    def delete_report(self, engagement_id: str) -> bool:
        """Delete the report for an engagement."""
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "DELETE FROM reports WHERE engagement_id = %s",
                    (engagement_id,),
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"Failed to delete report: {e}")
            return False

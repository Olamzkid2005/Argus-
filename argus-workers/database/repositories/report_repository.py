"""
Report Repository - Persistence for LLM-generated penetration test reports.

Stores structured reports from the LLMReportGenerator in the reports table.
Provides upsert semantics: one report per engagement.
"""

import json
import logging

from database.connection import db_cursor

logger = logging.getLogger(__name__)

#: Severities the reports table has a counter column for.
_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def _as_report_dict(report_data: object) -> dict:
    """Coerce the generator's JSON into the dict the reports table expects.

    ``LLMService.chat_json`` is typed ``dict | list``: when the model answers
    with a bare findings array the report still has to persist instead of
    raising ``'list' object has no attribute 'get'``.
    """
    if isinstance(report_data, dict):
        return report_data
    if isinstance(report_data, list):
        return {"findings": report_data}
    if report_data is None:
        return {}
    return {"findings": [report_data]}


def _as_finding_dicts(findings: object) -> list[dict]:
    """Keep the dict entries of a findings field — the LLM also writes prose.

    Non-dict entries are dropped from the derived counts only; the untouched
    report is still stored in ``full_report_json``.
    """
    if findings is None:
        return []
    if isinstance(findings, dict):
        return [findings]
    if isinstance(findings, (list, tuple)):
        return [entry for entry in findings if isinstance(entry, dict)]
    return []


def _count_by_severity(findings: list[dict]) -> dict[str, int]:
    """Count findings per severity, case-insensitively."""
    counts = dict.fromkeys(_SEVERITIES, 0)
    for finding in findings:
        severity = str(finding.get("severity") or "").upper()
        if severity in counts:
            counts[severity] += 1
    return counts


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
        report_data: dict | list,
        generated_by: str = "llm",
        model_used: str = None,
        sbom_json: dict = None,
    ) -> str | None:
        """
        Insert or update a report for an engagement.

        Args:
            engagement_id: Engagement UUID
            report_data: Full report dict (must contain executive_summary, risk_level, etc.)
            generated_by: 'llm' or 'template'
            model_used: LLM model name used for generation
            sbom_json: Optional CycloneDX SBOM JSON dict

        Returns:
            Report ID string, or None on failure
        """
        report_data = _as_report_dict(report_data)
        raw_findings = report_data.get("detailed_findings") or report_data.get(
            "findings"
        )
        findings = _as_finding_dicts(raw_findings)
        if isinstance(raw_findings, (list, tuple)) and len(findings) != len(
            raw_findings
        ):
            logger.warning(
                "Report for %s has %d entries in its findings list that are not "
                "objects; the raw report is still stored, but they are not counted",
                engagement_id,
                len(raw_findings) - len(findings),
            )

        total = len(findings)
        counts = _count_by_severity(findings)
        critical = counts["CRITICAL"]
        high = counts["HIGH"]
        medium = counts["MEDIUM"]
        low = counts["LOW"]

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reports
                        (engagement_id, generated_by, executive_summary, full_report_json,
                         risk_level, total_findings, critical_count, high_count,
                         medium_count, low_count, model_used, sbom_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        sbom_json = EXCLUDED.sbom_json
                    RETURNING id
                    """,
                    (
                        engagement_id,
                        generated_by,
                        # The LLM's JSON is not schema-checked, so coerce the
                        # scalar columns instead of handing psycopg a dict.
                        str(report_data.get("executive_summary") or ""),
                        json.dumps(report_data, default=str),
                        str(report_data.get("risk_level") or "medium"),
                        total,
                        critical,
                        high,
                        medium,
                        low,
                        model_used,
                        json.dumps(sbom_json, default=str) if sbom_json else None,
                    ),
                )
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except Exception as e:
            logger.warning("Failed to upsert report: %s", e)
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
                           full_report_json, sbom_json, risk_level, total_findings,
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
            logger.warning("Failed to get report: %s", e)
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
            logger.warning("Failed to delete report: %s", e)
            return False

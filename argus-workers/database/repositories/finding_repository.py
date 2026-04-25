"""
Finding repository for database operations on vulnerability findings
"""
from typing import Dict, List, Optional
import uuid
from psycopg2.extras import RealDictCursor, Json
from database.repositories.base import BaseRepository


class FindingRepository(BaseRepository):
    """
    Repository for vulnerability findings

    Provides specialized queries for findings data access.
    """

    table_name = "findings"
    id_column = "id"

    def create_finding(
        self,
        engagement_id: str,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float,
        source_tool: str,
        cvss_score: Optional[float] = None,
        owasp_category: Optional[str] = None,
        cwe_id: Optional[str] = None,
        evidence_strength: Optional[str] = None,
        tool_agreement_level: Optional[str] = None,
        fp_likelihood: Optional[float] = None,
    ) -> str:
        """
        Create a new finding in the database.

        Args:
            engagement_id: Engagement ID
            finding_type: Type of finding (SQL_INJECTION, XSS, etc.)
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)
            endpoint: Affected endpoint
            evidence: Evidence dictionary
            confidence: Confidence score (0.0-1.0)
            source_tool: Tool that found the finding
            cvss_score: Optional CVSS score
            owasp_category: Optional OWASP category
            cwe_id: Optional CWE ID
            evidence_strength: Optional evidence strength
            tool_agreement_level: Optional tool agreement level
            fp_likelihood: Optional false positive likelihood

        Returns:
            The ID of the created finding
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        finding_id = str(uuid.uuid4())

        try:
            cursor.execute(
                """
                INSERT INTO findings (
                    id, engagement_id, type, severity, confidence,
                    endpoint, evidence, source_tool, cvss_score,
                    owasp_category, cwe_id, evidence_strength,
                    tool_agreement_level, fp_likelihood, verified, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW()
                )
                """,
                (
                    finding_id,
                    engagement_id,
                    finding_type,
                    severity,
                    confidence,
                    endpoint,
                    Json(evidence),
                    source_tool,
                    cvss_score,
                    owasp_category,
                    cwe_id,
                    evidence_strength,
                    tool_agreement_level,
                    fp_likelihood,
                )
            )
            conn.commit()
            return finding_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def find_high_confidence(
        self,
        engagement_id: str,
        threshold: float = 0.7
    ) -> List[Dict]:
        """
        Find high confidence findings

        Args:
            engagement_id: Engagement ID
            threshold: Confidence threshold (default 0.7)

        Returns:
            List of high confidence findings
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT * FROM findings
                WHERE engagement_id = %s AND confidence >= %s
                ORDER BY confidence DESC
                """,
                (engagement_id, threshold)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
    
    def get_summary_by_engagement(self, engagement_id: str) -> Dict:
        """
        Get summary statistics for findings.
        Uses materialized view if available for better performance.

        Args:
            engagement_id: Engagement ID

        Returns:
            Dictionary with counts by severity
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Try materialized view first for better performance
            cursor.execute(
                """
                SELECT total_findings, critical_count, high_count, medium_count, 
                       low_count, info_count, avg_confidence
                FROM mv_engagement_findings
                WHERE engagement_id = %s
                """,
                (engagement_id,)
            )
            row = cursor.fetchone()
            
            if row:
                summary = {}
                for severity, key in [
                    ("CRITICAL", "critical_count"),
                    ("HIGH", "high_count"),
                    ("MEDIUM", "medium_count"),
                    ("LOW", "low_count"),
                    ("INFO", "info_count"),
                ]:
                    count = row.get(key, 0) or 0
                    if count > 0:
                        summary[severity] = {
                            "count": count,
                            "avg_confidence": float(row.get("avg_confidence") or 0),
                            "avg_cvss": 0,
                        }
                return summary
            
            # Fallback to direct query
            cursor.execute(
                """
                SELECT
                    severity,
                    COUNT(*) as count,
                    AVG(confidence) as avg_confidence,
                    AVG(cvss_score) as avg_cvss
                FROM findings
                WHERE engagement_id = %s
                GROUP BY severity
                """,
                (engagement_id,)
            )
            rows = cursor.fetchall()
            summary = {}
            for row in rows:
                summary[row["severity"]] = {
                    "count": row["count"],
                    "avg_confidence": float(row["avg_confidence"]) if row["avg_confidence"] else 0,
                    "avg_cvss": float(row["avg_cvss"]) if row["avg_cvss"] else 0,
                }
            return summary
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
    
    def find_by_engagement_with_details(self, engagement_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        """
        Find findings with engagement details in a single query.
        Avoids N+1 query problem by using JOINs.

        Args:
            engagement_id: Engagement ID
            limit: Maximum number of records
            offset: Number of records to skip

        Returns:
            List of finding dictionaries with engagement details
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT 
                    f.*,
                    e.target_url as engagement_target,
                    e.status as engagement_status
                FROM findings f
                INNER JOIN engagements e ON f.engagement_id = e.id
                WHERE f.engagement_id = %s
                ORDER BY f.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (engagement_id, limit, offset)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
    
    def update_confidence(self, finding_id: str, confidence: float) -> None:
        """
        Update confidence score for a finding.

        Args:
            finding_id: Finding ID
            confidence: New confidence score (0.0-1.0)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE findings
                SET confidence = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (confidence, finding_id)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def add_llm_evidence(self, finding_id: str, llm_result: dict) -> None:
        """
        Store LLM analysis result and mark finding as LLM-reviewed.

        Args:
            finding_id: Finding ID
            llm_result: Dictionary with LLM analysis (vulnerable, confidence, evidence_quote, model, timestamp)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            from psycopg2.extras import Json
            cursor.execute(
                """
                UPDATE findings
                SET llm_reviewed = TRUE,
                    llm_analysis = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (Json(llm_result), finding_id)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_findings_by_engagement(self, engagement_id: str) -> List[Dict]:
        """
        Get all findings for an engagement.

        Args:
            engagement_id: Engagement ID

        Returns:
            List of finding dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT * FROM findings
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                """,
                (engagement_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def find_unreviewed_low_confidence(
        self,
        engagement_id: str,
        threshold: float = 0.7,
        min_confidence: float = 0.3,
        limit: int = 50
    ) -> List[Dict]:
        """
        Find findings for an engagement that:
        - Have confidence below threshold
        - Have confidence above min_confidence (skip very noisy findings)
        - Haven't been LLM-reviewed yet
        - Have evidence with payload or response data

        Args:
            engagement_id: Engagement ID
            threshold: Upper confidence bound (findings below this)
            min_confidence: Lower confidence bound (findings below this are too noisy)
            limit: Maximum results

        Returns:
            List of finding dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT * FROM findings
                WHERE engagement_id = %s
                  AND confidence >= %s
                  AND confidence < %s
                  AND (llm_reviewed IS NULL OR llm_reviewed = FALSE)
                  AND (evidence->>'payload' IS NOT NULL OR evidence->>'response' IS NOT NULL)
                ORDER BY confidence DESC
                LIMIT %s
                """,
                (engagement_id, min_confidence, threshold, limit)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

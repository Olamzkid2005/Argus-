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

    def find_by_engagement(self, engagement_id: str) -> List[Dict]:
        """
        Find all findings for an engagement

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
            conn.close()
    
    def get_findings_by_engagement(self, engagement_id: str) -> List[Dict]:
        """
        Get all findings for an engagement (alias for find_by_engagement).
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            List of finding dictionaries
        """
        return self.find_by_engagement(engagement_id)

    def find_by_severity(
        self,
        engagement_id: str,
        severity: str
    ) -> List[Dict]:
        """
        Find findings by severity level

        Args:
            engagement_id: Engagement ID
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)

        Returns:
            List of finding dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT * FROM findings
                WHERE engagement_id = %s AND severity = %s
                ORDER BY confidence DESC
                """,
                (engagement_id, severity)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()

    def find_by_type(
        self,
        engagement_id: str,
        finding_type: str
    ) -> List[Dict]:
        """
        Find findings by type

        Args:
            engagement_id: Engagement ID
            finding_type: Finding type (SQL_INJECTION, XSS, etc.)

        Returns:
            List of finding dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT * FROM findings
                WHERE engagement_id = %s AND type = %s
                ORDER BY confidence DESC
                """,
                (engagement_id, finding_type)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()

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
            conn.close()

    def get_summary_by_engagement(self, engagement_id: str) -> Dict:
        """
        Get summary statistics for findings

        Args:
            engagement_id: Engagement ID

        Returns:
            Dictionary with counts by severity
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
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
            conn.close()

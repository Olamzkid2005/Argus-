"""
Finding repository for database operations on vulnerability findings
"""
from typing import Dict, List, Optional
from psycopg2.extras import RealDictCursor
from database.repositories.base import BaseRepository


class FindingRepository(BaseRepository):
    """
    Repository for vulnerability findings

    Provides specialized queries for findings data access.
    """

    table_name = "findings"
    id_column = "id"

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

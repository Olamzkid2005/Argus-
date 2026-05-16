"""
Finding repository for database operations on vulnerability findings
"""
import logging
import uuid

from psycopg2.extras import Json, RealDictCursor

logger = logging.getLogger(__name__)

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
        cvss_score: float | None = None,
        owasp_category: str | None = None,
        cwe_id: str | None = None,
        evidence_strength: str | None = None,
        tool_agreement_level: str | None = None,
        fp_likelihood: float | None = None,
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
            source_tool = source_tool or ""
            # First, check if a legacy row with source_tool IS NULL exists for
            # this (engagement_id, endpoint, type) and update it in-place.
            # This handles the migration from NULL to '' source_tool values.
            cursor.execute(
                """
                UPDATE findings
                SET source_tool = %s,
                    severity = %s,
                    confidence = %s,
                    evidence = %s,
                    cvss_score = %s,
                    owasp_category = %s,
                    cwe_id = %s,
                    evidence_strength = %s,
                    tool_agreement_level = %s,
                    fp_likelihood = %s,
                    updated_at = NOW()
                WHERE engagement_id = %s
                  AND endpoint = %s
                  AND type = %s
                  AND source_tool IS NULL
                RETURNING id
                """,
                (
                    source_tool, severity, confidence, Json(evidence),
                    cvss_score, owasp_category, cwe_id,
                    evidence_strength, tool_agreement_level, fp_likelihood,
                    engagement_id, endpoint, finding_type,
                )
            )
            row = cursor.fetchone()
            if row:
                conn.commit()
                return str(row[0])

            # No legacy row found — do the standard INSERT with ON CONFLICT
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
                ON CONFLICT (engagement_id, endpoint, type, source_tool)
                DO UPDATE SET id = findings.id
                RETURNING id
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
            row = cursor.fetchone()
            if row:
                finding_id = str(row[0])
            else:
                # Fallback: query the finding by conflict key to retrieve ID
                try:
                    cursor.execute(
                        "SELECT id FROM findings WHERE engagement_id = %s AND endpoint = %s AND type = %s AND source_tool = %s",
                        (engagement_id, endpoint, finding_type, source_tool),
                    )
                    fallback_row = cursor.fetchone()
                    if fallback_row:
                        finding_id = str(fallback_row[0])
                        logger.debug("Retrieved finding ID via fallback query for %s", engagement_id)
                    else:
                        logger.warning("Fallback query also returned no row for engagement=%s endpoint=%s type=%s", engagement_id, endpoint, finding_type)
                        return None
                except Exception as fb_err:
                    logger.error("Fallback query failed: %s", fb_err)
                    return None
            conn.commit()
            return finding_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def upsert_secret_finding(
        self,
        engagement_id: str,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float,
        source_tool: str,
        cvss_score: float | None = None,
    ) -> str:
        """
        Insert or update a secret finding.

        Deduplicates by (engagement_id, type, endpoint) fingerprint.
        Uses ON CONFLICT to prevent TOCTOU races between the SELECT and INSERT.
        If the same secret already exists, updates last_seen_at instead of
        creating a duplicate. Prevents unbounded growth on repeated scans.

        Args:
            engagement_id: Engagement ID
            finding_type: Type of finding (COMMITTED_SECRET, EXPOSED_PRIVATE_KEY, etc.)
            severity: Severity level
            endpoint: File path + commit hash or file path
            evidence: Evidence dictionary
            confidence: Confidence score (0.0-1.0)
            source_tool: Tool that found the secret
            cvss_score: Optional CVSS score

        Returns:
            The ID of the created or updated finding
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        source_tool = source_tool or ""

        try:
            # Handle legacy rows with source_tool IS NULL (pre-migration)
            cursor.execute(
                """
                UPDATE findings
                SET last_seen_at = NOW(),
                    severity = %s,
                    confidence = %s,
                    evidence = %s,
                    cvss_score = %s
                WHERE engagement_id = %s
                  AND type = %s
                  AND endpoint = %s
                  AND source_tool IS NULL
                RETURNING id
                """,
                (severity, confidence, Json(evidence), cvss_score,
                 engagement_id, finding_type, endpoint),
            )
            row = cursor.fetchone()
            if row:
                conn.commit()
                return str(row[0])

            cursor.execute(
                """
                INSERT INTO findings (
                    id, engagement_id, type, severity, confidence,
                    endpoint, evidence, source_tool, cvss_score,
                    verified, created_at, last_seen_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    FALSE, NOW(), NOW()
                )
                ON CONFLICT (engagement_id, endpoint, type, source_tool)
                DO UPDATE SET
                    last_seen_at = NOW(),
                    severity = EXCLUDED.severity,
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence,
                    cvss_score = EXCLUDED.cvss_score
                RETURNING id
                """,
                (
                    str(uuid.uuid4()), engagement_id, finding_type, severity,
                    confidence, endpoint, Json(evidence), source_tool, cvss_score,
                )
            )
            row = cursor.fetchone()
            finding_id = str(row[0]) if row else None
            conn.commit()
            return finding_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def find_high_confidence(
        self,
        engagement_id: str,
        threshold: float = 0.7
    ) -> list[dict]:
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
                LIMIT 500
                """,
                (engagement_id, threshold)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_summary_by_engagement(self, engagement_id: str) -> dict:
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

    def find_by_engagement_with_details(self, engagement_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
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
                SET confidence = %s
                WHERE id = %s
                """,
                (float(confidence), finding_id)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
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
            cursor.execute(
                """
                UPDATE findings
                SET llm_reviewed = TRUE,
                    llm_analysis = %s
                WHERE id = %s
                """,
                (Json(llm_result), finding_id)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_findings_by_engagement(
        self, engagement_id: str, limit: int = 100, offset: int = 0,
        severity: str | None = None, finding_type: str | None = None,
    ) -> tuple[list[dict], int]:
        """
        Get findings for an engagement with pagination and optional filters.

        Args:
            engagement_id: Engagement ID
            limit: Maximum number of findings to return
            offset: Number of findings to skip
            severity: Optional severity filter
            finding_type: Optional finding type filter

        Returns:
            Tuple of (list of finding dictionaries, total count)
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            where_clause = "WHERE engagement_id = %s"
            params = [engagement_id]

            if severity:
                where_clause += " AND severity = %s"
                params.append(severity)

            if finding_type:
                where_clause += " AND type = %s"
                params.append(finding_type)

            cursor.execute(
                f"SELECT COUNT(*) AS total FROM findings {where_clause}",
                params,
            )
            total = cursor.fetchone()["total"]

            cursor.execute(
                f"""
                SELECT * FROM findings
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows], total
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
    ) -> list[dict]:
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
                FOR UPDATE SKIP LOCKED
                """,
                (engagement_id, min_confidence, threshold, limit)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

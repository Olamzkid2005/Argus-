"""
Finding repository for database operations on vulnerability findings
"""
import logging
import os
import uuid

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)

MAX_FINDINGS_PER_ENGAGEMENT = int(os.getenv("MAX_FINDINGS_PER_ENGAGEMENT", "50000"))


class FindingCapExceededError(Exception):
    """Raised when the maximum number of findings per engagement is reached."""
    pass


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
        finding_id = str(uuid.uuid4())

        with self.db_operation(commit=True) as (conn, cursor):
            # Soft limit check to prevent unbounded storage growth.
            # TOCTOU is acceptable here — two concurrent inserts may slightly
            # exceed the cap, which is better than holding a FOR UPDATE lock
            # on the engagement row and serializing all inserts.
            cursor.execute(
                "SELECT COUNT(*) FROM findings WHERE engagement_id = %s",
                (engagement_id,)
            )
            count = cursor.fetchone()[0]
            if count >= MAX_FINDINGS_PER_ENGAGEMENT:
                logger.error(
                    "Engagement %s has %d findings (limit %d) — finding cap exceeded",
                    engagement_id, count, MAX_FINDINGS_PER_ENGAGEMENT
                )
                raise FindingCapExceededError(
                    f"Engagement {engagement_id} has {count} findings (limit {MAX_FINDINGS_PER_ENGAGEMENT})"
                )

            source_tool = source_tool or ""
            endpoint = endpoint or ""
            finding_type = finding_type or ""
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
                return str(row[0])

            # No legacy row found — do the standard INSERT with ON CONFLICT
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
            except psycopg2.errors.UniqueViolation:
                # ON CONFLICT clause requires the constraint to exist on the table.
                # If it doesn't, PostgreSQL raises UniqueViolation at query-plan time.
                # Fall back to SELECT-then-UPDATE-else-INSERT approach.
                logger.warning("ON CONFLICT constraint not found — using SELECT-then-INSERT fallback")
                cursor.execute(
                    "SELECT id FROM findings WHERE engagement_id = %s AND endpoint = %s AND type = %s AND source_tool = %s",
                    (engagement_id, endpoint, finding_type, source_tool),
                )
                row = cursor.fetchone()
                if row:
                    finding_id = str(row[0])
                else:
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
                return finding_id
            except psycopg2.Error as on_conflict_err:
                logger.error("ON CONFLICT insert failed: %s", on_conflict_err)
                raise
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
            return finding_id

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
        source_tool = source_tool or ""
        endpoint = endpoint or ""
        finding_type = finding_type or ""

        with self.db_operation(commit=True) as (conn, cursor):
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
            return str(row[0]) if row else None

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
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
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

    def get_summary_by_engagement(self, engagement_id: str) -> dict:
        """
        Get summary statistics for findings.
        Uses materialized view if available for better performance.

        Args:
            engagement_id: Engagement ID

        Returns:
            Dictionary with counts by severity
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
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
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
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

    def update_confidence(self, finding_id: str, confidence: float) -> None:
        """
        Update confidence score for a finding.

        Args:
            finding_id: Finding ID
            confidence: New confidence score (0.0-1.0)
        """
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                """
                UPDATE findings
                SET confidence = %s
                WHERE id = %s
                """,
                (float(confidence), finding_id)
            )

    def add_llm_evidence(self, finding_id: str, llm_result: dict) -> None:
        """
        Store LLM analysis result and mark finding as LLM-reviewed.

        Args:
            finding_id: Finding ID
            llm_result: Dictionary with LLM analysis (vulnerable, confidence, evidence_quote, model, timestamp)
        """
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                """
                UPDATE findings
                SET llm_reviewed = TRUE,
                    llm_analysis = %s
                WHERE id = %s
                """,
                (Json(llm_result), finding_id)
            )

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
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
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
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
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

    def batch_create_or_update_findings(
        self,
        engagement_id: str,
        findings: list[dict],
    ) -> tuple[int, int]:
        """
        Insert or update multiple findings in a single database transaction.

        Each finding dict must have: engagement_id, type, severity, endpoint,
        evidence, source_tool. Optional: confidence, cvss_score, owasp_category,
        cwe_id, evidence_strength, tool_agreement_level, fp_likelihood.

        Uses INSERT ... ON CONFLICT for atomic upserts. The entire batch
        either commits or rolls back — no partial commits.

        Args:
            engagement_id: Engagement UUID
            findings: List of finding dicts

        Returns:
            Tuple of (inserted_count, updated_count)
        """
        if not findings:
            return 0, 0

        inserted_count = 0
        updated_count = 0

        with self.db_operation(commit=True) as (conn, cursor):
            for idx, f in enumerate(findings):
                sp_name = f"finding_sp_{idx}"
                try:
                    # Create a savepoint before each finding so individual
                    # failures can be rolled back without aborting the batch.
                    cursor.execute(f"SAVEPOINT {sp_name}")

                    finding_id = str(uuid.uuid4())
                    _type = f.get("type", "UNKNOWN")
                    _severity = f.get("severity", "INFO")
                    _endpoint = f.get("endpoint", "")
                    _evidence = f.get("evidence", {})
                    _confidence = f.get("confidence", 0.5)
                    _source_tool = f.get("source_tool", "") or ""
                    _cvss = f.get("cvss_score")
                    _owasp = f.get("owasp_category")
                    _cwe = f.get("cwe_id")
                    _ev_strength = f.get("evidence_strength")
                    _tool_agree = f.get("tool_agreement_level")
                    _fp_like = f.get("fp_likelihood")

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
                        DO UPDATE SET
                            severity = EXCLUDED.severity,
                            confidence = EXCLUDED.confidence,
                            evidence = EXCLUDED.evidence,
                            cvss_score = EXCLUDED.cvss_score,
                            owasp_category = EXCLUDED.owasp_category,
                            cwe_id = EXCLUDED.cwe_id,
                            evidence_strength = EXCLUDED.evidence_strength,
                            tool_agreement_level = EXCLUDED.tool_agreement_level,
                            fp_likelihood = EXCLUDED.fp_likelihood,
                            updated_at = NOW()
                        RETURNING id, (xmax = 0) AS is_insert
                        """,
                        (
                            finding_id, engagement_id, _type, _severity,
                            _confidence, _endpoint, Json(_evidence),
                            _source_tool, _cvss, _owasp, _cwe,
                            _ev_strength, _tool_agree, _fp_like,
                        ),
                    )
                    row = cursor.fetchone()
                    if row:
                        if row[1]:
                            inserted_count += 1
                        else:
                            updated_count += 1
                        f["_saved_id"] = str(row[0])
                    else:
                        logger.warning(
                            "batch_create_or_update: no row returned for type=%s endpoint=%s",
                            _type, _endpoint,
                        )

                    # Release the savepoint on success
                    try:
                        cursor.execute(f"RELEASE SAVEPOINT {sp_name}")
                    except psycopg2.Error as sp_err:
                        logger.debug("Failed to release savepoint %s: %s", sp_name, sp_err)
                except psycopg2.errors.UniqueViolation:
                    # Rollback savepoint to clear aborted transaction state
                    try:
                        cursor.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    except psycopg2.Error as sp_err:
                        logger.debug("Failed to rollback savepoint %s: %s", sp_name, sp_err)
                    # ON CONFLICT didn't catch it — fall back to SELECT
                    try:
                        cursor.execute(
                            "SELECT id FROM findings WHERE engagement_id = %s AND endpoint = %s AND type = %s AND source_tool = %s",
                            (engagement_id, _endpoint, _type, _source_tool),
                        )
                        row = cursor.fetchone()
                        if row:
                            f["_saved_id"] = str(row[0])
                            updated_count += 1
                    except Exception as fb_err:
                        logger.debug("Fallback query failed: %s", fb_err)
                except psycopg2.Error as db_err:
                    logger.warning(
                        "batch_create_or_update: DB error for type=%s endpoint=%s: %s — rolling back savepoint, continuing batch",
                        _type, _endpoint, db_err,
                    )
                    # Rollback savepoint to clear aborted transaction state.
                    # Without this, PostgreSQL rejects all subsequent statements
                    # with "current transaction is aborted, commands ignored".
                    try:
                        cursor.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    except Exception as sp_err:
                        logger.warning(
                            "batch_create_or_update: savepoint rollback also failed for %s — aborting batch: %s",
                            _endpoint, sp_err,
                        )
                        raise

        return inserted_count, updated_count

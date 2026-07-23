"""SQLite backend for standalone/local mode.

Provides SQLite-based implementations of the core repository interfaces
(EngagementRepository, FindingRepository) so Argus can run without Postgres.

Usage:
    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    eng_repo = SQLiteEngagementRepo(":memory:")
    finding_repo = SQLiteFindingRepo(":memory:")
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    """Return ISO 8601 timestamp string."""
    return datetime.now(UTC).isoformat()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS engagements (
            id TEXT PRIMARY KEY,
            org_id TEXT,
            target TEXT,
            target_url TEXT,
            status TEXT DEFAULT 'created',
            scan_type TEXT DEFAULT 'url',
            authorization_proof TEXT,
            authorized_scope TEXT,
            created_by TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL,
            type TEXT DEFAULT '',
            severity TEXT DEFAULT 'INFO',
            confidence REAL DEFAULT 0.5,
            endpoint TEXT DEFAULT '',
            evidence TEXT DEFAULT '{}',
            source_tool TEXT DEFAULT '',
            cvss_score REAL,
            owasp_category TEXT,
            cwe_id TEXT,
            evidence_strength TEXT,
            tool_agreement_level TEXT,
            fp_likelihood REAL,
            verified INTEGER DEFAULT 0,
            llm_reviewed INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            last_seen_at TEXT,
            UNIQUE(engagement_id, endpoint, type, source_tool)
        );

        CREATE TABLE IF NOT EXISTS hypotheses (
            id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL,
            description TEXT,
            root_cause_key TEXT,
            source_finding_id TEXT,
            confidence REAL DEFAULT 0.5,
            status TEXT DEFAULT 'UNVERIFIED',
            verification_steps TEXT DEFAULT '[]',
            finding_ids TEXT DEFAULT '[]',
            supporting_finding_ids TEXT DEFAULT '[]',
            refuting_finding_ids TEXT DEFAULT '[]',
            suggested_tools TEXT DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_findings_engagement
            ON findings(engagement_id);
        CREATE INDEX IF NOT EXISTS idx_hypotheses_engagement
            ON hypotheses(engagement_id);
    """)


class SQLiteEngagementRepo:
    """SQLite-backed EngagementRepository for standalone mode.

    Thread-safe via per-operation lock. Uses ``concurrent=False`` SQLite
    mode (one write at a time, which is fine for single-user local use).
    """

    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        with self._lock:
            _ensure_tables(self._conn)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def _to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        # Parse JSON string fields
        for key in ("metadata",):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    def create(self, engagement_data: dict) -> dict:
        with self._lock:
            eng_id = str(uuid.uuid4())
            now = _now()
            metadata = engagement_data.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            target_url = engagement_data.get("target_url") or engagement_data.get("target", "")
            self._conn.execute(
                """INSERT INTO engagements
                   (id, org_id, target, target_url, status, scan_type,
                    authorization_proof, authorized_scope, created_by,
                    metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    eng_id,
                    engagement_data.get("org_id"),
                    target_url,
                    target_url,
                    engagement_data.get("status", "created"),
                    engagement_data.get("scan_type", "url"),
                    engagement_data.get("authorization_proof"),
                    engagement_data.get("authorized_scope"),
                    engagement_data.get("created_by"),
                    json.dumps(metadata),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            cursor = self._conn.execute("SELECT * FROM engagements WHERE id = ?", (eng_id,))
            return self._to_dict(cursor.fetchone()) or {}

    def find_by_id(self, id: str) -> dict | None:
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM engagements WHERE id = ?", (id,))
            return self._to_dict(cursor.fetchone())

    def update_status(self, engagement_id: str, status: str) -> dict | None:
        with self._lock:
            now = _now()
            self._conn.execute(
                "UPDATE engagements SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, engagement_id),
            )
            self._conn.commit()
            cursor = self._conn.execute(
                "SELECT * FROM engagements WHERE id = ?", (engagement_id,)
            )
            return self._to_dict(cursor.fetchone())

    def update_by_id(self, id: str, updates: dict) -> dict | None:
        with self._lock:
            if not updates:
                return self.find_by_id(id)
            now = _now()
            updates["updated_at"] = now
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [id]
            # Serialize dict fields to JSON (iterate over items so k is defined)
            values = [
                json.dumps(v) if isinstance(v, dict) and k != "id" else v
                for k, v in updates.items()
            ] + [id]
            self._conn.execute(
                f"UPDATE engagements SET {set_clause} WHERE id = ?", values
            )
            self._conn.commit()
            cursor = self._conn.execute(
                "SELECT * FROM engagements WHERE id = ?", (id,)
            )
            return self._to_dict(cursor.fetchone())

    def find_by_org(
        self, org_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM engagements WHERE org_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (org_id, limit, offset),
            )
            return [self._to_dict(row) for row in cursor.fetchall()]


class SQLiteFindingRepo:
    """SQLite-backed FindingRepository for standalone mode."""

    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        with self._lock:
            _ensure_tables(self._conn)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def _to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        # Parse JSON string evidence back to dict
        if isinstance(d.get("evidence"), str):
            try:
                d["evidence"] = json.loads(d["evidence"])
            except (json.JSONDecodeError, TypeError):
                pass
        # Convert int booleans back
        for key in ("verified", "llm_reviewed"):
            if key in d:
                d[key] = bool(d[key])
        return d

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
        finding_id = str(uuid.uuid4())
        now = _now()
        with self._lock:
            # Upsert: try update first, then insert
            cursor = self._conn.execute(
                """UPDATE findings SET severity=?, confidence=?, evidence=?,
                   cvss_score=?, owasp_category=?, cwe_id=?, updated_at=?
                   WHERE engagement_id=? AND endpoint=? AND type=? AND source_tool=?
                   RETURNING id""",
                (
                    severity, confidence, json.dumps(evidence) if isinstance(evidence, dict) else evidence,
                    cvss_score, owasp_category, cwe_id, now,
                    engagement_id, endpoint or "", finding_type or "", source_tool or "",
                ),
            )
            row = cursor.fetchone()
            if row:
                return str(row["id"])

            self._conn.execute(
                """INSERT INTO findings
                   (id, engagement_id, type, severity, confidence, endpoint,
                    evidence, source_tool, cvss_score, owasp_category, cwe_id,
                    evidence_strength, tool_agreement_level, fp_likelihood,
                    verified, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    finding_id, engagement_id, finding_type or "", severity,
                    confidence, endpoint or "",
                    json.dumps(evidence) if isinstance(evidence, dict) else evidence,
                    source_tool or "", cvss_score, owasp_category, cwe_id,
                    evidence_strength, tool_agreement_level, fp_likelihood,
                    now, now,
                ),
            )
            self._conn.commit()
            return finding_id

    def batch_create_or_update_findings(
        self, engagement_id: str, findings: list[dict],
    ) -> tuple[int, int]:
        now = _now()
        with self._lock:
            for f in findings:
                f_id = str(uuid.uuid4())
                f_type = f.get("type", "UNKNOWN")
                f_severity = f.get("severity", "INFO")
                f_endpoint = f.get("endpoint", "")
                f_evidence = f.get("evidence", {})
                f_confidence = f.get("confidence", 0.5)
                f_tool = f.get("source_tool", "")
                f_cvss = f.get("cvss_score")

                # Upsert — SQLite doesn't distinguish insert vs update
                # (no xmax equivalent), so we return approximate counts.
                self._conn.execute(
                    """INSERT INTO findings
                       (id, engagement_id, type, severity, confidence, endpoint,
                        evidence, source_tool, cvss_score, verified, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                       ON CONFLICT(engagement_id, endpoint, type, source_tool)
                       DO UPDATE SET
                           severity=excluded.severity,
                           confidence=excluded.confidence,
                           evidence=excluded.evidence,
                           cvss_score=excluded.cvss_score,
                           updated_at=excluded.updated_at""",
                    (
                        f_id, engagement_id, f_type, f_severity, f_confidence,
                        f_endpoint,
                        json.dumps(f_evidence) if isinstance(f_evidence, dict) else f_evidence,
                        f_tool, f_cvss, now, now,
                    ),
                )
            self._conn.commit()
        # Return (0, len(findings)) — exact counts aren't critical for
        # callers (they only check if failures == total for abort decision)
        return 0, len(findings)

    def get_findings_by_engagement(
        self,
        engagement_id: str,
        limit: int = 100,
        offset: int = 0,
        severity: str | None = None,
        finding_type: str | None = None,
    ) -> tuple[list[dict], int]:
        with self._lock:
            where = "WHERE engagement_id = ?"
            params: list[Any] = [engagement_id]
            if severity:
                where += " AND severity = ?"
                params.append(severity)
            if finding_type:
                where += " AND type = ?"
                params.append(finding_type)

            count_row = self._conn.execute(
                f"SELECT COUNT(*) as cnt FROM findings {where}", params
            ).fetchone()
            total = count_row["cnt"] if count_row else 0

            cursor = self._conn.execute(
                f"SELECT * FROM findings {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            return [self._to_dict(row) for row in cursor.fetchall()], total

    def get_summary_by_engagement(self, engagement_id: str) -> dict:
        with self._lock:
            cursor = self._conn.execute(
                """SELECT severity, COUNT(*) as count, AVG(confidence) as avg_confidence
                   FROM findings WHERE engagement_id = ? GROUP BY severity""",
                (engagement_id,),
            )
            summary = {}
            for row in cursor.fetchall():
                summary[row["severity"]] = {
                    "count": row["count"],
                    "avg_confidence": float(row["avg_confidence"] or 0),
                    "avg_cvss": 0,
                }
            return summary

    def get_top_findings_for_hypothesis(
        self, engagement_id: str, limit: int = 5000,
    ) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                """SELECT * FROM findings WHERE engagement_id = ?
                   ORDER BY
                       CASE severity
                           WHEN 'CRITICAL' THEN 0
                           WHEN 'HIGH' THEN 1
                           WHEN 'MEDIUM' THEN 2
                           WHEN 'LOW' THEN 3
                           WHEN 'INFO' THEN 4
                           ELSE 5
                       END,
                       confidence DESC
                   LIMIT ?""",
                (engagement_id, limit),
            )
            return [self._to_dict(row) for row in cursor.fetchall()]

    def find_high_confidence(
        self, engagement_id: str, threshold: float = 0.7
    ) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                """SELECT * FROM findings
                   WHERE engagement_id = ? AND confidence >= ?
                   ORDER BY confidence DESC LIMIT 500""",
                (engagement_id, threshold),
            )
            return [self._to_dict(row) for row in cursor.fetchall()]

"""
database/sqlite_trends.py — Cross-engagement trend analysis for local mode.

Aggregates findings across all engagements in the SQLite database to surface
portfolio-level insights: trending vulnerabilities, most affected domains,
CWE frequency, severity distribution, and risk scoring over time.

Connects to the same SQLite database used by ``SQLiteEngagementRepo`` and
``SQLiteFindingRepo`` — no separate schema required.

Usage::

    from database.sqlite_trends import SQLiteTrendRepository, display_trend_summary

    repo = SQLiteTrendRepository("assessments.db")
    trends = repo.get_trends(
        domain="example.com",
        last_n_days=90,
        min_severity="HIGH",
    )
    print(display_trend_summary(trends, verbose=True))
    repo.close()
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteTrendRepository:
    """SQLite-backed cross-engagement trend analysis.

    Thread-safe via per-operation lock. Shares the same database schema
    as ``SQLiteEngagementRepo`` and ``SQLiteFindingRepo``.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        # Ensure the underlying tables exist (created by sqlite_backend, but
        # this repo may be the first to connect to a fresh database)
        from database.sqlite_backend import _ensure_tables as _ensure_backend_tables
        with self._lock:
            _ensure_backend_tables(self._conn)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def get_trends(
        self,
        domain: str | None = None,
        last_n_days: int | None = None,
        min_severity: str | None = None,
    ) -> dict:
        """Aggregate cross-engagement trend data.

        Args:
            domain: Optional domain filter (matches against target_url).
            last_n_days: Only include findings from the last N days.
            min_severity: Minimum severity threshold (CRITICAL > HIGH > MEDIUM > LOW > INFO).

        Returns:
            Dict with trend analysis keys:
            - ``summary``: overall stats (total_engagements, total_findings, date_range)
            - ``by_severity``: severity distribution across all engagements
            - ``by_type``: top finding types with counts
            - ``by_cwe``: top CWEs with counts (requires cwe_id field)
            - ``by_domain``: per-domain breakdown (when no specific domain filter)
            - ``by_engagement``: top engagements by finding count
            - ``over_time``: findings grouped by month
            - ``avg_confidence_by_severity``: average confidence per severity level
        """
        with self._lock:
            return self._compute_trends(
                domain=domain,
                last_n_days=last_n_days,
                min_severity=min_severity,
            )

    def _compute_trends(
        self,
        domain: str | None = None,
        last_n_days: int | None = None,
        min_severity: str | None = None,
    ) -> dict:
        """Internal trend computation — must be called from within lock."""
        # ── Build base query with filters ──
        # We join findings with engagements to get target_url and dates.
        # Filters: domain match, recency, minimum severity.
        where_clauses: list[str] = []
        params: list[Any] = []

        if domain:
            where_clauses.append("e.target_url LIKE ?")
            params.append(f"%{domain}%")

        if last_n_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=last_n_days)
            where_clauses.append("f.created_at >= ?")
            params.append(cutoff.isoformat())

        if min_severity:
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
            min_order = severity_order.get(min_severity.upper(), 0)
            # Filter: only include findings with severity >= min_severity
            allowed = [s for s, o in severity_order.items() if o <= min_order]
            placeholders = ", ".join("?" for _ in allowed)
            where_clauses.append(f"f.severity IN ({placeholders})")
            params.extend(allowed)

        # Always start with WHERE 1=1 so appended AND clauses always work
        # (even when no filters are applied)
        where_sql = "WHERE 1=1"
        if where_clauses:
            where_sql += " AND " + " AND ".join(where_clauses)

        # ── Overall summary ──
        summary = self._get_summary(where_sql, params)

        # ── By severity ──
        by_severity = self._get_by_severity(where_sql, params)

        # ── By finding type ──
        by_type = self._get_by_type(where_sql, params)

        # ── By CWE ──
        by_cwe = self._get_by_cwe(where_sql, params)

        # ── By domain (only when no specific domain filter) ──
        by_domain = {}
        if not domain:
            by_domain = self._get_by_domain(where_sql, params)

        # ── By engagement ──
        by_engagement = self._get_by_engagement(where_sql, params)

        # ── Over time (monthly) ──
        over_time = self._get_over_time(where_sql, params)

        # ── Average confidence by severity ──
        avg_confidence = self._get_avg_confidence(where_sql, params)

        return {
            "summary": summary,
            "by_severity": by_severity,
            "by_type": by_type,
            "by_cwe": by_cwe,
            "by_domain": by_domain,
            "by_engagement": by_engagement,
            "over_time": over_time,
            "avg_confidence_by_severity": avg_confidence,
        }

    def _get_summary(self, where_sql: str, params: list) -> dict:
        """Get overall summary statistics."""
        cursor = self._conn.execute(
            f"""SELECT
                   COUNT(DISTINCT f.engagement_id) as total_engagements,
                   COUNT(*) as total_findings,
                   MIN(f.created_at) as earliest_finding,
                   MAX(f.created_at) as latest_finding,
                   COUNT(DISTINCT e.target_url) as unique_targets
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}""",
            params,
        )
        row = cursor.fetchone()
        if not row:
            return {
                "total_engagements": 0,
                "total_findings": 0,
                "earliest_finding": None,
                "latest_finding": None,
                "unique_targets": 0,
            }

        return {
            "total_engagements": row["total_engagements"],
            "total_findings": row["total_findings"],
            "earliest_finding": row["earliest_finding"],
            "latest_finding": row["latest_finding"],
            "unique_targets": row["unique_targets"],
        }

    def _get_by_severity(self, where_sql: str, params: list) -> list[dict]:
        """Get finding counts grouped by severity."""
        cursor = self._conn.execute(
            f"""SELECT
                   f.severity,
                   COUNT(*) as count,
                   ROUND(AVG(f.confidence), 2) as avg_confidence
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                GROUP BY f.severity
                ORDER BY
                   CASE f.severity
                       WHEN 'CRITICAL' THEN 0
                       WHEN 'HIGH' THEN 1
                       WHEN 'MEDIUM' THEN 2
                       WHEN 'LOW' THEN 3
                       WHEN 'INFO' THEN 4
                       ELSE 5
                   END""",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def _get_by_type(self, where_sql: str, params: list) -> list[dict]:
        """Get top finding types."""
        cursor = self._conn.execute(
            f"""SELECT
                   f.type,
                   COUNT(*) as count,
                   COUNT(DISTINCT f.engagement_id) as affected_engagements
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                GROUP BY f.type
                ORDER BY count(*) DESC
                LIMIT 20""",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def _get_by_cwe(self, where_sql: str, params: list) -> list[dict]:
        """Get top CWEs (when cwe_id is populated)."""
        cursor = self._conn.execute(
            f"""SELECT
                   f.cwe_id,
                   COUNT(*) as count,
                   COUNT(DISTINCT f.engagement_id) as affected_engagements
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                AND f.cwe_id IS NOT NULL
                AND f.cwe_id != ''
                GROUP BY f.cwe_id
                ORDER BY count(*) DESC
                LIMIT 15""",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def _get_by_domain(self, where_sql: str, params: list) -> list[dict]:
        """Get findings grouped by domain (extracted from target_url)."""
        # Extract domain from target_url: strip protocol and path
        cursor = self._conn.execute(
            f"""SELECT
                   e.target_url,
                   COUNT(*) as count,
                   COUNT(DISTINCT f.severity) as severity_count,
                   MAX(CASE WHEN f.severity = 'CRITICAL' THEN 1 ELSE 0 END) as has_critical,
                   MAX(CASE WHEN f.severity = 'HIGH' THEN 1 ELSE 0 END) as has_high
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                GROUP BY e.target_url
                ORDER BY count(*) DESC
                LIMIT 20""",
            params,
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d["has_critical"] = bool(d["has_critical"])
            d["has_high"] = bool(d["has_high"])
            results.append(d)
        return results

    def _get_by_engagement(self, where_sql: str, params: list) -> list[dict]:
        """Get top engagements by finding count."""
        cursor = self._conn.execute(
            f"""SELECT
                   f.engagement_id,
                   e.target_url,
                   e.created_at,
                   e.status,
                   COUNT(*) as count,
                   MAX(CASE WHEN f.severity = 'CRITICAL' THEN 1 ELSE 0 END) as has_critical,
                   MAX(CASE WHEN f.severity = 'HIGH' THEN 1 ELSE 0 END) as has_high
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                GROUP BY f.engagement_id
                ORDER BY count(*) DESC
                LIMIT 20""",
            params,
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d["has_critical"] = bool(d["has_critical"])
            d["has_high"] = bool(d["has_high"])
            results.append(d)
        return results

    def _get_over_time(self, where_sql: str, params: list) -> list[dict]:
        """Get findings grouped by month (for trend charting)."""
        cursor = self._conn.execute(
            f"""SELECT
                   SUBSTR(f.created_at, 1, 7) as month,
                   COUNT(*) as count,
                   COUNT(DISTINCT f.engagement_id) as engagement_count,
                   SUM(CASE WHEN f.severity IN ('CRITICAL', 'HIGH') THEN 1 ELSE 0 END) as high_plus_count
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                GROUP BY month
                ORDER BY month DESC
                LIMIT 24""",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def _get_avg_confidence(self, where_sql: str, params: list) -> list[dict]:
        """Get average confidence by severity."""
        cursor = self._conn.execute(
            f"""SELECT
                   f.severity,
                   ROUND(AVG(f.confidence), 2) as avg_confidence,
                   COUNT(*) as count
                FROM findings f
                LEFT JOIN engagements e ON f.engagement_id = e.id
                {where_sql}
                AND f.confidence IS NOT NULL
                GROUP BY f.severity
                ORDER BY
                   CASE f.severity
                       WHEN 'CRITICAL' THEN 0
                       WHEN 'HIGH' THEN 1
                       WHEN 'MEDIUM' THEN 2
                       WHEN 'LOW' THEN 3
                       WHEN 'INFO' THEN 4
                       ELSE 5
                   END""",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


# ── Display functions ──────────────────────────────────────────────


def _severity_color(severity: str) -> str:
    """ANSI color code for a severity level."""
    colors = {
        "CRITICAL": "\033[91m",   # Bright red
        "HIGH": "\033[38;5;196m",  # Red
        "MEDIUM": "\033[93m",     # Yellow
        "LOW": "\033[92m",        # Green
        "INFO": "\033[94m",       # Blue
    }
    reset = "\033[0m"
    return f"{colors.get(severity.upper(), '')}{severity}{reset}"


def display_trend_summary(trends: dict, verbose: bool = False) -> str:
    """Format trend analysis data as a human-readable table.

    Args:
        trends: Trend data dict from ``SQLiteTrendRepository.get_trends()``.
        verbose: If True, show all detail sections.
            If False (default), show only summary, severity, top types, top CWEs.

    Returns:
        Formatted string with tables and summaries.
    """
    lines: list[str] = []
    dash = "-" * 70

    summary = trends.get("summary", {})
    total_findings = summary.get("total_findings", 0)
    total_engagements = summary.get("total_engagements", 0)
    unique_targets = summary.get("unique_targets", 0)

    if total_findings == 0:
        lines.append("")
        lines.append("  No findings found matching the current filters.")
        lines.append("")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"  {'=' * 66}")
    lines.append(f"  {'':>5}Cross-Engagement Trend Analysis")
    lines.append(f"  {'=' * 66}")
    lines.append("")
    lines.append(f"  {'Summary':^66}")
    lines.append(f"  {dash}")
    lines.append(f"    Total engagements:    {total_engagements}")
    lines.append(f"    Total findings:       {total_findings}")
    lines.append(f"    Unique targets:       {unique_targets}")
    lines.append(f"    Date range:           {summary.get('earliest_finding', '-')[:10]} to {summary.get('latest_finding', '-')[:10]}")
    lines.append("")

    # ── Severity breakdown ──
    by_severity = trends.get("by_severity", [])
    if by_severity:
        lines.append(f"  {'Severity Breakdown':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'Severity':<12} {'Count':<10} {'Avg Confidence':<15}")
        lines.append(f"    {'-'*10:<12} {'-'*5:<10} {'-'*13:<15}")
        for item in by_severity:
            sev = item["severity"] or "UNKNOWN"
            count = item["count"]
            avg_conf = item.get("avg_confidence", 0)
            lines.append(f"    {_severity_color(sev):<12} {count:<10} {avg_conf:<15}")
        lines.append("")

    # ── Top finding types ──
    by_type = trends.get("by_type", [])
    if by_type:
        lines.append(f"  {'Top Finding Types':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'Type':<30} {'Count':<10} {'Engagements':<12}")
        lines.append(f"    {'-'*28:<30} {'-'*5:<10} {'-'*10:<12}")
        for item in by_type[:10]:
            ftype = item["type"] or "UNKNOWN"
            if len(ftype) > 28:
                ftype = ftype[:25] + "..."
            lines.append(f"    {ftype:<30} {item['count']:<10} {item['affected_engagements']:<12}")
        lines.append("")

    # ── Top CWEs ──
    by_cwe = trends.get("by_cwe", [])
    if by_cwe:
        lines.append(f"  {'Top CWEs':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'CWE ID':<15} {'Count':<10} {'Engagements':<12}")
        lines.append(f"    {'-'*13:<15} {'-'*5:<10} {'-'*10:<12}")
        for item in by_cwe[:8]:
            cwe = item.get("cwe_id", "N/A") or "N/A"
            lines.append(f"    {cwe:<15} {item['count']:<10} {item['affected_engagements']:<12}")
        lines.append("")

    # ── Over time (monthly) ──
    over_time = trends.get("over_time", [])
    if over_time and verbose:
        lines.append(f"  {'Findings Over Time (Monthly)':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'Month':<12} {'Findings':<12} {'Engagements':<12} {'HIGH+CRIT':<12}")
        lines.append(f"    {'-'*8:<12} {'-'*8:<12} {'-'*10:<12} {'-'*8:<12}")
        for item in over_time[:12]:
            lines.append(f"    {item['month']:<12} {item['count']:<12} {item['engagement_count']:<12} {item['high_plus_count']:<12}")
        lines.append("")

    # ── By domain ──
    by_domain = trends.get("by_domain", [])
    if by_domain and verbose:
        lines.append(f"  {'Top Domains':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'Target URL':<40} {'Findings':<10} {'Critical':<10}")
        lines.append(f"    {'-'*38:<40} {'-'*8:<10} {'-'*8:<10}")
        for item in by_domain[:8]:
            url = item.get("target_url", "N/A") or "N/A"
            if len(url) > 38:
                url = url[:35] + "..."
            critical_flag = "!" if item.get("has_critical") else " "
            lines.append(f"    {url:<40} {item['count']:<10} {critical_flag:<10}")
        lines.append("")

    # ── Top engagements ──
    by_engagement = trends.get("by_engagement", [])
    if by_engagement and verbose:
        lines.append(f"  {'Top Engagements by Finding Count':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'Engagement ID':<20} {'Target':<25} {'Findings':<10} {'Status':<10}")
        lines.append(f"    {'-'*18:<20} {'-'*23:<25} {'-'*8:<10} {'-'*8:<10}")
        for item in by_engagement[:8]:
            eid = str(item.get("engagement_id", ""))[:18]
            url = str(item.get("target_url", "N/A") or "N/A")
            if len(url) > 23:
                url = url[:20] + "..."
            status = str(item.get("status", "-") or "-")
            lines.append(f"    {eid:<20} {url:<25} {item['count']:<10} {status:<10}")
        lines.append("")

    # ── Average confidence by severity ──
    avg_conf = trends.get("avg_confidence_by_severity", [])
    if avg_conf and verbose:
        lines.append(f"  {'Average Confidence by Severity':^66}")
        lines.append(f"  {dash}")
        lines.append(f"    {'Severity':<12} {'Avg Confidence':<15} {'Count':<10}")
        lines.append(f"    {'-'*10:<12} {'-'*13:<15} {'-'*5:<10}")
        for item in avg_conf:
            sev = item["severity"] or "UNKNOWN"
            lines.append(f"    {_severity_color(sev):<12} {item['avg_confidence']:<15} {item['count']:<10}")
        lines.append("")

    lines.append(f"  {'=' * 66}")
    lines.append("")
    return "\n".join(lines)

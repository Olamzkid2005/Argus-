"""
database/sqlite_trends.py — Cross-engagement trend analysis for local mode.

Aggregates findings across all engagements in the SQLite database to
provide portfolio-level visibility: trending vulnerabilities, most
affected domains, CWE frequency, and risk scoring over time.

Usage::

    from database.sqlite_trends import SQLiteTrendRepository

    repo = SQLiteTrendRepository("assessments.db")
    trends = repo.get_trends(domain="example.com", last_n_days=30)
    print(trends.summary)
    repo.close()
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class TrendSummary:
    """Aggregated trend data across engagements."""

    total_engagements: int = 0
    total_findings: int = 0
    unique_domains: int = 0
    unique_cwes: int = 0
    severity_breakdown: dict[str, int] = field(default_factory=dict)
    top_cwes: list[dict] = field(default_factory=list)
    top_domains: list[dict] = field(default_factory=list)
    top_tools: list[dict] = field(default_factory=list)
    findings_over_time: list[dict] = field(default_factory=list)
    recurring_vulnerabilities: list[dict] = field(default_factory=list)
    portfolio_risk_score: float = 0.0

    @property
    def summary_line(self) -> str:
        """Short one-line summary."""
        total = sum(self.severity_breakdown.values()) or self.total_findings
        crit = self.severity_breakdown.get("CRITICAL", 0)
        high = self.severity_breakdown.get("HIGH", 0)
        return (
            f"{self.total_engagements} engagements, {total} findings "
            f"({crit} CRITICAL, {high} HIGH), "
            f"{self.unique_domains} domains, {self.unique_cwes} CWEs"
        )


class SQLiteTrendRepository:
    """Cross-engagement trend analysis for local/standalone mode.

    Thread-safe via per-operation lock. Reads from the same SQLite
    database as ``SQLiteEngagementRepo`` and ``SQLiteFindingRepo``.
    Gracefully returns empty results when the database is fresh
    (no tables created yet).
    """

    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        with self._lock:
            pass  # Tables created by SQLiteEngagementRepo / SQLiteFindingRepo

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    # ── Public API ───────────────────────────────────────────────────

    def get_trends(
        self,
        domain: str | None = None,
        last_n_days: int | None = None,
        min_severity: str | None = None,
    ) -> TrendSummary:
        """Aggregate findings across engagements to produce trend data.

        Args:
            domain: Filter to engagements matching this domain.
            last_n_days: Only consider engagements from the last N days.
            min_severity: Minimum severity to include (e.g. ``HIGH``).

        Returns:
            TrendSummary with aggregated statistics.
        """
        with self._lock:
            try:
                return self._compute_trends(domain, last_n_days, min_severity)
            except sqlite3.OperationalError as e:
                logger.debug("Trend query failed (engagements table may not exist): %s", e)
                return TrendSummary()

    def get_domain_list(self) -> list[dict]:
        """List all unique domains with engagement counts.

        Returns:
            List of dicts with ``domain``, ``engagement_count``, ``finding_count``.
        """
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """SELECT
                        e.target_url,
                        COUNT(DISTINCT e.id) as engagement_count,
                        COUNT(f.id) as finding_count
                       FROM engagements e
                       LEFT JOIN findings f ON f.engagement_id = e.id
                       WHERE e.target_url IS NOT NULL AND e.target_url != ''
                       GROUP BY e.target_url
                       ORDER BY finding_count DESC"""
                )
                results = []
                for row in cursor.fetchall():
                    domain = self._extract_domain(row["target_url"])
                    if domain:
                        results.append({
                            "domain": domain,
                            "target_url": row["target_url"],
                            "engagement_count": row["engagement_count"],
                            "finding_count": row["finding_count"],
                        })
                return results
            except sqlite3.OperationalError as e:
                logger.debug("Domain list query failed (tables may not exist): %s", e)
                return []

    def get_cwe_list(self) -> list[dict]:
        """List all CWEs found with frequency.

        Returns:
            List of dicts with ``cwe_id``, ``count``, ``avg_severity``.
        """
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """SELECT
                        cwe_id,
                        COUNT(*) as count,
                        AVG(CASE severity
                            WHEN 'CRITICAL' THEN 5 WHEN 'HIGH' THEN 4
                            WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 2
                            ELSE 1 END) as avg_severity_score
                       FROM findings
                       WHERE cwe_id IS NOT NULL AND cwe_id != ''
                       GROUP BY cwe_id
                       ORDER BY count DESC"""
                )
                return [
                    {
                        "cwe_id": row["cwe_id"],
                        "count": row["count"],
                        "avg_severity_score": round(float(row["avg_severity_score"] or 0), 2),
                    }
                    for row in cursor.fetchall()
                ]
            except sqlite3.OperationalError as e:
                logger.debug("CWE list query failed (tables may not exist): %s", e)
                return []

    # ── Internal: trend computation ────────────────────────────────

    def _compute_trends(
        self,
        domain: str | None,
        last_n_days: int | None,
        min_severity: str | None,
    ) -> TrendSummary:
        """Compute trend summary from raw data."""
        # ── 1. Build engagement filter ──────────────────────────────
        where_clauses: list[str] = []
        params: list[Any] = []

        if domain:
            where_clauses.append("e.target_url LIKE ?")
            params.append(f"%{domain}%")

        if last_n_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=last_n_days)
            where_clauses.append("COALESCE(e.completed_at, e.created_at) >= ?")
            params.append(cutoff.isoformat())

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # ── 2. Engagement stats ─────────────────────────────────────
        cursor = self._conn.execute(
            f"SELECT COUNT(*) as cnt FROM engagements e {where_sql}", params
        )
        total_engagements = cursor.fetchone()["cnt"]

        cursor = self._conn.execute(
            f"""SELECT COUNT(DISTINCT e.target_url) as cnt
                FROM engagements e {where_sql}""",
            params,
        )
        unique_domains = cursor.fetchone()["cnt"]

        # ── 3. Finding stats ────────────────────────────────────────
        finding_join = f"FROM findings f JOIN engagements e ON f.engagement_id = e.id {where_sql}"
        severity_filter = ""
        if min_severity:
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
            sev_level = severity_order.get(min_severity.upper(), 0)
            sev_names = [s for s, l in severity_order.items() if l <= sev_level]
            severity_filter = f" AND f.severity IN ({','.join('?' * len(sev_names))})"
            params_sev = list(params) + sev_names
        else:
            params_sev = list(params)

        cursor = self._conn.execute(
            f"SELECT COUNT(*) as cnt {finding_join}{severity_filter}", params_sev
        )
        total_findings = cursor.fetchone()["cnt"]

        # Severity breakdown
        cursor = self._conn.execute(
            f"""SELECT f.severity, COUNT(*) as count
                {finding_join}{severity_filter}
                GROUP BY f.severity ORDER BY count DESC""",
            params_sev,
        )
        severity_breakdown: dict[str, int] = {}
        for row in cursor.fetchall():
            severity_breakdown[str(row["severity"])] = row["count"]

        # ── 4. Top CWEs ─────────────────────────────────────────────
        cursor = self._conn.execute(
            f"""SELECT f.cwe_id, COUNT(*) as count
                {finding_join}
                AND f.cwe_id IS NOT NULL AND f.cwe_id != ''
                GROUP BY f.cwe_id ORDER BY count DESC LIMIT 10""",
            params,
        )
        top_cwes = [
            {"cwe_id": row["cwe_id"], "count": row["count"]}
            for row in cursor.fetchall()
        ]

        # ── 5. Top domains ──────────────────────────────────────────
        cursor = self._conn.execute(
            f"""SELECT e.target_url, COUNT(f.id) as finding_count
                {finding_join}
                GROUP BY e.target_url ORDER BY finding_count DESC LIMIT 10""",
            params,
        )
        top_domains_raw = cursor.fetchall()
        top_domains = []
        seen_domains: set[str] = set()
        for row in top_domains_raw:
            d = self._extract_domain(row["target_url"])
            if d and d not in seen_domains:
                seen_domains.add(d)
                top_domains.append({
                    "domain": d,
                    "target_url": row["target_url"],
                    "finding_count": row["finding_count"],
                })

        # ── 6. Top tools ────────────────────────────────────────────
        cursor = self._conn.execute(
            f"""SELECT f.source_tool, COUNT(*) as count
                {finding_join}
                AND f.source_tool IS NOT NULL AND f.source_tool != ''
                GROUP BY f.source_tool ORDER BY count DESC LIMIT 10""",
            params,
        )
        top_tools = [
            {"tool": row["source_tool"], "count": row["count"]}
            for row in cursor.fetchall()
        ]

        # ── 7. Findings over time (by day) ──────────────────────────
        cursor = self._conn.execute(
            f"""SELECT DATE(f.created_at) as day, COUNT(*) as count
                {finding_join}
                AND f.created_at IS NOT NULL
                GROUP BY day ORDER BY day DESC LIMIT 30""",
            params,
        )
        findings_over_time = [
            {"date": row["day"], "count": row["count"]}
            for row in reversed(list(cursor.fetchall()))
        ]

        # ── 8. Recurring vulnerabilities ────────────────────────────
        cursor = self._conn.execute(
            f"""SELECT f.cwe_id, e.target_url, COUNT(DISTINCT e.id) as eng_count
                {finding_join}
                AND f.cwe_id IS NOT NULL AND f.cwe_id != ''
                AND e.target_url IS NOT NULL AND e.target_url != ''
                GROUP BY f.cwe_id, e.target_url
                HAVING eng_count > 1
                ORDER BY eng_count DESC LIMIT 10""",
            params,
        )
        recurring_vulnerabilities = [
            {
                "cwe_id": row["cwe_id"],
                "target_url": row["target_url"],
                "times_found": row["eng_count"],
            }
            for row in cursor.fetchall()
        ]

        # ── 9. Portfolio risk score (0-100) ─────────────────────────
        severity_score = min(
            100,
            (
                severity_breakdown.get("CRITICAL", 0) * 20
                + severity_breakdown.get("HIGH", 0) * 8
                + severity_breakdown.get("MEDIUM", 0) * 3
            )
            / max(total_findings, 1) * 100,
        )
        recurrence_score = min(
            100,
            len(recurring_vulnerabilities) * 20,
        )
        volume_score = min(
            100,
            total_findings / max(total_engagements, 1) * 10,
        )
        portfolio_risk_score = round(
            severity_score * 0.4 + recurrence_score * 0.3 + volume_score * 0.3, 1
        )

        return TrendSummary(
            total_engagements=total_engagements,
            total_findings=total_findings,
            unique_domains=unique_domains,
            unique_cwes=len(top_cwes),
            severity_breakdown=dict(severity_breakdown),
            top_cwes=top_cwes,
            top_domains=top_domains,
            top_tools=top_tools,
            findings_over_time=findings_over_time,
            recurring_vulnerabilities=recurring_vulnerabilities,
            portfolio_risk_score=portfolio_risk_score,
        )

    @staticmethod
    def _extract_domain(target_url: str) -> str:
        """Extract domain from a target URL."""
        if not target_url:
            return ""
        try:
            parsed = urlparse(target_url)
            domain = parsed.hostname or parsed.netloc or target_url
            return domain.lower().strip()
        except Exception:
            return target_url.lower().strip() if target_url else ""


def display_trend_summary(trends: TrendSummary, verbose: bool = False) -> str:
    """Format a trend summary as a human-readable report.

    Args:
        trends: TrendSummary to display.
        verbose: If True, show all sections including top tools and
            findings over time.

    Returns:
        Formatted string.
    """
    lines: list[str] = []
    sep = "-" * 62

    lines.append("")
    lines.append("  Cross-Engagement Trend Report")
    lines.append(f"  {sep}")
    lines.append(f"  Portfolio Risk Score: {trends.portfolio_risk_score}/100")
    lines.append(f"  {sep}")
    lines.append(f"  {'Metric':<35} {'Value':<25}")
    lines.append(f"  {sep}")
    lines.append(f"  {'Total engagements':<35} {trends.total_engagements}")
    lines.append(f"  {'Total findings':<35} {trends.total_findings}")
    lines.append(f"  {'Unique domains':<35} {trends.unique_domains}")
    lines.append(f"  {'Unique CWEs':<35} {trends.unique_cwes}")

    # Severity breakdown
    if trends.severity_breakdown:
        lines.append(f"  {sep}")
        lines.append("  Severity Breakdown:")
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            count = trends.severity_breakdown.get(sev, 0)
            if count > 0:
                lines.append(f"    {sev:<20} {count}")

    # Top CWEs
    if trends.top_cwes:
        lines.append(f"  {sep}")
        lines.append("  Top CWEs:")
        for cwe in trends.top_cwes[:5]:
            lines.append(f"    {cwe['cwe_id']:<20} {cwe['count']} finding(s)")

    # Top domains
    if trends.top_domains:
        lines.append(f"  {sep}")
        lines.append("  Most Tested Domains:")
        for d in trends.top_domains[:5]:
            lines.append(f"    {d['domain']:<30} {d['finding_count']} finding(s)")

    # Recurring vulnerabilities
    if trends.recurring_vulnerabilities:
        lines.append(f"  {sep}")
        lines.append("  Recurring Vulnerabilities (same CWE, multiple engagements):")
        for rv in trends.recurring_vulnerabilities[:5]:
            lines.append(
                f"    {rv['cwe_id']:<20} found {rv['times_found']}x on {rv['target_url']}"
            )

    # Verbose sections
    if verbose:
        if trends.top_tools:
            lines.append(f"  {sep}")
            lines.append("  Top Finding Sources:")
            for t in trends.top_tools:
                lines.append(f"    {t['tool']:<25} {t['count']} finding(s)")

        if trends.findings_over_time:
            lines.append(f"  {sep}")
            lines.append("  Findings Over Time (last 30 days):")
            for ft in trends.findings_over_time[-10:]:
                lines.append(f"    {ft['date']:<15} {ft['count']} finding(s)")

    lines.append(f"  {sep}")
    lines.append(f"  Portfolio Risk Score: {trends.portfolio_risk_score}/100")
    lines.append("")
    return "\n".join(lines)

"""
Tests for database/sqlite_trends.py — cross-engagement trend analysis.

Uses real SQLite with seeded engagements and findings via a shared temp
file to verify aggregation logic, filters, and graceful empty-DB handling.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from database.sqlite_trends import SQLiteTrendRepository, TrendSummary, display_trend_summary
from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo


def _seed_data(db_path: str) -> None:
    """Seed a SQLite database file with sample engagements and findings."""
    eng_repo = SQLiteEngagementRepo(db_path)
    finding_repo = SQLiteFindingRepo(db_path)

    # Engagement 1: https://example.com
    eng1 = eng_repo.create({
        "target_url": "https://example.com",
        "org_id": "local", "status": "completed", "scan_type": "url",
    })
    finding_repo.create_finding(
        eng1["id"], "SQL_INJECTION", "CRITICAL", "/api",
        {"payload": "' OR 1=1--"}, 0.9, "nuclei",
        cwe_id="CWE-89",
    )
    finding_repo.create_finding(
        eng1["id"], "XSS", "HIGH", "/search",
        {"payload": "<script>"}, 0.8, "httpx",
        cwe_id="CWE-79",
    )
    finding_repo.create_finding(
        eng1["id"], "INFO_LEAK", "MEDIUM", "/robots.txt",
        {"detail": "Disallowed paths"}, 0.6, "katana",
        cwe_id="CWE-200",
    )

    # Engagement 2: https://example.com (same domain, more findings)
    eng2 = eng_repo.create({
        "target_url": "https://example.com",
        "org_id": "local", "status": "completed", "scan_type": "url",
    })
    finding_repo.create_finding(
        eng2["id"], "SQL_INJECTION", "CRITICAL", "/admin",
        {"payload": "' UNION SELECT--"}, 0.95, "nuclei",
        cwe_id="CWE-89",
    )
    finding_repo.create_finding(
        eng2["id"], "AUTH_BYPASS", "CRITICAL", "/login",
        {"detail": "Weak JWT"}, 0.85, "nuclei",
        cwe_id="CWE-287",
    )

    # Engagement 3: different domain, 60 days old
    old = datetime.now(timezone.utc) - timedelta(days=60)
    eng3 = eng_repo.create({
        "target_url": "https://staging.example.org",
        "org_id": "local", "status": "completed", "scan_type": "url",
    })
    eng_repo.update_by_id(eng3["id"], {"completed_at": old.isoformat()})
    finding_repo.create_finding(
        eng3["id"], "LOW_ISSUE", "LOW", "/",
        {"detail": "Server header"}, 0.3, "whatweb",
        cwe_id="CWE-16",
    )


class TestSQLiteTrendRepository:
    """Test suite for SQLiteTrendRepository with seeded data."""

    @pytest.fixture
    def seeded_repo(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        _seed_data(db_path)
        repo = SQLiteTrendRepository(db_path)
        yield repo
        repo.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def empty_repo(self):
        repo = SQLiteTrendRepository(":memory:")
        yield repo
        repo.close()

    def test_get_trends_returns_summary(self, seeded_repo):
        """get_trends returns a TrendSummary with correct totals."""
        trends = seeded_repo.get_trends()
        assert isinstance(trends, TrendSummary)
        assert trends.total_engagements == 3
        assert trends.total_findings == 6
        assert trends.unique_domains == 2

    def test_get_trends_severity_breakdown(self, seeded_repo):
        """Severity breakdown counts are correct."""
        trends = seeded_repo.get_trends()
        assert trends.severity_breakdown.get("CRITICAL", 0) == 3
        assert trends.severity_breakdown.get("HIGH", 0) == 1
        assert trends.severity_breakdown.get("MEDIUM", 0) == 1
        assert trends.severity_breakdown.get("LOW", 0) == 1

    def test_get_trends_domain_filter(self, seeded_repo):
        """Domain filter narrows results."""
        trends = seeded_repo.get_trends(domain="example.com")
        assert trends.total_engagements == 2
        assert trends.total_findings == 5
        assert trends.unique_domains == 1

    def test_get_trends_last_n_days(self, seeded_repo):
        """Time filter excludes old engagements."""
        trends = seeded_repo.get_trends(last_n_days=30)
        assert trends.total_engagements == 2  # eng3 is 60 days old
        assert trends.total_findings == 5

    def test_get_trends_min_severity_high(self, seeded_repo):
        """Min severity filter includes only HIGH+ findings."""
        trends = seeded_repo.get_trends(min_severity="HIGH")
        assert trends.total_findings == 4

    def test_get_trends_min_severity_critical(self, seeded_repo):
        """Min severity CRITICAL includes only CRITICAL findings."""
        trends = seeded_repo.get_trends(min_severity="CRITICAL")
        assert trends.total_findings == 3

    def test_get_trends_top_cwes(self, seeded_repo):
        """Top CWEs sorted by frequency."""
        trends = seeded_repo.get_trends()
        assert len(trends.top_cwes) >= 1
        cwe_89 = [c for c in trends.top_cwes if c["cwe_id"] == "CWE-89"]
        assert len(cwe_89) == 1
        assert cwe_89[0]["count"] >= 2

    def test_get_trends_top_domains(self, seeded_repo):
        """Most tested domains sorted by finding count."""
        trends = seeded_repo.get_trends()
        assert len(trends.top_domains) >= 1
        assert trends.top_domains[0]["domain"] == "example.com"

    def test_get_trends_top_tools(self, seeded_repo):
        """Top tools sorted by finding count."""
        trends = seeded_repo.get_trends()
        tool_names = [t["tool"] for t in trends.top_tools]
        assert "nuclei" in tool_names

    def test_get_trends_recurring_vulns(self, seeded_repo):
        """CWE appearing in multiple engagements for same domain."""
        trends = seeded_repo.get_trends()
        cwe_89_rec = [
            r for r in trends.recurring_vulnerabilities if r["cwe_id"] == "CWE-89"
        ]
        assert len(cwe_89_rec) >= 1
        assert cwe_89_rec[0]["times_found"] >= 2

    def test_get_trends_risk_score(self, seeded_repo):
        """Portfolio risk score computes without error."""
        trends = seeded_repo.get_trends()
        assert 0 <= trends.portfolio_risk_score <= 100
        assert trends.portfolio_risk_score > 0

    def test_get_trends_findings_over_time(self, seeded_repo):
        """Findings over time returns daily counts."""
        trends = seeded_repo.get_trends()
        assert len(trends.findings_over_time) > 0

    def test_summary_line_format(self, seeded_repo):
        """summary_line property returns formatted string."""
        trends = seeded_repo.get_trends()
        line = trends.summary_line
        assert "3 engagements" in line
        assert "3 CRITICAL" in line
        assert "1 HIGH" in line

    def test_empty_db_returns_defaults(self, empty_repo):
        """Fresh DB returns empty TrendSummary without crashing."""
        trends = empty_repo.get_trends()
        assert isinstance(trends, TrendSummary)
        assert trends.total_engagements == 0
        assert trends.total_findings == 0
        assert trends.portfolio_risk_score == 0.0

    def test_empty_db_domain_list(self, empty_repo):
        """get_domain_list on fresh DB returns []."""
        assert empty_repo.get_domain_list() == []

    def test_empty_db_cwe_list(self, empty_repo):
        """get_cwe_list on fresh DB returns []."""
        assert empty_repo.get_cwe_list() == []

    def test_seeded_domain_list(self, seeded_repo):
        """get_domain_list returns seeded domains."""
        domains = seeded_repo.get_domain_list()
        assert len(domains) >= 2
        domain_names = [d["domain"] for d in domains]
        assert "example.com" in domain_names

    def test_seeded_cwe_list(self, seeded_repo):
        """get_cwe_list returns seeded CWEs."""
        cwes = seeded_repo.get_cwe_list()
        assert len(cwes) >= 3
        cwe_ids = [c["cwe_id"] for c in cwes]
        assert "CWE-89" in cwe_ids
        assert "CWE-79" in cwe_ids


class TestDisplayTrendSummary:
    """Tests for the display_trend_summary formatting function."""

    def test_empty_display(self):
        """Display empty trends produces a formatted report."""
        trends = TrendSummary()
        output = display_trend_summary(trends)
        assert "Cross-Engagement Trend Report" in output
        assert "0/100" in output

    def test_verbose_extra_sections(self):
        """Verbose mode includes extra sections."""
        trends = TrendSummary(
            total_engagements=1,
            total_findings=3,
            severity_breakdown={"CRITICAL": 1, "HIGH": 1, "LOW": 1},
            top_tools=[{"tool": "nuclei", "count": 2}, {"tool": "httpx", "count": 1}],
            findings_over_time=[{"date": "2026-06-01", "count": 1}],
            portfolio_risk_score=45.0,
        )
        verbose = display_trend_summary(trends, verbose=True)
        non_verbose = display_trend_summary(trends, verbose=False)

        assert "Top Finding Sources" in verbose
        assert "nuclei" in verbose
        assert "Findings Over Time" in verbose
        assert "2026-06-01" in verbose
        assert "Top Finding Sources" not in non_verbose

    def test_display_with_cwes(self):
        """Display includes top CWEs when present."""
        trends = TrendSummary(
            total_engagements=1,
            total_findings=2,
            top_cwes=[{"cwe_id": "CWE-89", "count": 2}],
            portfolio_risk_score=30.0,
        )
        output = display_trend_summary(trends)
        assert "Top CWEs" in output
        assert "CWE-89" in output

    def test_display_with_recurring(self):
        """Display includes recurring vulnerabilities when present."""
        trends = TrendSummary(
            total_engagements=2,
            total_findings=5,
            recurring_vulnerabilities=[
                {"cwe_id": "CWE-89", "target_url": "example.com", "times_found": 2}
            ],
            portfolio_risk_score=50.0,
        )
        output = display_trend_summary(trends)
        assert "Recurring Vulnerabilities" in output
        assert "CWE-89" in output
        assert "2x" in output

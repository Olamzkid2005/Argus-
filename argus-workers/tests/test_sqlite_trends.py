"""Tests for database/sqlite_trends.py — cross-engagement trend analysis."""

from __future__ import annotations

import pytest

from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo
from database.sqlite_trends import SQLiteTrendRepository, display_trend_summary


# ── Helpers ──────────────────────────────────────────────────────────────


def _seed_engagement(eng_repo: SQLiteEngagementRepo, **overrides: str) -> dict:
    """Create a basic engagement with sensible defaults."""
    defaults = {
        "target_url": "https://example.com",
        "org_id": "test-org",
        "status": "completed",
        "scan_type": "url",
        "created_by": "test",
    }
    defaults.update(overrides)
    return eng_repo.create(defaults)


def _seed_finding(finding_repo: SQLiteFindingRepo, engagement_id: str, **overrides) -> str:
    """Create a basic finding with sensible defaults."""
    defaults = {
        "engagement_id": engagement_id,
        "finding_type": "SQL_INJECTION",
        "severity": "HIGH",
        "endpoint": "https://example.com/api",
        "evidence": {"payload": "test"},
        "confidence": 0.9,
        "source_tool": "nuclei",
        "cvss_score": 8.5,
        "cwe_id": "CWE-89",
    }
    defaults.update(overrides)
    return finding_repo.create_finding(**defaults)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def shared_db(tmp_path):
    """All repos share the same temp-file database (avoid :memory: isolation)."""
    db_path = str(tmp_path / "test_trends.db")
    eng_repo = SQLiteEngagementRepo(db_path)
    finding_repo = SQLiteFindingRepo(db_path)
    trend_repo = SQLiteTrendRepository(db_path)
    yield eng_repo, finding_repo, trend_repo
    trend_repo.close()
    finding_repo.close()
    eng_repo.close()


@pytest.fixture
def seeded_db(shared_db):
    """Database seeded with 2 engagements and 5 findings across them."""
    eng_repo, finding_repo, trend_repo = shared_db

    # Engagement 1: https://example.com — 3 findings (CRITICAL, HIGH, MEDIUM)
    eng1 = _seed_engagement(eng_repo, target_url="https://example.com")
    _seed_finding(finding_repo, eng1["id"],
                  finding_type="SQL_INJECTION", severity="CRITICAL",
                  endpoint="https://example.com/api", cwe_id="CWE-89", confidence=0.95)
    _seed_finding(finding_repo, eng1["id"],
                  finding_type="XSS", severity="HIGH",
                  endpoint="https://example.com/login", cwe_id="CWE-79", confidence=0.8)
    _seed_finding(finding_repo, eng1["id"],
                  finding_type="OPEN_REDIRECT", severity="MEDIUM",
                  endpoint="https://example.com/redirect", cwe_id="CWE-601", confidence=0.6)

    # Engagement 2: https://test.org — 2 findings (MEDIUM, LOW)
    eng2 = _seed_engagement(eng_repo, target_url="https://test.org")
    _seed_finding(finding_repo, eng2["id"],
                  finding_type="XSS", severity="MEDIUM",
                  endpoint="https://test.org/search", cwe_id="CWE-79", confidence=0.65)
    _seed_finding(finding_repo, eng2["id"],
                  finding_type="WEAK_TLS", severity="LOW",
                  endpoint="https://test.org", cwe_id="CWE-327", confidence=0.5)

    return eng_repo, finding_repo, trend_repo, eng1, eng2


# ── TrendRepository tests ───────────────────────────────────────────────


class TestSQLiteTrendRepository:
    """Tests for SQLiteTrendRepository.get_trends()."""

    def test_empty_database(self, shared_db):
        """get_trends returns empty summary when no data exists."""
        eng_repo, finding_repo, trend_repo = shared_db
        trends = trend_repo.get_trends()
        summary = trends["summary"]
        assert summary["total_engagements"] == 0
        assert summary["total_findings"] == 0
        assert summary["unique_targets"] == 0

    def test_no_filters_returns_all_data(self, seeded_db):
        """get_trends with no filters returns all engagements and findings."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        summary = trends["summary"]
        assert summary["total_engagements"] == 2
        assert summary["total_findings"] == 5
        assert summary["unique_targets"] == 2

    def test_summary_has_date_range(self, seeded_db):
        """Summary includes earliest and latest finding timestamps."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        s = trends["summary"]
        assert s["earliest_finding"] is not None
        assert s["latest_finding"] is not None
        assert s["earliest_finding"] <= s["latest_finding"]

    # ── Severity breakdown ──────────────────────────────────────────

    def test_severity_breakdown(self, seeded_db):
        """Severity breakdown has correct counts."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        by_sev = trends["by_severity"]
        sev_map = {s["severity"]: s["count"] for s in by_sev}
        assert sev_map.get("CRITICAL") == 1
        assert sev_map.get("HIGH") == 1
        assert sev_map.get("MEDIUM") == 2
        assert sev_map.get("LOW") == 1

    def test_severity_ordered_correctly(self, seeded_db):
        """Severity results are ordered CRITICAL > HIGH > MEDIUM > LOW > INFO."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        order = [s["severity"] for s in trends["by_severity"] if s["severity"]]
        assert order == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

    def test_severity_includes_avg_confidence(self, seeded_db):
        """Each severity entry includes avg_confidence."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        for s in trends["by_severity"]:
            assert "avg_confidence" in s
            assert isinstance(s["avg_confidence"], (int, float))

    # ── Finding type aggregation ─────────────────────────────────────

    def test_by_type_shows_all_types(self, seeded_db):
        """Top finding types includes all unique types."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        types = {t["type"] for t in trends["by_type"]}
        assert "SQL_INJECTION" in types
        assert "XSS" in types
        assert "OPEN_REDIRECT" in types
        assert "WEAK_TLS" in types

    def test_by_type_counts_correctly(self, seeded_db):
        """Finding type counts are correct (XSS appears twice)."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        type_map = {t["type"]: t["count"] for t in trends["by_type"]}
        assert type_map["XSS"] == 2
        assert type_map["SQL_INJECTION"] == 1

    def test_by_type_affected_engagements(self, seeded_db):
        """XSS affects both engagements, other types affect only one."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        type_map = {t["type"]: t["affected_engagements"] for t in trends["by_type"]}
        assert type_map["XSS"] == 2
        assert type_map["SQL_INJECTION"] == 1

    # ── CWE aggregation ──────────────────────────────────────────────

    def test_cwe_aggregation(self, seeded_db):
        """CWE aggregation returns all 4 distinct CWEs."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        cwe_list = trends["by_cwe"]
        cwe_map = {c["cwe_id"]: c["count"] for c in cwe_list}
        assert "CWE-79" in cwe_map
        assert "CWE-89" in cwe_map
        assert "CWE-601" in cwe_map
        assert "CWE-327" in cwe_map
        assert cwe_map["CWE-79"] == 2  # XSS appears twice

    def test_cwe_aggregation_no_cwe_data(self, shared_db):
        """CWE aggregation returns empty list when no findings have cwe_id."""
        eng_repo, finding_repo, trend_repo = shared_db
        eng = _seed_engagement(eng_repo)
        _seed_finding(finding_repo, eng["id"], cwe_id=None,
                      finding_type="TEST", endpoint="https://test.com/a")
        _seed_finding(finding_repo, eng["id"], cwe_id="",
                      finding_type="TEST2", endpoint="https://test.com/b")
        trends = trend_repo.get_trends()
        assert trends["by_cwe"] == []

    # ── Domain aggregation ───────────────────────────────────────────

    def test_by_domain_counts(self, seeded_db):
        """Domain breakdown shows correct counts per domain."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        domain_map = {d["target_url"]: d["count"] for d in trends["by_domain"]}
        assert domain_map.get("https://example.com") == 3
        assert domain_map.get("https://test.org") == 2

    def test_by_domain_critical_flag(self, seeded_db):
        """Domain with CRITICAL findings has has_critical=True."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        for d in trends["by_domain"]:
            if d["target_url"] == "https://example.com":
                assert d["has_critical"] is True
            elif d["target_url"] == "https://test.org":
                assert d["has_critical"] is False

    # ── By engagement ────────────────────────────────────────────────

    def test_by_engagement_counts(self, seeded_db):
        """Engagement breakdown has correct finding counts."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        eng_map = {e["engagement_id"]: e["count"] for e in trends["by_engagement"]}
        assert eng_map[eng1["id"]] == 3
        assert eng_map[eng2["id"]] == 2

    def test_by_engagement_includes_target_url(self, seeded_db):
        """Engagement breakdown includes target_url."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        urls = {e["target_url"] for e in trends["by_engagement"]}
        assert "https://example.com" in urls
        assert "https://test.org" in urls

    # ── Over time ────────────────────────────────────────────────────

    def test_over_time_has_monthly_data(self, seeded_db):
        """Over-time data shows findings grouped by month."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        assert len(trends["over_time"]) >= 1
        for m in trends["over_time"]:
            assert "month" in m
            assert "count" in m
            assert m["count"] >= 1

    def test_over_time_includes_high_plus(self, seeded_db):
        """Over-time data includes high+critical count."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        total_high_plus = sum(m["high_plus_count"] for m in trends["over_time"])
        assert total_high_plus == 2  # 1 CRITICAL + 1 HIGH

    # ── Average confidence ───────────────────────────────────────────

    def test_avg_confidence_by_severity(self, seeded_db):
        """Average confidence is computed correctly per severity."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        conf_map = {c["severity"]: c["avg_confidence"] for c in trends["avg_confidence_by_severity"]}
        assert conf_map["CRITICAL"] == pytest.approx(0.95, abs=0.01)
        assert conf_map["HIGH"] == pytest.approx(0.80, abs=0.01)

    # ── Filter: domain ───────────────────────────────────────────────

    def test_filter_domain_exact(self, seeded_db):
        """Domain filter returns only findings for that domain."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(domain="example.com")
        assert trends["summary"]["total_findings"] == 3
        assert trends["summary"]["total_engagements"] == 1

    def test_filter_domain_partial(self, seeded_db):
        """Domain filter with partial match works."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(domain="test")
        # Only "https://test.org" matches '%test%' (example.com does not contain "test")
        assert trends["summary"]["total_findings"] == 2

    def test_filter_domain_no_match(self, seeded_db):
        """Domain filter with no match returns empty."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(domain="nonexistent.com")
        assert trends["summary"]["total_findings"] == 0

    # ── Filter: min_severity ─────────────────────────────────────────

    def test_filter_min_severity_critical(self, seeded_db):
        """min_severity=CRITICAL returns only CRITICAL findings."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(min_severity="CRITICAL")
        assert trends["summary"]["total_findings"] == 1

    def test_filter_min_severity_high(self, seeded_db):
        """min_severity=HIGH returns CRITICAL + HIGH findings."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(min_severity="HIGH")
        assert trends["summary"]["total_findings"] == 2  # 1 CRITICAL + 1 HIGH

    def test_filter_min_severity_medium(self, seeded_db):
        """min_severity=MEDIUM returns CRITICAL + HIGH + MEDIUM findings."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(min_severity="MEDIUM")
        assert trends["summary"]["total_findings"] == 4

    def test_filter_min_severity_low(self, seeded_db):
        """min_severity=LOW returns all findings (no filtering)."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(min_severity="LOW")
        assert trends["summary"]["total_findings"] == 5

    # ── Filter: last_n_days ──────────────────────────────────────────

    def test_filter_last_n_days_returns_all_for_recent(self, seeded_db):
        """last_n_days with large value returns all findings."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(last_n_days=365)
        assert trends["summary"]["total_findings"] == 5

    def test_filter_last_n_days_returns_none_for_past(self, seeded_db):
        """last_n_days with 0 returns no findings (created just now, but 0 days = no match)."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(last_n_days=0)
        assert trends["summary"]["total_findings"] == 0  # created now, not before 0 days ago

    # ── Combined filters ─────────────────────────────────────────────

    def test_filter_domain_and_severity(self, seeded_db):
        """Combined domain + severity filter works."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(domain="example.com", min_severity="HIGH")
        assert trends["summary"]["total_findings"] == 2  # CRITICAL + HIGH for example.com

    def test_filter_domain_and_severity_no_match(self, seeded_db):
        """Combined filters with no match return empty."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends(domain="test.org", min_severity="CRITICAL")
        assert trends["summary"]["total_findings"] == 0  # test.org has no CRITICAL

    # ── Edge cases ───────────────────────────────────────────────────

    def test_single_finding(self, shared_db):
        """Single finding across one engagement works."""
        eng_repo, finding_repo, trend_repo = shared_db
        eng = _seed_engagement(eng_repo, target_url="https://single.com")
        _seed_finding(finding_repo, eng["id"],
                      finding_type="TEST", severity="INFO",
                      endpoint="https://single.com/health")
        trends = trend_repo.get_trends()
        assert trends["summary"]["total_findings"] == 1
        assert trends["summary"]["total_engagements"] == 1

    def test_many_findings_same_type_different_severities(self, shared_db):
        """Multiple findings of the same type with different severities."""
        eng_repo, finding_repo, trend_repo = shared_db
        eng = _seed_engagement(eng_repo, target_url="https://multi.com")
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            _seed_finding(finding_repo, eng["id"],
                          finding_type="XSS", severity=sev,
                          endpoint=f"https://multi.com/{sev.lower()}")
        trends = trend_repo.get_trends()
        assert trends["summary"]["total_findings"] == 5
        sev_map = {s["severity"]: s["count"] for s in trends["by_severity"]}
        # Each severity appears once (5 findings, 5 different severities)
        assert len(trends["by_severity"]) == 5
        assert sev_map.get("CRITICAL") == 1
        assert sev_map.get("HIGH") == 1
        assert sev_map.get("INFO") == 1

    def test_close_is_idempotent(self):
        """close() does not raise on multiple calls."""
        repo = SQLiteTrendRepository(":memory:")
        repo.close()
        repo.close()  # second close should not raise

    def test_repo_shared_with_backend(self, tmp_path):
        """TrendRepository can share a database with backend repos."""
        db_path = str(tmp_path / "shared_test.db")
        eng_repo = SQLiteEngagementRepo(db_path)
        finding_repo = SQLiteFindingRepo(db_path)
        trend_repo = SQLiteTrendRepository(db_path)
        try:
            eng = _seed_engagement(eng_repo)
            _seed_finding(finding_repo, eng["id"])
            trends = trend_repo.get_trends()
            assert trends["summary"]["total_findings"] == 1
        finally:
            trend_repo.close()
            finding_repo.close()
            eng_repo.close()


# ── Display function tests ───────────────────────────────────────────────


class TestDisplayTrendSummary:
    """Tests for display_trend_summary()."""

    def test_empty_database(self, shared_db):
        """display_trend_summary handles empty results gracefully."""
        eng_repo, finding_repo, trend_repo = shared_db
        trends = trend_repo.get_trends()
        output = display_trend_summary(trends)
        assert "No findings found" in output

    def test_contains_cross_engagement_header(self, seeded_db):
        """Output includes the header title."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        output = display_trend_summary(trends)
        assert "Cross-Engagement Trend Analysis" in output

    def test_contains_total_findings(self, seeded_db):
        """Output shows total findings count."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        output = display_trend_summary(trends)
        assert "5" in output or "Total findings" in output

    def test_contains_severity_breakdown(self, seeded_db):
        """Output includes severity breakdown section."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        output = display_trend_summary(trends)
        assert "Severity" in output

    def test_verbose_shows_more_sections(self, seeded_db):
        """Verbose mode shows domain and engagement sections."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        verbose_output = display_trend_summary(trends, verbose=True)
        brief_output = display_trend_summary(trends, verbose=False)
        # Verbose output should have more content
        assert len(verbose_output) >= len(brief_output)

    def test_uses_ascii_only(self, seeded_db):
        """Output uses only ASCII characters (no unicode issues on Windows)."""
        eng_repo, finding_repo, trend_repo, eng1, eng2 = seeded_db
        trends = trend_repo.get_trends()
        output = display_trend_summary(trends, verbose=True)
        # Try encoding as ASCII — should not raise
        encoded = output.encode("ascii", errors="strict")
        assert len(encoded) > 0

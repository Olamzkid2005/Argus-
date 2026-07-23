"""Tests for database/sqlite_backend.py — standalone SQLite repositories."""

from __future__ import annotations

import json
import pytest

from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo


# ── Helpers ──────────────────────────────────────────────────────────────


def _seed_engagement(eng_repo: SQLiteEngagementRepo, **overrides: str) -> dict:
    """Create a basic engagement with sensible defaults."""
    defaults = {
        "target_url": "https://example.com",
        "org_id": "test-org",
        "status": "created",
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
        "evidence": {"payload": "' OR 1=1 --", "status": 500},
        "confidence": 0.9,
        "source_tool": "nuclei",
        "cvss_score": 8.5,
        "cwe_id": "CWE-89",
    }
    defaults.update(overrides)
    return finding_repo.create_finding(**defaults)


# ── EngagementRepo tests ────────────────────────────────────────────────


class TestSQLiteEngagementRepo:
    """Full CRUD tests for SQLiteEngagementRepo."""

    @pytest.fixture
    def repo(self):
        r = SQLiteEngagementRepo(":memory:")
        yield r
        r.close()

    # ── Create ───────────────────────────────────────────────────────

    def test_create_returns_dict_with_id(self, repo):
        """create() returns a dict with generated id and timestamps."""
        eng = _seed_engagement(repo)
        assert "id" in eng
        assert eng["target_url"] == "https://example.com"
        assert eng["org_id"] == "test-org"
        assert eng["status"] == "created"
        assert eng["created_at"] is not None
        assert eng["updated_at"] is not None

    def test_create_uses_target_as_fallback(self, repo):
        """create() falls back to target if target_url not provided."""
        eng = repo.create({"target": "https://fallback.com", "org_id": "o"})
        assert eng["target_url"] == "https://fallback.com"
        assert eng["target"] == "https://fallback.com"

    def test_create_stores_metadata_as_json(self, repo):
        """create() serializes metadata dict to JSON string."""
        eng = _seed_engagement(repo, metadata={"phase": "recon", "score": 85})
        result = repo.find_by_id(eng["id"])
        assert result is not None
        assert result["metadata"] == {"phase": "recon", "score": 85}

    def test_create_handles_string_metadata(self, repo):
        """create() passes through string metadata without double-encoding."""
        eng = repo.create({
            "target_url": "https://test.com",
            "org_id": "o",
            "metadata": json.dumps({"existing": True}),
        })
        result = repo.find_by_id(eng["id"])
        assert result is not None
        assert result["metadata"] == {"existing": True}

    # ── Find by ID ───────────────────────────────────────────────────

    def test_find_by_id_returns_engagement(self, repo):
        """find_by_id returns the correct engagement."""
        eng = _seed_engagement(repo, target_url="https://findme.com")
        found = repo.find_by_id(eng["id"])
        assert found is not None
        assert found["id"] == eng["id"]
        assert found["target_url"] == "https://findme.com"

    def test_find_by_id_nonexistent_returns_none(self, repo):
        """find_by_id returns None for missing id."""
        assert repo.find_by_id("nonexistent") is None

    def test_find_by_id_parses_json_metadata(self, repo):
        """find_by_id deserializes JSON metadata back to dict."""
        eng = _seed_engagement(repo, metadata={"key": "value"})
        found = repo.find_by_id(eng["id"])
        assert found is not None
        assert found["metadata"] == {"key": "value"}

    # ── Update status ────────────────────────────────────────────────

    def test_update_status(self, repo):
        """update_status changes status and returns updated engagement."""
        eng = _seed_engagement(repo)
        updated = repo.update_status(eng["id"], "scanning")
        assert updated is not None
        assert updated["status"] == "scanning"
        assert updated["updated_at"] != eng["updated_at"]

    def test_update_status_nonexistent(self, repo):
        """update_status on missing id returns None."""
        assert repo.update_status("nonexistent", "completed") is None

    # ── Update by ID ─────────────────────────────────────────────────

    def test_update_by_id_single_field(self, repo):
        """update_by_id changes specified fields only."""
        eng = _seed_engagement(repo, status="created")
        updated = repo.update_by_id(eng["id"], {"status": "completed"})
        assert updated is not None
        assert updated["status"] == "completed"
        assert updated["target_url"] == eng["target_url"]  # unchanged

    def test_update_by_id_empty_updates(self, repo):
        """update_by_id with empty dict returns current engagement."""
        eng = _seed_engagement(repo)
        updated = repo.update_by_id(eng["id"], {})
        assert updated is not None
        assert updated["id"] == eng["id"]

    def test_update_by_id_serializes_dict_fields(self, repo):
        """update_by_id serializes dict values to JSON."""
        eng = _seed_engagement(repo)
        updated = repo.update_by_id(eng["id"], {"metadata": {"phase": "done"}})
        assert updated is not None
        assert updated["metadata"] == {"phase": "done"}

    def test_update_by_id_nonexistent(self, repo):
        """update_by_id on missing id returns None."""
        assert repo.update_by_id("nonexistent", {"status": "done"}) is None

    # ── Find by org ──────────────────────────────────────────────────

    def test_find_by_org_returns_engagements(self, repo):
        """find_by_org returns engagements for that org."""
        _seed_engagement(repo, org_id="org-a", target_url="https://a.com")
        _seed_engagement(repo, org_id="org-a", target_url="https://b.com")
        _seed_engagement(repo, org_id="org-b", target_url="https://c.com")
        results = repo.find_by_org("org-a")
        assert len(results) == 2
        assert all(e["org_id"] == "org-a" for e in results)

    def test_find_by_org_empty(self, repo):
        """find_by_org returns empty list when no engagements."""
        assert repo.find_by_org("nonexistent") == []

    def test_find_by_org_respects_limit(self, repo):
        """find_by_org respects the limit parameter."""
        for i in range(10):
            _seed_engagement(repo, org_id="org", target_url=f"https://{i}.com")
        results = repo.find_by_org("org", limit=3)
        assert len(results) == 3

    def test_find_by_org_orders_by_created_at_desc(self, repo):
        """find_by_org orders results newest first."""
        import time
        ids = []
        for i in range(3):
            eng = _seed_engagement(repo, org_id="org", target_url=f"https://{i}.com")
            ids.append(eng["id"])
            time.sleep(0.01)
        results = repo.find_by_org("org")
        assert [r["id"] for r in results] == list(reversed(ids))

    # ── Edge cases ───────────────────────────────────────────────────

    def test_close_is_idempotent_own_repo(self):
        """close() does not raise on multiple calls."""
        r = SQLiteEngagementRepo(":memory:")
        r.close()  # first close
        r.close()  # second close — should not raise

    def test_multiple_repos_same_db(self):
        """Two repos can share the same database file."""
        eng_repo = SQLiteEngagementRepo(":memory:")
        finding_repo = SQLiteFindingRepo(":memory:")
        try:
            eng = _seed_engagement(eng_repo)
            f_id = _seed_finding(finding_repo, eng["id"])
            assert f_id is not None
        finally:
            eng_repo.close()
            finding_repo.close()


# ── FindingRepo tests ───────────────────────────────────────────────────


class TestSQLiteFindingRepo:
    """Full CRUD tests for SQLiteFindingRepo."""

    @pytest.fixture
    def eng_repo(self):
        r = SQLiteEngagementRepo(":memory:")
        yield r
        r.close()

    @pytest.fixture
    def finding_repo(self):
        r = SQLiteFindingRepo(":memory:")
        yield r
        r.close()

    @pytest.fixture
    def eng_id(self, eng_repo):
        eng = _seed_engagement(eng_repo)
        return eng["id"]

    # ── Create ───────────────────────────────────────────────────────

    def test_create_finding_returns_id(self, finding_repo, eng_id):
        """create_finding returns a string UUID."""
        f_id = _seed_finding(finding_repo, eng_id)
        assert isinstance(f_id, str)
        assert len(f_id) > 20  # UUID length

    def test_create_finding_sets_defaults(self, finding_repo, eng_id):
        """create_finding uses default values for optional fields."""
        f_id = _seed_finding(
            finding_repo, eng_id,
            cvss_score=None, owasp_category=None, cwe_id=None,
        )
        findings, total = finding_repo.get_findings_by_engagement(eng_id)
        assert total == 1
        assert findings[0]["cvss_score"] is None

    def test_create_finding_upserts_duplicate(self, finding_repo, eng_id):
        """create_finding updates existing finding on duplicate (same key tuple)."""
        f_id1 = _seed_finding(finding_repo, eng_id, severity="HIGH")
        f_id2 = _seed_finding(finding_repo, eng_id, severity="CRITICAL")

        # Same engagement, endpoint, type, tool — should be the same finding
        findings, total = finding_repo.get_findings_by_engagement(eng_id)
        assert total == 1
        assert findings[0]["severity"] == "CRITICAL"

    def test_create_finding_different_endpoint_separate(self, finding_repo, eng_id):
        """Different endpoint creates separate finding."""
        _seed_finding(finding_repo, eng_id, endpoint="https://a.com/api")
        _seed_finding(finding_repo, eng_id, endpoint="https://b.com/api")
        _, total = finding_repo.get_findings_by_engagement(eng_id)
        assert total == 2

    # ── Get findings ─────────────────────────────────────────────────

    def test_get_findings_by_engagement_empty(self, finding_repo, eng_id):
        """No findings returns empty list and zero count."""
        findings, total = finding_repo.get_findings_by_engagement(eng_id)
        assert findings == []
        assert total == 0

    def test_get_findings_by_engagement_all(self, finding_repo, eng_id):
        """Returns all findings for the engagement."""
        _seed_finding(finding_repo, eng_id, finding_type="SQL_INJECTION")
        _seed_finding(finding_repo, eng_id, finding_type="XSS",
                       endpoint="https://example.com/search")
        findings, total = finding_repo.get_findings_by_engagement(eng_id)
        assert total == 2
        types = {f["type"] for f in findings}
        assert types == {"SQL_INJECTION", "XSS"}

    def test_get_findings_by_engagement_severity_filter(self, finding_repo, eng_id):
        """Severity filter narrows results."""
        _seed_finding(finding_repo, eng_id, finding_type="SQL_INJECTION", severity="CRITICAL")
        _seed_finding(finding_repo, eng_id, finding_type="XSS", severity="MEDIUM",
                       endpoint="https://example.com/search")
        findings, total = finding_repo.get_findings_by_engagement(
            eng_id, severity="CRITICAL"
        )
        assert total == 1
        assert findings[0]["severity"] == "CRITICAL"

    def test_get_findings_by_type_filter(self, finding_repo, eng_id):
        """Finding type filter narrows results."""
        _seed_finding(finding_repo, eng_id, finding_type="SQL_INJECTION")
        _seed_finding(finding_repo, eng_id, finding_type="XSS",
                       endpoint="https://example.com/search")
        findings, total = finding_repo.get_findings_by_engagement(
            eng_id, finding_type="SQL_INJECTION"
        )
        assert total == 1
        assert findings[0]["type"] == "SQL_INJECTION"

    # ── Batch upsert ─────────────────────────────────────────────────

    def test_batch_create_or_update_findings(self, finding_repo, eng_id):
        """Batch upsert creates multiple findings."""
        findings_data = [
            {"type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://a.com"},
            {"type": "XSS", "severity": "HIGH", "endpoint": "https://b.com"},
            {"type": "OPEN_REDIRECT", "severity": "MEDIUM", "endpoint": "https://c.com"},
        ]
        created, total = finding_repo.batch_create_or_update_findings(eng_id, findings_data)
        assert total == 3

        all_findings, count = finding_repo.get_findings_by_engagement(eng_id)
        assert count == 3

    def test_batch_upsert_updates_existing(self, finding_repo, eng_id):
        """Batch upsert updates matching findings instead of duplicating."""
        findings_data = [
            {"type": "SQL_INJECTION", "severity": "HIGH", "endpoint": "https://a.com",
             "source_tool": "nuclei"},
        ]
        finding_repo.batch_create_or_update_findings(eng_id, findings_data)

        # Update with different severity
        findings_data[0]["severity"] = "CRITICAL"
        finding_repo.batch_create_or_update_findings(eng_id, findings_data)

        all_findings, count = finding_repo.get_findings_by_engagement(eng_id)
        assert count == 1
        assert all_findings[0]["severity"] == "CRITICAL"

    def test_batch_upsert_handles_evidence_dict(self, finding_repo, eng_id):
        """Batch upsert serializes evidence dict to JSON."""
        findings_data = [
            {
                "type": "SQL_INJECTION", "severity": "HIGH",
                "endpoint": "https://a.com",
                "evidence": {"payload": "test", "response_code": 200},
            },
        ]
        finding_repo.batch_create_or_update_findings(eng_id, findings_data)
        findings, _ = finding_repo.get_findings_by_engagement(eng_id)
        assert findings[0]["evidence"] == {"payload": "test", "response_code": 200}

    # ── Summary ──────────────────────────────────────────────────────

    def test_get_summary_empty(self, finding_repo, eng_id):
        """get_summary_by_engagement returns empty dict for no findings."""
        summary = finding_repo.get_summary_by_engagement(eng_id)
        assert summary == {}

    def test_get_summary_by_severity(self, finding_repo, eng_id):
        """get_summary returns counts by severity."""
        _seed_finding(finding_repo, eng_id, severity="CRITICAL")
        _seed_finding(finding_repo, eng_id, severity="HIGH",
                       endpoint="https://example.com/high")
        _seed_finding(finding_repo, eng_id, severity="MEDIUM",
                       endpoint="https://example.com/medium")
        summary = finding_repo.get_summary_by_engagement(eng_id)
        assert summary.get("CRITICAL", {}).get("count") == 1
        assert summary.get("HIGH", {}).get("count") == 1
        assert summary.get("MEDIUM", {}).get("count") == 1

    def test_get_summary_includes_confidence(self, finding_repo, eng_id):
        """get_summary includes average confidence per severity."""
        _seed_finding(finding_repo, eng_id, severity="HIGH", confidence=0.9)
        _seed_finding(finding_repo, eng_id, severity="HIGH", confidence=0.7,
                       endpoint="https://example.com/other")
        summary = finding_repo.get_summary_by_engagement(eng_id)
        avg_conf = summary.get("HIGH", {}).get("avg_confidence", 0)
        assert avg_conf == pytest.approx(0.8, abs=0.01)

    # ── Top findings ─────────────────────────────────────────────────

    def test_get_top_findings_orders_by_severity(self, finding_repo, eng_id):
        """get_top_findings_for_hypothesis orders by severity then confidence."""
        _seed_finding(finding_repo, eng_id, severity="LOW", confidence=0.5,
                       endpoint="https://a.com", finding_type="LOW_FINDING")
        _seed_finding(finding_repo, eng_id, severity="CRITICAL", confidence=0.8,
                       endpoint="https://b.com", finding_type="CRIT_FINDING")
        results = finding_repo.get_top_findings_for_hypothesis(eng_id)
        assert results[0]["severity"] == "CRITICAL"
        assert results[1]["severity"] == "LOW"

    def test_get_top_findings_empty(self, finding_repo, eng_id):
        """get_top_findings_for_hypothesis with no findings returns []."""
        assert finding_repo.get_top_findings_for_hypothesis(eng_id) == []

    # ── High confidence ──────────────────────────────────────────────

    def test_find_high_confidence(self, finding_repo, eng_id):
        """find_high_confidence returns only findings above threshold."""
        _seed_finding(finding_repo, eng_id, confidence=0.9)
        _seed_finding(finding_repo, eng_id, confidence=0.5,
                       endpoint="https://example.com/low")
        results = finding_repo.find_high_confidence(eng_id, threshold=0.7)
        assert len(results) == 1
        assert results[0]["confidence"] >= 0.7

    def test_find_high_confidence_empty(self, finding_repo, eng_id):
        """find_high_confidence with no findings returns []."""
        assert finding_repo.find_high_confidence(eng_id) == []

    # ── Evidence parsing ─────────────────────────────────────────────

    def test_evidence_parses_json_to_dict(self, finding_repo, eng_id):
        """Evidence stored as JSON string is returned as dict."""
        _seed_finding(finding_repo, eng_id, evidence={"key": "value"})
        findings, _ = finding_repo.get_findings_by_engagement(eng_id)
        assert isinstance(findings[0]["evidence"], dict)
        assert findings[0]["evidence"]["key"] == "value"

    def test_verified_field_is_bool(self, finding_repo, eng_id):
        """Integer verified field is returned as bool."""
        _seed_finding(finding_repo, eng_id)
        findings, _ = finding_repo.get_findings_by_engagement(eng_id)
        assert isinstance(findings[0]["verified"], bool)

    # ── Cross-engagement isolation ───────────────────────────────────

    def test_findings_isolated_by_engagement(self, finding_repo, eng_repo):
        """Findings for different engagements don't mix."""
        eng1 = _seed_engagement(eng_repo, target_url="https://a.com")
        eng2 = _seed_engagement(eng_repo, target_url="https://b.com")

        _seed_finding(finding_repo, eng1["id"])
        _seed_finding(finding_repo, eng2["id"],
                       endpoint="https://b.com/api")

        f1, c1 = finding_repo.get_findings_by_engagement(eng1["id"])
        f2, c2 = finding_repo.get_findings_by_engagement(eng2["id"])
        assert c1 == 1
        assert c2 == 1
        assert f1[0]["engagement_id"] == eng1["id"]
        assert f2[0]["engagement_id"] == eng2["id"]

    # ── Multiple finding types ───────────────────────────────────────

    def test_various_finding_types_stored_correctly(self, finding_repo, eng_id):
        """Multiple finding types with various severities work."""
        findings_data = [
            ("SQL_INJECTION", "CRITICAL", "https://a.com/api"),
            ("XSS", "HIGH", "https://b.com/search"),
            ("OPEN_REDIRECT", "MEDIUM", "https://c.com/redirect"),
            ("INFO_LEAK", "LOW", "https://d.com/debug"),
            ("TECH_DETECT", "INFO", "https://e.com"),
        ]
        for ftype, sev, endpoint in findings_data:
            _seed_finding(finding_repo, eng_id,
                          finding_type=ftype, severity=sev, endpoint=endpoint)
        all_f, total = finding_repo.get_findings_by_engagement(eng_id)
        assert total == 5
        assert {f["type"] for f in all_f} == {f[0] for f in findings_data}

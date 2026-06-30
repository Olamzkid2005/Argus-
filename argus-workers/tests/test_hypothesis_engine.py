"""
Unit tests for the Hypothesis Engine module.

Tests cover:
- generate() with empty findings
- generate() with grouped findings (XSS by host, SQLi by parameter)
- Single-finding hypothesis generation for HIGH/CRITICAL findings
- Suggested tool mapping
- Feature flag disabled behavior
- EngagementState hypothesis methods
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.hypothesis_engine import HypothesisEngine, _extract_cwe, _extract_parameters, _group_findings_for_hypotheses


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_XSS_FINDING_1 = {
    "id": "f1",
    "type": "REFLECTED_XSS",
    "severity": "HIGH",
    "endpoint": "https://example.com/search?q=test",
    "confidence": 0.8,
    "evidence": {"payload": "<script>alert(1)</script>", "param": "q"},
}

SAMPLE_XSS_FINDING_2 = {
    "id": "f2",
    "type": "STORED_XSS",
    "severity": "MEDIUM",
    "endpoint": "https://example.com/profile",
    "confidence": 0.6,
    "evidence": {"payload": "<img src=x onerror=alert(1)>", "param": "name"},
}

SAMPLE_SQLI_FINDING_1 = {
    "id": "f3",
    "type": "SQL_INJECTION",
    "severity": "CRITICAL",
    "endpoint": "https://example.com/api/search?id=1",
    "confidence": 0.9,
    "cwe_id": "89",
    "evidence": {"parameter": "id", "payload": "' OR 1=1 --"},
}

SAMPLE_SQLI_FINDING_2 = {
    "id": "f4",
    "type": "BLIND_SQLI",
    "severity": "HIGH",
    "endpoint": "https://example.com/api/items?category=1",
    "confidence": 0.7,
    "cwe_id": "89",
    "evidence": {"parameter": "category", "payload": "1 AND 1=1"},
}

SAMPLE_LONE_CRITICAL = {
    "id": "f5",
    "type": "SSRF",
    "severity": "CRITICAL",
    "endpoint": "https://example.com/fetch?url=http://internal",
    "confidence": 0.95,
    "evidence": {"parameter": "url", "response": "meta-data"},
}


# ── Test: _group_findings_for_hypotheses ──────────────────────────────


class TestGroupFindingsForHypotheses:
    def test_empty_findings(self):
        """Empty findings produce no groups."""
        assert _group_findings_for_hypotheses([]) == []

    def test_single_finding_no_group(self):
        """Single finding does not produce a group (min_group_size=2)."""
        groups = _group_findings_for_hypotheses([SAMPLE_XSS_FINDING_1])
        assert len(groups) == 0

    def test_group_by_cwe(self):
        """Two SQLi findings with same CWE produce a CWE group."""
        groups = _group_findings_for_hypotheses(
            [SAMPLE_SQLI_FINDING_1, SAMPLE_SQLI_FINDING_2]
        )
        cwe_groups = [g for g in groups if g["category"] == "cwe"]
        assert len(cwe_groups) >= 1
        assert cwe_groups[0]["common_cwe"] == "89"


# ── Test: HypothesisEngine.generate() ─────────────────────────────────


class TestHypothesisEngineGenerate:
    def test_empty_findings(self, monkeypatch):
        """Empty findings produce no hypotheses."""
        monkeypatch.setattr(
            "feature_flags.is_enabled", lambda flag, default=False: True
        )
        engine = HypothesisEngine()
        hypotheses = engine.generate([], "eng-1")
        assert hypotheses == []

    def test_feature_flag_disabled(self, monkeypatch):
        """When feature flag is off, return empty list."""
        monkeypatch.setattr(
            "feature_flags.is_enabled", lambda flag, default=False: False
        )
        engine = HypothesisEngine()
        hypotheses = engine.generate(
            [SAMPLE_XSS_FINDING_1, SAMPLE_XSS_FINDING_2], "eng-1"
        )
        assert hypotheses == []

    def test_generates_grouped_hypothesis(self, monkeypatch):
        """Two XSS findings on same host produce a grouped hypothesis."""
        monkeypatch.setattr(
            "feature_flags.is_enabled", lambda flag, default=False: True
        )
        engine = HypothesisEngine()
        # Both XSS findings share the same host
        findings = [
            SAMPLE_XSS_FINDING_1,
            {**SAMPLE_XSS_FINDING_2, "endpoint": "https://example.com/other"},
        ]
        hypotheses = engine.generate(findings, "eng-1")
        assert len(hypotheses) >= 1
        h = hypotheses[0]
        assert h["engagement_id"] == "eng-1"
        assert h["status"] == "UNVERIFIED"
        assert isinstance(h["confidence"], float)
        assert 0 <= h["confidence"] <= 1.0
        assert "finding_ids" in h
        assert "verification_steps" in h
        assert "suggested_tools" in h

    def test_single_critical_generates_hypothesis(self, monkeypatch):
        """A lone CRITICAL SSRF finding produces a single-finding hypothesis."""
        monkeypatch.setattr(
            "feature_flags.is_enabled", lambda flag, default=False: True
        )
        engine = HypothesisEngine()
        hypotheses = engine.generate([SAMPLE_LONE_CRITICAL], "eng-1")
        assert len(hypotheses) >= 1
        # Should have a single-finding hypothesis
        single = [h for h in hypotheses if h.get("source_finding_id") == "f5"]
        assert len(single) >= 1
        assert single[0]["status"] == "UNVERIFIED"
        assert "SSRF" in single[0]["description"]

    def test_suggested_tools_mapping(self, monkeypatch):
        """XSS hypothesis suggests finding_verifier/verification_agent."""
        monkeypatch.setattr(
            "feature_flags.is_enabled", lambda flag, default=False: True
        )
        engine = HypothesisEngine()
        findings = [
            {**SAMPLE_XSS_FINDING_1, "endpoint": "https://example.com/a"},
            {**SAMPLE_XSS_FINDING_2, "endpoint": "https://example.com/b"},
        ]
        hypotheses = engine.generate(findings, "eng-1")
        # Check grouped hypothesis suggested_tools
        for h in hypotheses:
            if h.get("root_cause_key"):
                tools = h.get("suggested_tools", [])
                assert any("verification" in t for t in tools)

    def test_hypothesis_has_required_fields(self, monkeypatch):
        """Each hypothesis has all required TypedDict fields."""
        monkeypatch.setattr(
            "feature_flags.is_enabled", lambda flag, default=False: True
        )
        engine = HypothesisEngine()
        findings = [
            SAMPLE_SQLI_FINDING_1,
            SAMPLE_SQLI_FINDING_2,
        ]
        hypotheses = engine.generate(findings, "eng-1")
        for h in hypotheses:
            assert h["id"]
            assert h["description"]
            assert h["engagement_id"] == "eng-1"
            assert isinstance(h["confidence"], float)
            assert h["status"] in ("UNVERIFIED", "CONFIRMED", "REJECTED")
            assert isinstance(h["finding_ids"], list)
            assert isinstance(h["supporting_finding_ids"], list)
            assert isinstance(h["refuting_finding_ids"], list)
            assert isinstance(h["suggested_tools"], list)
            assert isinstance(h["verification_steps"], list)


# ── Test: _extract_cwe / _extract_parameters ──────────────────────────


class TestExtractHelpers:
    def test_extract_cwe_from_field(self):
        assert _extract_cwe({"cwe_id": "89"}) == "89"
        assert _extract_cwe({"cwe_id": "CWE-79"}) == "79"
        assert _extract_cwe({"cwe": "22"}) == "22"

    def test_extract_cwe_from_evidence(self):
        f = {"evidence": {"cwe": "89"}}
        assert _extract_cwe(f) == "89"

    def test_extract_cwe_none(self):
        assert _extract_cwe({}) is None

    def test_extract_parameters(self):
        f = {"evidence": {"parameter": "id", "payload": "test"}}
        params = _extract_parameters(f)
        assert "id" in params

    def test_extract_parameters_multiple(self):
        f = {"evidence": {"parameters": ["q", "page"], "param": "sort"}}
        params = _extract_parameters(f)
        assert "q" in params
        assert "page" in params
        assert "sort" in params

    def test_extract_parameters_empty(self):
        assert _extract_parameters({}) == []


# ── Test: EngagementState hypothesis methods ──────────────────────────


class TestEngagementStateHypotheses:
    def test_add_and_get_active_hypotheses(self):
        """Adding a hypothesis and retrieving active ones works."""
        from runtime.engagement_state import EngagementState

        state = EngagementState("eng-1")
        state.add_hypothesis({
            "id": "h1",
            "description": "Test hypothesis",
            "status": "UNVERIFIED",
            "confidence": 0.8,
            "finding_ids": [],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": [],
            "verification_steps": [],
        })
        active = state.get_active_hypotheses(max_count=10)
        assert len(active) == 1
        assert active[0]["id"] == "h1"

    def test_get_active_filters_by_status(self):
        """Only UNVERIFIED hypotheses are returned as active."""
        from runtime.engagement_state import EngagementState

        state = EngagementState("eng-1")
        state.add_hypothesis({
            "id": "h1",
            "status": "UNVERIFIED",
            "confidence": 0.7,
            "description": "Active",
            "finding_ids": [],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": [],
            "verification_steps": [],
        })
        state.add_hypothesis({
            "id": "h2",
            "status": "CONFIRMED",
            "confidence": 0.9,
            "description": "Done",
            "finding_ids": [],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": [],
            "verification_steps": [],
        })
        active = state.get_active_hypotheses(max_count=10)
        assert len(active) == 1
        assert active[0]["id"] == "h1"

    def test_update_hypothesis(self):
        """Updating a hypothesis in-memory works."""
        from runtime.engagement_state import EngagementState

        state = EngagementState("eng-1")
        state.add_hypothesis({
            "id": "h1",
            "description": "Test",
            "status": "UNVERIFIED",
            "confidence": 0.5,
            "finding_ids": [],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": [],
            "verification_steps": [],
        })
        result = state.update_hypothesis("h1", {"status": "CONFIRMED", "confidence": 0.9})
        assert result is True
        assert state.hypotheses[0]["status"] == "CONFIRMED"
        assert state.hypotheses[0]["confidence"] == 0.9

    def test_update_hypothesis_not_found(self):
        """Updating a non-existent hypothesis returns False."""
        from runtime.engagement_state import EngagementState

        state = EngagementState("eng-1")
        result = state.update_hypothesis("nonexistent", {"status": "CONFIRMED"})
        assert result is False

    def test_get_active_hypotheses_sorts_by_confidence(self):
        """Active hypotheses are returned sorted by confidence descending."""
        from runtime.engagement_state import EngagementState

        state = EngagementState("eng-1")
        for i, conf in enumerate([0.3, 0.9, 0.6]):
            state.add_hypothesis({
                "id": f"h{i}",
                "description": f"Hyp {i}",
                "status": "UNVERIFIED",
                "confidence": conf,
                "finding_ids": [],
                "supporting_finding_ids": [],
                "refuting_finding_ids": [],
                "suggested_tools": [],
                "verification_steps": [],
            })
        active = state.get_active_hypotheses(max_count=10)
        confidences = [h["confidence"] for h in active]
        assert confidences == sorted(confidences, reverse=True)

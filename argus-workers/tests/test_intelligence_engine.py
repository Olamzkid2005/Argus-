"""
Tests for Intelligence Engine
"""

from unittest.mock import MagicMock

import pytest

from intelligence_engine import IntelligenceEngine


class TestIntelligenceEngine:
    """Test suite for IntelligenceEngine"""

    def setup_method(self):
        """Setup test fixtures"""
        self.engine = IntelligenceEngine()

    def test_calculate_tool_agreement_single_tool(self):
        """Test tool agreement for single tool"""
        findings = [{"source_tool": "nuclei"}]

        agreement = self.engine._calculate_tool_agreement(findings)

        assert agreement == 0.7

    def test_calculate_tool_agreement_two_tools(self):
        """Test tool agreement for two tools"""
        findings = [{"source_tool": "nuclei"}, {"source_tool": "sqlmap"}]

        agreement = self.engine._calculate_tool_agreement(findings)

        assert agreement == 0.85

    def test_calculate_tool_agreement_three_plus_tools(self):
        """Test tool agreement for three or more tools"""
        findings = [
            {"source_tool": "nuclei"},
            {"source_tool": "sqlmap"},
            {"source_tool": "burp"},
        ]

        agreement = self.engine._calculate_tool_agreement(findings)

        assert agreement == 1.0

    def test_get_evidence_strength_verified(self):
        """Test evidence strength for verified findings"""
        finding = {"evidence_strength": "VERIFIED"}

        strength = self.engine._get_evidence_strength(finding)

        assert strength == 1.0

    def test_get_evidence_strength_request_response(self):
        """Test evidence strength for request/response"""
        finding = {"evidence_strength": "REQUEST_RESPONSE"}

        strength = self.engine._get_evidence_strength(finding)

        assert strength == 0.9

    def test_get_evidence_strength_payload(self):
        """Test evidence strength for payload"""
        finding = {"evidence_strength": "PAYLOAD"}

        strength = self.engine._get_evidence_strength(finding)

        assert strength == 0.8

    def test_get_evidence_strength_minimal(self):
        """Test evidence strength for minimal evidence"""
        finding = {"evidence_strength": "MINIMAL"}

        strength = self.engine._get_evidence_strength(finding)

        assert strength == 0.6

    def test_detect_low_coverage_with_few_endpoints(self):
        """Test low coverage detection with few endpoints"""
        findings = [
            {"endpoint": "https://example.com/1"},
            {"endpoint": "https://example.com/2"},
        ]

        assert self.engine.detect_low_coverage(findings) is True

    def test_detect_low_coverage_with_many_endpoints(self):
        """Test low coverage detection with many endpoints"""
        findings = [{"endpoint": f"https://example.com/{i}"} for i in range(10)]

        assert self.engine.detect_low_coverage(findings) is False

    def test_detect_high_value_targets_with_critical(self):
        """Test high value target detection with CRITICAL severity"""
        findings = [{"severity": "CRITICAL", "endpoint": "https://example.com/api"}]

        assert self.engine.detect_high_value_targets(findings) is True

    def test_detect_high_value_targets_with_high(self):
        """Test high value target detection with HIGH severity"""
        findings = [{"severity": "HIGH", "endpoint": "https://example.com/api"}]

        assert self.engine.detect_high_value_targets(findings) is True

    def test_detect_high_value_targets_without_critical_or_high(self):
        """Test high value target detection without CRITICAL/HIGH"""
        findings = [{"severity": "MEDIUM", "endpoint": "https://example.com/api"}]

        assert self.engine.detect_high_value_targets(findings) is False

    def test_detect_weak_auth_signals_with_auth_keyword(self):
        """Test weak auth signal detection with auth keywords"""
        findings = [
            {"type": "BROKEN_AUTHENTICATION", "endpoint": "https://example.com/login"}
        ]

        assert self.engine.detect_weak_auth_signals(findings) is True

    def test_detect_weak_auth_signals_without_auth_keyword(self):
        """Test weak auth signal detection without auth keywords"""
        findings = [{"type": "XSS", "endpoint": "https://example.com/page"}]

        assert self.engine.detect_weak_auth_signals(findings) is False

    def test_detect_low_coverage_triggers_recon_expand(self):
        """Test that low coverage detection can be used by analyze_state()"""
        findings = [{"endpoint": "https://example.com/1", "severity": "INFO"}]

        assert self.engine.detect_low_coverage(findings) is True
        gaps = self.engine.suggest_new_targets(findings)
        assert len(gaps) > 0

    def test_detect_high_value_triggers_deep_scan(self):
        """Test that high value detection can be used by analyze_state()"""
        findings = [{"endpoint": "https://example.com/api", "severity": "CRITICAL"}]

        assert self.engine.detect_high_value_targets(findings) is True
        endpoints = self.engine.get_priority_endpoints(findings)
        assert len(endpoints) > 0

    def test_evaluate_returns_scored_findings_and_analysis(self):
        """Test that evaluate returns scored findings and analysis"""
        snapshot = {
            "findings": [
                {
                    "type": "XSS",
                    "endpoint": "https://example.com/api",
                    "severity": "HIGH",
                    "evidence_strength": "PAYLOAD",
                    "fp_likelihood": 0.15,
                    "source_tool": "nuclei",
                }
            ],
            "loop_budget": {},
            "attack_graph": {},
            "engagement_state": {},
        }

        result = self.engine.evaluate(snapshot)

        assert "scored_findings" in result
        assert "analysis" in result
        assert "reasoning" in result
        assert len(result["scored_findings"]) == 1

    def test_analyze_state_independent(self):
        """Test analyze_state works independently (without pre-enriched findings)"""

        class FakeState:
            findings = [
                {"type": "XSS", "endpoint": "https://example.com", "severity": "HIGH"}
            ]
            execution_iteration = 1

        analysis = self.engine.analyze_state(FakeState())

        assert "risk_level" in analysis
        assert "coverage_gaps" in analysis
        assert "reasoning" in analysis

    # ── Tool accuracy computation tests (Blocker #2 Phase 3) ──

    def test_compute_tool_accuracy_returns_empty_without_org_id(self):
        """No org_id means no tool accuracy computation."""
        scored = [{"source_tool": "nuclei", "fp_likelihood": 0.15}]

        result = self.engine._compute_tool_accuracy(scored, org_id="")

        assert result == {}

    def test_compute_tool_accuracy_returns_empty_without_findings(self):
        """Empty scored_findings means no rates to compute."""
        result = self.engine._compute_tool_accuracy([], org_id="org-1")

        assert result == {}

    def test_compute_tool_accuracy_skips_findings_missing_source_tool(self):
        """Findings without source_tool are silently skipped."""
        scored = [
            {"source_tool": "", "fp_likelihood": 0.15},
            {"fp_likelihood": 0.20},
        ]

        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert result == {}

    def test_compute_tool_accuracy_skips_findings_missing_fp_likelihood(self):
        """Findings without fp_likelihood are silently skipped."""
        scored = [
            {"source_tool": "nuclei", "fp_likelihood": 0.15},
            {"source_tool": "sqlmap"},
        ]

        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert result == {"nuclei": 0.15}

    def test_compute_tool_accuracy_averages_per_tool(self):
        """Multiple findings from the same tool are averaged."""
        scored = [
            {"source_tool": "nuclei", "fp_likelihood": 0.1},
            {"source_tool": "nuclei", "fp_likelihood": 0.3},
            {"source_tool": "sqlmap", "fp_likelihood": 0.05},
        ]

        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert result["nuclei"] == pytest.approx(0.2)  # (0.1 + 0.3) / 2
        assert result["sqlmap"] == 0.05

    def test_compute_tool_accuracy_ignores_invalid_fp_values(self):
        """Non-numeric or out-of-range fp_likelihood values are ignored."""
        scored = [
            {"source_tool": "nuclei", "fp_likelihood": 0.15},
            {"source_tool": "nuclei", "fp_likelihood": "invalid"},
            {"source_tool": "nuclei", "fp_likelihood": -0.5},
            {"source_tool": "nuclei", "fp_likelihood": 1.5},
        ]

        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert result["nuclei"] == 0.15  # Only the valid one counted

    def test_compute_tool_accuracy_persists_via_repository(self, monkeypatch):
        """The computed rates are persisted via ToolAccuracyRepository."""
        mock_repo = MagicMock()
        mock_repo.save_fp_rates.return_value = True

        # Patch at the lazy import site (inside the method body)
        import database.repositories.tool_accuracy_repository as repo_mod
        monkeypatch.setattr(
            repo_mod, "ToolAccuracyRepository", lambda: mock_repo
        )

        scored = [
            {"source_tool": "nuclei", "fp_likelihood": 0.15},
            {"source_tool": "sqlmap", "fp_likelihood": 0.05},
        ]

        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert result == {"nuclei": 0.15, "sqlmap": 0.05}
        mock_repo.save_fp_rates.assert_called_once_with(
            "org-1", {"nuclei": 0.15, "sqlmap": 0.05}
        )

    def test_compute_tool_accuracy_handles_repo_failure(self, monkeypatch):
        """Repo failure doesn't raise — returns computed rates anyway."""
        mock_repo = MagicMock()
        mock_repo.save_fp_rates.side_effect = Exception("DB down")

        import database.repositories.tool_accuracy_repository as repo_mod
        monkeypatch.setattr(
            repo_mod, "ToolAccuracyRepository", lambda: mock_repo
        )

        scored = [
            {"source_tool": "nuclei", "fp_likelihood": 0.15},
        ]

        # Should not raise even though save_fp_rates fails
        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert result == {"nuclei": 0.15}

    def test_compute_tool_accuracy_tool_stripped(self):
        """Whitespace around tool names is stripped."""
        scored = [
            {"source_tool": "  nuclei ", "fp_likelihood": 0.15},
            {"source_tool": "\tsqlmap\n", "fp_likelihood": 0.05},
        ]

        result = self.engine._compute_tool_accuracy(scored, org_id="org-1")

        assert "nuclei" in result
        assert "sqlmap" in result
        assert result["nuclei"] == 0.15
        assert result["sqlmap"] == 0.05

"""
Tests for Intelligence Engine
"""
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
        findings = [
            {"source_tool": "nuclei"},
            {"source_tool": "sqlmap"}
        ]

        agreement = self.engine._calculate_tool_agreement(findings)

        assert agreement == 0.85

    def test_calculate_tool_agreement_three_plus_tools(self):
        """Test tool agreement for three or more tools"""
        findings = [
            {"source_tool": "nuclei"},
            {"source_tool": "sqlmap"},
            {"source_tool": "burp"}
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
            {"endpoint": "https://example.com/2"}
        ]

        assert self.engine.detect_low_coverage(findings) is True

    def test_detect_low_coverage_with_many_endpoints(self):
        """Test low coverage detection with many endpoints"""
        findings = [
            {"endpoint": f"https://example.com/{i}"}
            for i in range(10)
        ]

        assert self.engine.detect_low_coverage(findings) is False

    def test_detect_high_value_targets_with_critical(self):
        """Test high value target detection with CRITICAL severity"""
        findings = [
            {"severity": "CRITICAL", "endpoint": "https://example.com/api"}
        ]

        assert self.engine.detect_high_value_targets(findings) is True

    def test_detect_high_value_targets_with_high(self):
        """Test high value target detection with HIGH severity"""
        findings = [
            {"severity": "HIGH", "endpoint": "https://example.com/api"}
        ]

        assert self.engine.detect_high_value_targets(findings) is True

    def test_detect_high_value_targets_without_critical_or_high(self):
        """Test high value target detection without CRITICAL/HIGH"""
        findings = [
            {"severity": "MEDIUM", "endpoint": "https://example.com/api"}
        ]

        assert self.engine.detect_high_value_targets(findings) is False

    def test_detect_weak_auth_signals_with_auth_keyword(self):
        """Test weak auth signal detection with auth keywords"""
        findings = [
            {"type": "BROKEN_AUTHENTICATION", "endpoint": "https://example.com/login"}
        ]

        assert self.engine.detect_weak_auth_signals(findings) is True

    def test_detect_weak_auth_signals_without_auth_keyword(self):
        """Test weak auth signal detection without auth keywords"""
        findings = [
            {"type": "XSS", "endpoint": "https://example.com/page"}
        ]

        assert self.engine.detect_weak_auth_signals(findings) is False

    def test_generate_actions_for_low_coverage(self):
        """Test action generation for low coverage"""
        findings = [
            {"endpoint": "https://example.com/1", "severity": "INFO"}
        ]

        actions = self.engine.generate_actions(findings, {})

        assert len(actions) > 0
        assert any(a["type"] == "recon_expand" for a in actions)

    def test_generate_actions_for_high_value_targets(self):
        """Test action generation for high value targets"""
        findings = [
            {"endpoint": "https://example.com/api", "severity": "CRITICAL"}
        ]

        actions = self.engine.generate_actions(findings, {})

        assert len(actions) > 0
        assert any(a["type"] == "deep_scan" for a in actions)

    def test_evaluate_returns_scored_findings_and_actions(self):
        """Test that evaluate returns scored findings and actions"""
        snapshot = {
            "findings": [
                {
                    "type": "XSS",
                    "endpoint": "https://example.com/api",
                    "severity": "HIGH",
                    "evidence_strength": "PAYLOAD",
                    "fp_likelihood": 0.15,
                    "source_tool": "nuclei"
                }
            ],
            "loop_budget": {},
            "attack_graph": {},
            "engagement_state": {}
        }

        result = self.engine.evaluate(snapshot)

        assert "scored_findings" in result
        assert "actions" in result
        assert "reasoning" in result
        assert len(result["scored_findings"]) == 1

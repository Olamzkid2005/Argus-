"""
Tests for Normalizer
"""
from models.finding import EvidenceStrength, Severity
from parsers.normalizer import FindingNormalizer


class TestFindingNormalizer:
    """Test suite for FindingNormalizer"""

    def setup_method(self):
        """Setup test fixtures"""
        self.normalizer = FindingNormalizer()

    def test_normalize_type_standardizes_sqli(self):
        """Test that SQL injection variants are standardized"""
        assert self.normalizer._normalize_type("sqli", "nuclei") == "SQL_INJECTION"
        assert self.normalizer._normalize_type("sql injection", "nuclei") == "SQL_INJECTION"
        assert self.normalizer._normalize_type("sql-injection", "nuclei") == "SQL_INJECTION"

    def test_normalize_type_standardizes_xss(self):
        """Test that XSS variants are standardized"""
        assert self.normalizer._normalize_type("xss", "nuclei") == "XSS"
        assert self.normalizer._normalize_type("cross-site scripting", "nuclei") == "XSS"

    def test_normalize_severity_maps_correctly(self):
        """Test that severity levels are mapped correctly"""
        assert self.normalizer._normalize_severity("critical") == Severity.CRITICAL
        assert self.normalizer._normalize_severity("high") == Severity.HIGH
        assert self.normalizer._normalize_severity("medium") == Severity.MEDIUM
        assert self.normalizer._normalize_severity("low") == Severity.LOW
        assert self.normalizer._normalize_severity("info") == Severity.INFO

    def test_normalize_severity_case_insensitive(self):
        """Test that severity normalization is case insensitive"""
        assert self.normalizer._normalize_severity("CRITICAL") == Severity.CRITICAL
        assert self.normalizer._normalize_severity("High") == Severity.HIGH

    def test_normalize_severity_defaults_to_info(self):
        """Test that unknown severity defaults to INFO"""
        assert self.normalizer._normalize_severity("unknown") == Severity.INFO

    def test_structure_evidence_adds_standard_fields(self):
        """Test that evidence is structured with standard fields"""
        raw_evidence = {"custom_field": "value"}

        structured = self.normalizer._structure_evidence(raw_evidence)

        assert "request" in structured
        assert "response" in structured
        assert "payload" in structured
        assert "matched_pattern" in structured
        assert "custom_field" in structured

    def test_assess_evidence_strength_verified(self):
        """Test that verified findings get VERIFIED strength"""
        finding = {"verified": True, "evidence": {}}

        strength = self.normalizer._assess_evidence_strength(finding)

        assert strength == EvidenceStrength.VERIFIED

    def test_assess_evidence_strength_request_response(self):
        """Test that request/response pairs get REQUEST_RESPONSE strength"""
        finding = {"evidence": {"request": "GET /", "response": "200 OK"}}

        strength = self.normalizer._assess_evidence_strength(finding)

        assert strength == EvidenceStrength.REQUEST_RESPONSE

    def test_assess_evidence_strength_payload(self):
        """Test that payloads get PAYLOAD strength"""
        finding = {"evidence": {"payload": "' OR 1=1--"}}

        strength = self.normalizer._assess_evidence_strength(finding)

        assert strength == EvidenceStrength.PAYLOAD

    def test_assess_evidence_strength_minimal(self):
        """Test that minimal evidence gets MINIMAL strength"""
        finding = {"evidence": {}}

        strength = self.normalizer._assess_evidence_strength(finding)

        assert strength == EvidenceStrength.MINIMAL

    def test_estimate_fp_likelihood_uses_tool_rates(self):
        """Test that FP likelihood uses tool-specific rates"""
        finding = {}

        nuclei_fp = self.normalizer._estimate_fp_likelihood(finding, "nuclei")
        sqlmap_fp = self.normalizer._estimate_fp_likelihood(finding, "sqlmap")

        assert nuclei_fp == 0.15
        assert sqlmap_fp == 0.10

    def test_estimate_fp_likelihood_reduces_for_verified(self):
        """Test that verified findings have reduced FP likelihood"""
        finding = {"verified": True}

        fp = self.normalizer._estimate_fp_likelihood(finding, "nuclei")

        assert fp == 0.015  # 0.15 * 0.1

    def test_calculate_confidence_formula(self):
        """Test confidence calculation formula"""
        finding = {
            "evidence": {"request": "GET /", "response": "200 OK"},
            "verified": False
        }

        confidence = self.normalizer._calculate_confidence(finding, "sqlmap")

        # tool_agreement=0.7, evidence_strength=0.9, fp_likelihood=0.10
        # confidence = (0.7 * 0.9) / (1 + 0.10) = 0.63 / 1.10 = 0.573
        assert 0.57 <= confidence <= 0.58

    def test_normalize_creates_valid_finding(self):
        """Test that normalize creates valid VulnerabilityFinding"""
        raw_finding = {
            "type": "sqli",
            "severity": "high",
            "endpoint": "https://example.com/api",
            "evidence": {"payload": "' OR 1=1--"},
            "confidence": 0.8
        }

        finding = self.normalizer.normalize(raw_finding, "nuclei")

        assert finding.type == "SQL_INJECTION"
        assert finding.severity.value == "HIGH"
        assert finding.endpoint == "https://example.com/api"
        assert finding.source_tool == "nuclei"
        assert finding.confidence == 0.8

    def test_normalize_batch_skips_invalid_findings(self):
        """Test that normalize_batch skips invalid findings"""
        raw_findings = [
            {"type": "xss", "severity": "high", "endpoint": "https://example.com", "evidence": {}},
            {"type": "", "severity": "high", "endpoint": "", "evidence": {}},  # Invalid
            {"type": "sqli", "severity": "critical", "endpoint": "https://example.com/api", "evidence": {}}
        ]

        findings = self.normalizer.normalize_batch(raw_findings, "nuclei")

        assert len(findings) == 2  # Only valid findings

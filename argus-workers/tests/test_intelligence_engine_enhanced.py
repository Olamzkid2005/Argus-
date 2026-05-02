"""
Tests for intelligence engine enhancements
(CVE enrichment, EPSS scoring, threat feed matching, false positive detection)
"""
from unittest.mock import MagicMock, patch

import pytest

from intelligence_engine import IntelligenceEngine


class TestCVEEnrichment:
    """Test suite for CVE enrichment parsing"""

    @pytest.fixture
    def engine(self):
        return IntelligenceEngine()

    def test_extract_cve_ids_from_evidence(self, engine):
        """Test extracting CVE IDs from evidence"""
        finding = {
            "type": "VULNERABLE_COMPONENT",
            "evidence": {
                "details": "Vulnerable to CVE-2021-44228 and CVE-2022-22965"
            }
        }
        cves = engine._extract_cve_ids(finding)
        assert "CVE-2021-44228" in cves
        assert "CVE-2022-22965" in cves

    def test_extract_cve_ids_from_type(self, engine):
        """Test extracting CVE IDs from finding type field"""
        finding = {
            "type": "CVE-2023-12345-exploit",
            "evidence": {}
        }
        cves = engine._extract_cve_ids(finding)
        assert "CVE-2023-12345" in cves

    def test_extract_cve_ids_no_matches(self, engine):
        """Test extracting CVE IDs when none present"""
        finding = {
            "type": "SQL_INJECTION",
            "evidence": {"payload": "' OR 1=1--"}
        }
        cves = engine._extract_cve_ids(finding)
        assert cves == []

    def test_extract_cve_ids_limits_to_five(self, engine):
        """Test extraction limits to 5 CVEs"""
        finding = {
            "type": "",
            "evidence": {
                "details": " ".join([f"CVE-2021-{1000+i}" for i in range(10)])
            }
        }
        cves = engine._extract_cve_ids(finding)
        assert len(cves) == 5
        assert len(set(cves)) == 5  # deduplicated

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_nvd_cve_data(self, mock_client_class, engine):
        """Test fetching CVE details from NVD"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "vulnerabilities": [{
                "cve": {
                    "descriptions": [{"value": "Test vulnerability"}],
                    "metrics": {
                        "cvssMetricV31": [{
                            "cvssData": {
                                "baseScore": 9.8,
                                "baseSeverity": "CRITICAL"
                            }
                        }]
                    },
                    "published": "2021-01-01",
                    "lastModified": "2021-02-01",
                    "references": [{"url": "https://example.com/ref"}]
                }
            }]
        }
        mock_client.get.return_value = mock_response

        result = engine._fetch_nvd_cve_data(["CVE-2021-44228"])

        assert "CVE-2021-44228" in result
        assert result["CVE-2021-44228"]["cvss_score"] == 9.8
        assert result["CVE-2021-44228"]["severity"] == "CRITICAL"
        assert result["CVE-2021-44228"]["description"] == "Test vulnerability"

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_nvd_cve_data_empty_response(self, mock_client_class, engine):
        """Test fetching CVE details with empty response"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"vulnerabilities": []}
        mock_client.get.return_value = mock_response

        result = engine._fetch_nvd_cve_data(["CVE-2021-99999"])
        assert result == {}

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_nvd_cve_data_api_failure(self, mock_client_class, engine):
        """Test fetching CVE details when API fails"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Connection timeout")

        result = engine._fetch_nvd_cve_data(["CVE-2021-44228"])
        assert result == {}


class TestEPSSScoring:
    """Test suite for EPSS scoring"""

    @pytest.fixture
    def engine(self):
        return IntelligenceEngine()

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_epss_scores(self, mock_client_class, engine):
        """Test fetching EPSS scores"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"cve": "CVE-2021-44228", "epss": "0.95"},
                {"cve": "CVE-2022-22965", "epss": "0.87"},
            ]
        }
        mock_client.get.return_value = mock_response

        result = engine._fetch_epss_scores(["CVE-2021-44228", "CVE-2022-22965"])

        assert result["CVE-2021-44228"] == pytest.approx(0.95)
        assert result["CVE-2022-22965"] == pytest.approx(0.87)

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_epss_scores_empty_list(self, mock_client_class, engine):
        """Test fetching EPSS with empty CVE list"""
        result = engine._fetch_epss_scores([])
        assert result == {}
        mock_client_class.assert_not_called()

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_epss_scores_api_error(self, mock_client_class, engine):
        """Test EPSS fetch handles API errors gracefully"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Network error")

        result = engine._fetch_epss_scores(["CVE-2021-44228"])
        assert result == {}

    @patch("intelligence_engine.httpx.Client")
    def test_fetch_epss_scores_invalid_epss_value(self, mock_client_class, engine):
        """Test EPSS fetch skips invalid values"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"cve": "CVE-2021-44228", "epss": "invalid"},
                {"cve": "CVE-2022-22965", "epss": "0.5"},
            ]
        }
        mock_client.get.return_value = mock_response

        result = engine._fetch_epss_scores(["CVE-2021-44228", "CVE-2022-22965"])
        assert "CVE-2021-44228" not in result
        assert result["CVE-2022-22965"] == pytest.approx(0.5)


class TestThreatFeedMatching:
    """Test suite for threat feed matching"""

    @pytest.fixture
    def engine(self):
        return IntelligenceEngine()

    def test_check_threat_feeds_sql_injection(self, engine):
        """Test threat feed hit for SQL injection"""
        finding = {"type": "SQL_INJECTION", "endpoint": "https://example.com/api"}
        hits = engine._check_threat_feeds(finding)

        assert len(hits) == 1
        assert hits[0]["feed"] == "exploitdb"
        assert hits[0]["risk"] == "high"
        assert hits[0]["matched_type"] == "SQL_INJECTION"

    def test_check_threat_feeds_command_injection(self, engine):
        """Test threat feed hit for command injection"""
        finding = {"type": "COMMAND_INJECTION", "endpoint": "https://example.com/run"}
        hits = engine._check_threat_feeds(finding)

        assert len(hits) == 1
        assert hits[0]["risk"] == "critical"

    def test_check_threat_feeds_no_match(self, engine):
        """Test no threat feed hit for unmapped type"""
        finding = {"type": "INFO_DISCLOSURE", "endpoint": "https://example.com"}
        hits = engine._check_threat_feeds(finding)
        assert hits == []

    def test_check_threat_feeds_includes_endpoint(self, engine):
        """Test threat feed hit includes endpoint info"""
        finding = {"type": "XSS", "endpoint": "https://example.com/search"}
        hits = engine._check_threat_feeds(finding)

        assert hits[0]["endpoint"] == "https://example.com/search"


class TestFalsePositiveDetection:
    """Test suite for false positive detection heuristics"""

    @pytest.fixture
    def engine(self):
        return IntelligenceEngine()

    def test_detect_false_positive_rich_evidence(self, engine):
        """Test FP detection with rich evidence"""
        finding = {
            "evidence": {"detail": "x" * 600},
            "source_tool": "nuclei",
            "tool_agreement_level": "high",
            "endpoint": "https://example.com/api/users",
            "severity": "HIGH",
            "type": "SQL_INJECTION",
        }
        result = engine._detect_false_positive(finding)

        assert result["verdict"] == "true_positive"
        assert "rich_evidence" in result["factors"]
        assert "multi_tool_confirmed" in result["factors"]

    def test_detect_false_positive_minimal_evidence(self, engine):
        """Test FP detection with minimal evidence"""
        finding = {
            "evidence": {},
            "source_tool": "whatweb",
            "tool_agreement_level": "single_tool",
            "endpoint": "https://example.com/script.js",
            "severity": "CRITICAL",
            "type": "TECHNOLOGY_DETECTION",
        }
        result = engine._detect_false_positive(finding)

        assert result["verdict"] in ["likely_false_positive", "false_positive"]
        assert "minimal_evidence" in result["factors"]
        assert "known_noisy_source" in result["factors"]
        assert "static_asset_endpoint" in result["factors"]

    def test_detect_false_positive_severity_mismatch(self, engine):
        """Test FP detection flags severity/evidence mismatch"""
        finding = {
            "evidence": {"detail": "short"},
            "source_tool": "nuclei",
            "tool_agreement_level": "single_tool",
            "endpoint": "https://example.com/api",
            "severity": "CRITICAL",
            "type": "SQL_INJECTION",
        }
        result = engine._detect_false_positive(finding)

        assert "severity_evidence_mismatch" in result["factors"]

    def test_detect_false_positive_high_value_endpoint(self, engine):
        """Test FP detection for high-value endpoint"""
        finding = {
            "evidence": {"detail": "x" * 200},
            "source_tool": "nuclei",
            "tool_agreement_level": "medium",
            "endpoint": "https://example.com/api/admin",
            "severity": "HIGH",
            "type": "BROKEN_ACCESS_CONTROL",
        }
        result = engine._detect_false_positive(finding)

        assert "high_value_endpoint" in result["factors"]
        assert result["verdict"] in ["true_positive", "likely_true_positive"]

    def test_detect_false_positive_structure(self, engine):
        """Test FP result has expected structure"""
        finding = {
            "evidence": {"detail": "x" * 300},
            "source_tool": "nuclei",
            "tool_agreement_level": "high",
            "endpoint": "https://example.com/api",
            "severity": "HIGH",
            "type": "XSS",
        }
        result = engine._detect_false_positive(finding)

        assert "verdict" in result
        assert "confidence" in result
        assert "true_positive_score" in result
        assert "factors" in result
        assert "factor_scores" in result
        assert isinstance(result["confidence"], float)
        assert 0 <= result["confidence"] <= 1

    def test_detect_false_positive_single_tool(self, engine):
        """Test FP detection with single tool confirmation"""
        finding = {
            "evidence": {"detail": "x" * 300},
            "source_tool": "nuclei",
            "tool_agreement_level": "single_tool",
            "endpoint": "https://example.com/api",
            "severity": "MEDIUM",
            "type": "XSS",
        }
        result = engine._detect_false_positive(finding)

        assert "single_tool" in result["factors"]
        assert "reliable_source" in result["factors"]
        assert "standard_endpoint" in result["factors"]


class TestEnrichFindings:
    """Test suite for the full enrichment pipeline"""

    @pytest.fixture
    def engine(self):
        return IntelligenceEngine()

    @patch.object(IntelligenceEngine, "_fetch_nvd_cve_data")
    @patch.object(IntelligenceEngine, "_fetch_epss_scores")
    @patch.object(IntelligenceEngine, "_check_threat_feeds")
    @patch.object(IntelligenceEngine, "_detect_false_positive")
    def test_enrich_findings_with_cve(
        self, mock_fp, mock_threat, mock_epss, mock_nvd, engine
    ):
        """Test full enrichment pipeline with CVE"""
        mock_nvd.return_value = {"CVE-2021-44228": {"cvss_score": 9.8}}
        mock_epss.return_value = {"CVE-2021-44228": 0.95}
        mock_threat.return_value = [{"feed": "exploitdb"}]
        mock_fp.return_value = {"verdict": "true_positive"}

        findings = [{
            "type": "VULNERABLE_COMPONENT",
            "evidence": {"details": "CVE-2021-44228"}
        }]

        enriched = engine.enrich_findings_with_threat_intel(findings)

        assert len(enriched) == 1
        assert "threat_intel" in enriched[0]
        assert enriched[0]["threat_intel"]["cve_ids"] == ["CVE-2021-44228"]
        assert enriched[0]["threat_intel"]["cve_details"] == {"CVE-2021-44228": {"cvss_score": 9.8}}
        assert enriched[0]["threat_intel"]["epss_scores"] == {"CVE-2021-44228": 0.95}
        assert enriched[0]["threat_intel"]["fp_assessment"] == {"verdict": "true_positive"}

    @patch.object(IntelligenceEngine, "_extract_cve_ids")
    def test_enrich_findings_without_cve(self, mock_extract, engine):
        """Test enrichment when no CVEs are found"""
        mock_extract.return_value = []

        findings = [{"type": "SQL_INJECTION", "evidence": {}}]
        enriched = engine.enrich_findings_with_threat_intel(findings)

        assert "cve_ids" not in enriched[0]["threat_intel"]
        assert "cve_details" not in enriched[0]["threat_intel"]


class TestThreatSummary:
    """Test suite for threat summary generation"""

    @pytest.fixture
    def engine(self):
        return IntelligenceEngine()

    def test_get_threat_summary_counts(self, engine):
        """Test threat summary counts correctly"""
        findings = [
            {
                "severity": "CRITICAL",
                "threat_intel": {
                    "cve_details": {"CVE-2021-44228": {}},
                    "epss_scores": {"CVE-2021-44228": 0.95},
                    "threat_feed_hits": [{"feed": "exploitdb"}],
                    "fp_assessment": {"verdict": "true_positive"}
                }
            },
            {
                "severity": "HIGH",
                "threat_intel": {
                    "cve_details": {},
                    "epss_scores": {},
                    "threat_feed_hits": [],
                    "fp_assessment": {"verdict": "likely_false_positive"}
                }
            }
        ]

        summary = engine.get_threat_summary(findings)

        assert summary["total_findings"] == 2
        assert summary["findings_with_cves"] == 1
        assert summary["high_exploitability_count"] == 1
        assert summary["threat_feed_hits"] == 1
        assert summary["likely_false_positives"] == 1

    def test_calculate_overall_risk_critical(self, engine):
        """Test overall risk calculation - critical"""
        findings = [{"severity": "CRITICAL"}] * 3
        assert engine._calculate_overall_risk(findings) == "critical"

    def test_calculate_overall_risk_high(self, engine):
        """Test overall risk calculation - high"""
        findings = [{"severity": "HIGH"}] * 3
        assert engine._calculate_overall_risk(findings) == "high"

    def test_calculate_overall_risk_medium(self, engine):
        """Test overall risk calculation - medium"""
        findings = [{"severity": "HIGH"}]
        assert engine._calculate_overall_risk(findings) == "medium"

    def test_calculate_overall_risk_low(self, engine):
        """Test overall risk calculation - low"""
        findings = [{"severity": "LOW"}]
        assert engine._calculate_overall_risk(findings) == "low"

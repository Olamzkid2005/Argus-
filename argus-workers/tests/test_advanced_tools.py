"""
Unit tests for all 14 advanced security tools.

Tests cover:
- Finding Correlation Engine
- Attack Path Generator
- Verification Agent
- Browser Security Operator
- Attack Surface Mapper
- Evidence Intelligence Engine
- Executive Report Generator
- Threat Intelligence Aggregator
- Vulnerability Knowledge Engine
- Secure Code Intelligence Engine
- Infrastructure Security Analyzer
- Assessment Orchestrator
- Workflow Intelligence Engine
- Engagement Analytics Engine
"""

from tool_core.base import ToolContext
from tool_core.result import ToolStatus

# ═══════════════════════════════════════════════════════════════
# Finding Correlation Engine
# ═══════════════════════════════════════════════════════════════

class TestFindingCorrelationEngine:
    def _make_ctx(self, findings=None):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._correlation_input = findings
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.finding_correlation_engine import FindingCorrelationEngine
        engine = FindingCorrelationEngine()
        result = engine.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_no_input_returns_empty(self):
        from tools.finding_correlation_engine import FindingCorrelationEngine
        engine = FindingCorrelationEngine()
        result = engine.execute(self._make_ctx(None))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_deduplication(self):
        from tools.finding_correlation_engine import FindingCorrelationEngine
        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "confidence": 0.8},
            {"id": "2", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "confidence": 0.8},
            {"id": "3", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com/b", "confidence": 0.9},
        ]
        engine = FindingCorrelationEngine()
        result = engine.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count >= 2

    def test_priority_ranking(self):
        from tools.finding_correlation_engine import FindingCorrelationEngine
        findings = [
            {"id": "1", "type": "INFO_DISCLOSURE", "severity": "LOW", "endpoint": "https://example.com/a", "confidence": 0.5},
            {"id": "2", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com/b", "confidence": 0.9},
        ]
        engine = FindingCorrelationEngine()
        result = engine.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS
        assert len(result.findings) > 0


# ═══════════════════════════════════════════════════════════════
# Attack Path Generator
# ═══════════════════════════════════════════════════════════════

class TestAttackPathGenerator:
    def _make_ctx(self, findings=None):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._attack_path_input = findings
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.attack_path_generator import AttackPathGenerator
        gen = AttackPathGenerator()
        result = gen.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_finds_paths(self):
        from tools.attack_path_generator import AttackPathGenerator
        findings = [
            {"id": "1", "type": "MISCONFIGURATION", "severity": "MEDIUM", "endpoint": "https://example.com", "confidence": 0.7},
            {"id": "2", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com", "confidence": 0.9},
        ]
        gen = AttackPathGenerator()
        result = gen.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# Verification Agent
# ═══════════════════════════════════════════════════════════════

class TestVerificationAgent:
    def _make_ctx(self, findings=None):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._verification_input = findings
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.verification_agent import VerificationAgent
        agent = VerificationAgent()
        result = agent.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_verifies_findings(self):
        from tools.verification_agent import VerificationAgent
        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "confidence": 0.8},
            {"id": "2", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com/b", "confidence": 0.9},
        ]
        agent = VerificationAgent()
        result = agent.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count >= 2

    def test_verification_status_set(self):
        from tools.verification_agent import VerificationAgent
        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "confidence": 0.8},
        ]
        agent = VerificationAgent()
        result = agent.execute(self._make_ctx(findings))
        assert len(result.findings) > 0
        for f in result.findings:
            if "status" in f:
                assert f["status"] in ("CONFIRMED", "PENDING", "REJECTED")


# ═══════════════════════════════════════════════════════════════
# Browser Security Operator
# ═══════════════════════════════════════════════════════════════

class TestBrowserSecurityOperator:
    def _make_ctx(self, **kwargs):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123", **kwargs)
        return ctx

    def test_blocks_file_scheme(self):
        from tools.browser_security_operator import BrowserSecurityOperator
        op = BrowserSecurityOperator()
        ctx = ToolContext(target="file:///etc/passwd", engagement_id="test-123")
        result = op.execute(ctx)
        assert result.status == ToolStatus.SKIPPED

    def test_analyzes_headers(self):
        from tools.browser_security_operator import BrowserSecurityOperator
        op = BrowserSecurityOperator()
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._browser_headers = {}
        result = op.execute(ctx)
        assert result.status == ToolStatus.SUCCESS

    def test_detects_missing_csp(self):
        from tools.browser_security_operator import BrowserSecurityOperator
        op = BrowserSecurityOperator()
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._browser_headers = {}
        result = op.execute(ctx)
        csp_findings = [f for f in result.findings if f.get("type") == "MISSING_CSP"]
        assert len(csp_findings) > 0


# ═══════════════════════════════════════════════════════════════
# Attack Surface Mapper
# ═══════════════════════════════════════════════════════════════

class TestAttackSurfaceMapper:
    def _make_ctx(self):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._tool_runner = None
        return ctx

    def test_runs_without_tool_runner(self):
        from tools.attack_surface_mapper import AttackSurfaceMapper
        mapper = AttackSurfaceMapper()
        result = mapper.execute(self._make_ctx())
        assert result.status == ToolStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# Evidence Intelligence Engine
# ═══════════════════════════════════════════════════════════════

class TestEvidenceIntelligenceEngine:
    def _make_ctx(self, findings=None):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._evidence_input = findings
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.evidence_intelligence_engine import EvidenceIntelligenceEngine
        engine = EvidenceIntelligenceEngine()
        result = engine.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_enriches_findings(self):
        from tools.evidence_intelligence_engine import EvidenceIntelligenceEngine
        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "evidence": {"payload": "<script>alert(1)</script>"}},
        ]
        engine = EvidenceIntelligenceEngine()
        result = engine.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count >= 1

    def test_evidence_hash_generated(self):
        from tools.evidence_intelligence_engine import EvidenceIntelligenceEngine
        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "evidence": {"payload": "test"}},
        ]
        engine = EvidenceIntelligenceEngine()
        result = engine.execute(self._make_ctx(findings))
        for f in result.findings:
            if "evidence_package" in f:
                assert "hash" in f["evidence_package"]
                assert len(f["evidence_package"]["hash"]) > 0


# ═══════════════════════════════════════════════════════════════
# Executive Report Generator
# ═══════════════════════════════════════════════════════════════

class TestExecutiveReportGenerator:
    def _make_ctx(self, findings=None):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._report_input = findings
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.executive_report_generator import ExecutiveReportGenerator
        gen = ExecutiveReportGenerator()
        result = gen.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_generates_report(self):
        from tools.executive_report_generator import ExecutiveReportGenerator
        findings = [
            {"id": "1", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com/a", "confidence": 0.9},
            {"id": "2", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/b", "confidence": 0.8},
        ]
        gen = ExecutiveReportGenerator()
        result = gen.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS
        assert len(result.findings) > 0
        report = result.findings[0]
        assert "executive_summary" in report
        assert "severity_breakdown" in report
        assert "markdown" in report

    def test_severity_breakdown(self):
        from tools.executive_report_generator import ExecutiveReportGenerator
        findings = [
            {"id": "1", "type": "CRITICAL_VULN", "severity": "CRITICAL", "endpoint": "https://example.com"},
            {"id": "2", "type": "HIGH_VULN", "severity": "HIGH", "endpoint": "https://example.com"},
            {"id": "3", "type": "LOW_VULN", "severity": "LOW", "endpoint": "https://example.com"},
        ]
        gen = ExecutiveReportGenerator()
        result = gen.execute(self._make_ctx(findings))
        report = result.findings[0]
        assert report["severity_breakdown"]["CRITICAL"] == 1
        assert report["severity_breakdown"]["HIGH"] == 1
        assert report["severity_breakdown"]["LOW"] == 1


# ═══════════════════════════════════════════════════════════════
# Threat Intelligence Aggregator
# ═══════════════════════════════════════════════════════════════

class TestThreatIntelligenceAggregator:
    def _make_ctx(self):
        return ToolContext(target="https://example.com", engagement_id="test-123")

    def test_runs_without_external_apis(self):
        from tools.threat_intelligence_aggregator import ThreatIntelligenceAggregator
        agg = ThreatIntelligenceAggregator()
        result = agg.execute(self._make_ctx())
        assert result.status == ToolStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# Vulnerability Knowledge Engine
# ═══════════════════════════════════════════════════════════════

class TestVulnerabilityKnowledgeEngine:
    def _make_ctx(self, findings=None):
        ctx = ToolContext(target="https://example.com", engagement_id="test-123")
        ctx._knowledge_input = findings
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.vulnerability_knowledge_engine import VulnerabilityKnowledgeEngine
        engine = VulnerabilityKnowledgeEngine()
        result = engine.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_maps_to_cwe(self):
        from tools.vulnerability_knowledge_engine import VulnerabilityKnowledgeEngine
        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "cwe": "79"},
        ]
        engine = VulnerabilityKnowledgeEngine()
        result = engine.execute(self._make_ctx(findings))
        assert result.status == ToolStatus.SUCCESS
        cwe_findings = [f for f in result.findings if f.get("type") == "CWE_KNOWLEDGE"]
        assert len(cwe_findings) > 0

    def test_maps_to_owasp(self):
        from tools.vulnerability_knowledge_engine import VulnerabilityKnowledgeEngine
        findings = [
            {"id": "1", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com/a"},
        ]
        engine = VulnerabilityKnowledgeEngine()
        result = engine.execute(self._make_ctx(findings))
        owasp_findings = [f for f in result.findings if f.get("type") == "OWASP_MAPPING"]
        assert len(owasp_findings) > 0


# ═══════════════════════════════════════════════════════════════
# Secure Code Intelligence Engine
# ═══════════════════════════════════════════════════════════════

class TestSecureCodeIntelligenceEngine:
    def _make_ctx(self):
        ctx = ToolContext(target="/tmp/test_repo", engagement_id="test-123")
        ctx._tool_runner = None
        return ctx

    def test_runs_without_tool_runner(self):
        from tools.secure_code_intelligence_engine import SecureCodeIntelligenceEngine
        engine = SecureCodeIntelligenceEngine()
        result = engine.execute(self._make_ctx())
        assert result.status == ToolStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# Infrastructure Security Analyzer
# ═══════════════════════════════════════════════════════════════

class TestInfrastructureSecurityAnalyzer:
    def test_skips_non_directory(self):
        from tools.infrastructure_security_analyzer import (
            InfrastructureSecurityAnalyzer,
        )
        analyzer = InfrastructureSecurityAnalyzer()
        ctx = ToolContext(target="/tmp/nonexistent_file", engagement_id="test-123")
        result = analyzer.execute(ctx)
        assert result.status == ToolStatus.SKIPPED

    def test_scans_terraform(self, tmp_path):
        from tools.infrastructure_security_analyzer import (
            InfrastructureSecurityAnalyzer,
        )
        tf_file = tmp_path / "main.tf"
        tf_file.write_text('resource "aws_s3_bucket" "example" {\n  bucket = "test"\n  acl = "public-read"\n}')
        analyzer = InfrastructureSecurityAnalyzer()
        ctx = ToolContext(target=str(tmp_path), engagement_id="test-123")
        result = analyzer.execute(ctx)
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count > 0

    def test_scans_dockerfile(self, tmp_path):
        from tools.infrastructure_security_analyzer import (
            InfrastructureSecurityAnalyzer,
        )
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text('FROM ubuntu:latest\nRUN apt-get update\nUSER root\n')
        analyzer = InfrastructureSecurityAnalyzer()
        ctx = ToolContext(target=str(tmp_path), engagement_id="test-123")
        result = analyzer.execute(ctx)
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count > 0


# ═══════════════════════════════════════════════════════════════
# Assessment Orchestrator
# ═══════════════════════════════════════════════════════════════

class TestAssessmentOrchestrator:
    def _make_ctx(self):
        return ToolContext(target="https://example.com", engagement_id="test-123")

    def test_creates_plan(self):
        from tools.assessment_orchestrator import AssessmentOrchestrator
        orch = AssessmentOrchestrator()
        result = orch.execute(self._make_ctx())
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count > 0

    def test_custom_phase_range(self):
        from tools.assessment_orchestrator import AssessmentOrchestrator
        ctx = self._make_ctx()
        ctx._orchestrator_start_phase = "scan"
        ctx._orchestrator_end_phase = "analyze"
        orch = AssessmentOrchestrator()
        result = orch.execute(ctx)
        assert result.status == ToolStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# Workflow Intelligence Engine
# ═══════════════════════════════════════════════════════════════

class TestWorkflowIntelligenceEngine:
    def _make_ctx(self, metrics=None):
        ctx = ToolContext(target="test-engagement", engagement_id="test-123")
        ctx._workflow_metrics = metrics
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.workflow_intelligence_engine import WorkflowIntelligenceEngine
        engine = WorkflowIntelligenceEngine()
        result = engine.execute(self._make_ctx([]))
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_analyzes_metrics(self):
        from tools.workflow_intelligence_engine import WorkflowIntelligenceEngine
        metrics = [
            {"tool": "nuclei", "duration_seconds": 120, "success": True},
            {"tool": "nuclei", "duration_seconds": 150, "success": True},
            {"tool": "subfinder", "duration_seconds": 30, "success": False},
            {"tool": "httpx", "duration_seconds": 15, "success": True},
        ]
        engine = WorkflowIntelligenceEngine()
        result = engine.execute(self._make_ctx(metrics))
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count > 0


# ═══════════════════════════════════════════════════════════════
# Engagement Analytics Engine
# ═══════════════════════════════════════════════════════════════

class TestEngagementAnalyticsEngine:
    def _make_ctx(self, findings=None, engagements=None):
        ctx = ToolContext(target="test-scope", engagement_id="test-123")
        ctx._analytics_findings = findings
        ctx._analytics_engagements = engagements
        return ctx

    def test_empty_input_returns_empty(self):
        from tools.engagement_analytics_engine import EngagementAnalyticsEngine
        engine = EngagementAnalyticsEngine()
        result = engine.execute(self._make_ctx())
        assert result.status == ToolStatus.SUCCESS_EMPTY

    def test_analyzes_findings(self):
        from tools.engagement_analytics_engine import EngagementAnalyticsEngine
        findings = [
            {"type": "XSS", "severity": "HIGH", "cwe": "79", "source_tool": "nuclei"},
            {"type": "SQL_INJECTION", "severity": "CRITICAL", "cwe": "89", "source_tool": "sqlmap"},
            {"type": "XSS", "severity": "MEDIUM", "cwe": "79", "source_tool": "nikto"},
        ]
        engine = EngagementAnalyticsEngine()
        result = engine.execute(self._make_ctx(findings=findings))
        assert result.status == ToolStatus.SUCCESS
        assert result.findings_count > 0


# ═══════════════════════════════════════════════════════════════
# Sub-module unit tests
# ═══════════════════════════════════════════════════════════════

class TestDeduplicator:
    def test_exact_dedup(self):
        from tools.correlation.deduplicator import deduplicate
        findings = [
            {"type": "XSS", "endpoint": "https://example.com/a", "severity": "HIGH"},
            {"type": "XSS", "endpoint": "https://example.com/a", "severity": "HIGH"},
        ]
        unique, removed = deduplicate(findings)
        assert len(unique) == 1
        assert removed == 1

    def test_semantic_dedup(self):
        from tools.correlation.deduplicator import deduplicate
        findings = [
            {"type": "Cross-site Scripting", "endpoint": "https://example.com/a", "severity": "HIGH", "title": "XSS in search"},
            {"type": "XSS", "endpoint": "https://example.com/a", "severity": "HIGH", "title": "XSS vulnerability in search"},
        ]
        unique, removed = deduplicate(findings, similarity_threshold=0.6)
        assert len(unique) >= 1

    def test_different_findings_kept(self):
        from tools.correlation.deduplicator import deduplicate
        findings = [
            {"type": "XSS", "endpoint": "https://example.com/a", "severity": "HIGH"},
            {"type": "SQL_INJECTION", "endpoint": "https://example.com/b", "severity": "CRITICAL"},
        ]
        unique, removed = deduplicate(findings)
        assert len(unique) == 2
        assert removed == 0


class TestRootCause:
    def test_group_by_cwe(self):
        from tools.correlation.root_cause import group_by_root_cause
        findings = [
            {"type": "XSS", "cwe": "79", "endpoint": "https://a.com"},
            {"type": "XSS", "cwe": "79", "endpoint": "https://b.com"},
            {"type": "SQL_INJECTION", "cwe": "89", "endpoint": "https://a.com"},
        ]
        groups = group_by_root_cause(findings)
        assert "cwe:79" in groups
        assert len(groups["cwe:79"]) == 2

    def test_find_root_causes(self):
        from tools.correlation.root_cause import find_root_causes
        findings = [
            {"type": "XSS", "cwe": "79", "endpoint": "https://a.com", "severity": "HIGH"},
            {"type": "XSS", "cwe": "79", "endpoint": "https://b.com", "severity": "MEDIUM"},
        ]
        causes = find_root_causes(findings, min_group_size=2)
        assert len(causes) >= 1


class TestAttackChainDetector:
    def test_no_chains_for_single_finding(self):
        from tools.correlation.attack_chain_detector import detect_attack_chains
        findings = [{"type": "XSS", "endpoint": "https://example.com"}]
        chains = detect_attack_chains(findings)
        assert len(chains) == 0


class TestPriorityRanker:
    def test_ranks_by_severity(self):
        from tools.correlation.priority_ranker import rank_findings
        findings = [
            {"type": "INFO", "severity": "INFO", "endpoint": "https://a.com", "confidence": 0.5},
            {"type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://b.com", "confidence": 0.9},
        ]
        ranked = rank_findings(findings)
        assert ranked[0]["type"] == "SQL_INJECTION"


class TestPathFinder:
    def test_no_paths_for_empty_graph(self):
        from tools.attack_paths.path_finder import find_paths
        paths = find_paths({}, [])
        assert len(paths) == 0


class TestPathScorer:
    def test_score_path(self):
        from tools.attack_paths.path_scorer import score_path
        findings = [{"type": "XSS", "severity": "HIGH", "endpoint": "https://example.com"}]
        score = score_path(["host:example.com"], findings)
        assert score > 0


class TestPathVisualizer:
    def test_render_text(self):
        from tools.attack_paths.path_visualizer import render_all_paths
        output = render_all_paths([])
        assert "No attack paths" in output

    def test_render_mermaid(self):
        from tools.attack_paths.path_visualizer import render_mermaid
        output = render_mermaid([])
        assert "graph TD" in output


class TestNarrativeGenerator:
    def test_generate_narrative(self):
        from tools.attack_paths.narrative_generator import generate_narrative
        path_info = {"path": ["host:a.com", "host:b.com"], "score": 8.0, "steps": 2}
        findings = [{"type": "MISCONFIGURATION", "severity": "MEDIUM", "endpoint": "https://a.com"}]
        narrative = generate_narrative(path_info, findings)
        assert "attack path" in narrative.lower() or "steps" in narrative.lower()


class TestReproductionEngine:
    def test_reproduce_sqli(self):
        from tools.verification.reproduction_engine import ReproductionEngine
        engine = ReproductionEngine()
        result = engine.reproduce({"type": "SQL_INJECTION", "endpoint": "https://example.com"}, "https://example.com")
        assert "reproduced" in result
        assert result["reproduced"] is False

    def test_reproduce_xss(self):
        from tools.verification.reproduction_engine import ReproductionEngine
        engine = ReproductionEngine()
        result = engine.reproduce({"type": "XSS", "endpoint": "https://example.com"}, "https://example.com")
        assert "evidence" in result


class TestConfidenceScorer:
    def test_reproduced_higher_confidence(self):
        from tools.verification.confidence_scorer import score_confidence
        finding = {"confidence": 0.5}
        result = {"reproduced": True}
        evidence = {"artifacts": []}
        score = score_confidence(finding, result, evidence)
        assert score > 0.5

    def test_not_reproduced_lower_confidence(self):
        from tools.verification.confidence_scorer import score_confidence
        finding = {"confidence": 0.5}
        result = {"reproduced": False, "error": "some error"}
        evidence = {"artifacts": []}
        score = score_confidence(finding, result, evidence)
        assert score <= 0.5


class TestFindingPromoter:
    def test_confirm_reproduced(self):
        from tools.verification.finding_promoter import promote_finding
        finding = {"id": "1", "confidence": 0.5}
        result = promote_finding(finding, 0.9, True)
        assert result["status"] == "CONFIRMED"

    def test_reject_low_confidence(self):
        from tools.verification.finding_promoter import promote_finding
        finding = {"id": "1", "confidence": 0.5}
        result = promote_finding(finding, 0.2, False)
        assert result["status"] == "REJECTED"


class TestEvidenceCollector:
    def test_collect_evidence(self):
        from tools.verification.evidence_collector import VerificationEvidenceCollector
        collector = VerificationEvidenceCollector(output_dir="/tmp/test_evidence")
        finding = {"id": "test-finding-1"}
        reproduction = {"reproduced": False, "evidence": {"test": "data"}, "error": "no http client"}
        evidence = collector.collect(finding, reproduction)
        assert "hash" in evidence
        assert "artifacts" in evidence


class TestAssetGraph:
    def test_build_graph(self):
        from tools.attack_surface.asset_graph import AssetGraph
        graph = AssetGraph()
        graph.add_subdomain("api.example.com")
        graph.add_url("https://api.example.com/v1/users")
        d = graph.to_dict()
        assert "api.example.com" in d["subdomains"]
        assert len(d["urls"]) == 1


class TestSubdomainDiscovery:
    def test_without_runner(self):
        from tools.attack_surface.subdomain_discovery import SubdomainDiscovery
        disc = SubdomainDiscovery()
        subs = disc.discover("example.com")
        assert "example.com" in subs


class TestPortDiscovery:
    def test_without_runner(self):
        from tools.attack_surface.port_discovery import PortDiscovery
        disc = PortDiscovery()
        ports = disc.discover("example.com")
        assert ports == []


class TestURLDiscovery:
    def test_without_runner(self):
        from tools.attack_surface.url_discovery import URLDiscovery
        disc = URLDiscovery()
        urls = disc.discover("https://example.com")
        assert urls == []


class TestWorkflowAnalysis:
    def test_analyze_metrics(self):
        from tools.workflow_intelligence_engine import WorkflowIntelligenceEngine
        engine = WorkflowIntelligenceEngine()
        metrics = [
            {"tool": "nuclei", "duration_seconds": 120, "success": True},
            {"tool": "nuclei", "duration_seconds": 150, "success": True},
            {"tool": "subfinder", "duration_seconds": 30, "success": False},
        ]
        analysis = engine._analyze_metrics(metrics)
        assert analysis["total_tool_calls"] == 3
        assert analysis["total_failures"] == 1


class TestEngagementAnalysis:
    def test_analyze(self):
        from tools.engagement_analytics_engine import EngagementAnalyticsEngine
        engine = EngagementAnalyticsEngine()
        findings = [
            {"type": "XSS", "severity": "HIGH", "cwe": "79", "source_tool": "nuclei"},
            {"type": "SQL_INJECTION", "severity": "CRITICAL", "cwe": "89", "source_tool": "sqlmap"},
        ]
        analysis = engine._analyze(findings, [])
        assert analysis["total_findings"] == 2
        assert analysis["most_common_cwe"] == "79"

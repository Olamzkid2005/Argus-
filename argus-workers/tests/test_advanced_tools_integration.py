"""
Integration tests for advanced security tools.

Tests verify that tools work together correctly and integrate with
the existing tool infrastructure (ToolRunner, MCP, orchestrator).
"""

import pytest
from unittest.mock import MagicMock, patch
from tool_core.base import ToolContext
from tool_core.result import ToolStatus


class TestToolRegistration:
    """Verify all 14 tools are properly registered in tool_definitions.py."""

    def test_all_tools_registered(self):
        from tool_definitions import TOOLS
        expected = [
            "finding_correlation_engine",
            "attack_path_generator",
            "verification_agent",
            "browser_security_operator",
            "attack_surface_mapper",
            "evidence_intelligence_engine",
            "executive_report_generator",
            "threat_intelligence_aggregator",
            "vulnerability_knowledge_engine",
            "secure_code_intelligence_engine",
            "infrastructure_security_analyzer",
            "assessment_orchestrator",
            "workflow_intelligence_engine",
            "engagement_analytics_engine",
        ]
        for tool_name in expected:
            assert tool_name in TOOLS, f"{tool_name} not registered in TOOLS"

    def test_tools_have_phases(self):
        from tool_definitions import TOOLS
        no_phase = []
        for name in ["finding_correlation_engine", "attack_path_generator", "verification_agent",
                      "browser_security_operator", "attack_surface_mapper", "evidence_intelligence_engine",
                      "executive_report_generator", "threat_intelligence_aggregator", "vulnerability_knowledge_engine",
                      "secure_code_intelligence_engine", "infrastructure_security_analyzer",
                      "assessment_orchestrator", "workflow_intelligence_engine", "engagement_analytics_engine"]:
            tool = TOOLS.get(name)
            if tool and not tool.phases:
                no_phase.append(name)
        assert len(no_phase) == 0, f"Tools without phases: {no_phase}"

    def test_agent_internal_tools_include_new(self):
        from tool_definitions import _AGENT_INTERNAL_TOOLS
        expected = [
            "finding_correlation_engine", "attack_path_generator", "verification_agent",
            "browser_security_operator", "attack_surface_mapper", "evidence_intelligence_engine",
            "executive_report_generator", "threat_intelligence_aggregator", "vulnerability_knowledge_engine",
            "secure_code_intelligence_engine", "infrastructure_security_analyzer",
            "assessment_orchestrator", "workflow_intelligence_engine", "engagement_analytics_engine",
        ]
        for name in expected:
            assert name in _AGENT_INTERNAL_TOOLS, f"{name} not in _AGENT_INTERNAL_TOOLS"


class TestToolPipeline:
    """Test that tools can be chained together in a pipeline."""

    def test_correlation_then_attack_path(self):
        """Finding Correlation → Attack Path Generator pipeline."""
        from tools.finding_correlation_engine import FindingCorrelationEngine
        from tools.attack_path_generator import AttackPathGenerator

        findings = [
            {"id": "1", "type": "MISCONFIGURATION", "severity": "MEDIUM", "endpoint": "https://example.com", "confidence": 0.7},
            {"id": "2", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com", "confidence": 0.9},
            {"id": "3", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/page", "confidence": 0.8},
        ]

        ctx1 = ToolContext(target="https://example.com", engagement_id="test-pipeline")
        ctx1._correlation_input = findings
        corr_engine = FindingCorrelationEngine()
        corr_result = corr_engine.execute(ctx1)
        assert corr_result.status == ToolStatus.SUCCESS

        ctx2 = ToolContext(target="https://example.com", engagement_id="test-pipeline")
        ctx2._attack_path_input = corr_result.findings
        ap_gen = AttackPathGenerator()
        ap_result = ap_gen.execute(ctx2)
        assert ap_result.status == ToolStatus.SUCCESS

    def test_verification_then_evidence(self):
        """Verification Agent → Evidence Intelligence Engine pipeline."""
        from tools.verification_agent import VerificationAgent
        from tools.evidence_intelligence_engine import EvidenceIntelligenceEngine

        findings = [
            {"id": "1", "type": "XSS", "severity": "HIGH", "endpoint": "https://example.com/a", "confidence": 0.8},
        ]

        ctx1 = ToolContext(target="https://example.com", engagement_id="test-pipeline")
        ctx1._verification_input = findings
        verifier = VerificationAgent()
        v_result = verifier.execute(ctx1)
        assert v_result.status == ToolStatus.SUCCESS

        ctx2 = ToolContext(target="https://example.com", engagement_id="test-pipeline")
        ctx2._evidence_input = v_result.findings
        evidence = EvidenceIntelligenceEngine()
        e_result = evidence.execute(ctx2)
        assert e_result.status == ToolStatus.SUCCESS

    def test_knowledge_then_report(self):
        """Vulnerability Knowledge → Executive Report pipeline."""
        from tools.vulnerability_knowledge_engine import VulnerabilityKnowledgeEngine
        from tools.executive_report_generator import ExecutiveReportGenerator

        findings = [
            {"id": "1", "type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "https://example.com/a", "cwe": "89", "confidence": 0.9},
        ]

        ctx1 = ToolContext(target="https://example.com", engagement_id="test-pipeline")
        ctx1._knowledge_input = findings
        knowledge = VulnerabilityKnowledgeEngine()
        k_result = knowledge.execute(ctx1)
        assert k_result.status == ToolStatus.SUCCESS

        all_findings = findings + k_result.findings
        ctx2 = ToolContext(target="https://example.com", engagement_id="test-pipeline")
        ctx2._report_input = all_findings
        report_gen = ExecutiveReportGenerator()
        r_result = report_gen.execute(ctx2)
        assert r_result.status == ToolStatus.SUCCESS


class TestYAMLDefinitions:
    """Verify YAML definitions exist for all new tools."""

    def test_yaml_files_exist(self):
        import os
        yaml_dir = os.path.join(os.path.dirname(__file__), "..", "tools", "definitions")
        expected = [
            "finding_correlation_engine.yaml",
            "attack_path_generator.yaml",
            "verification_agent.yaml",
            "browser_security_operator.yaml",
            "attack_surface_mapper.yaml",
            "evidence_intelligence_engine.yaml",
            "executive_report_generator.yaml",
            "threat_intelligence_aggregator.yaml",
            "vulnerability_knowledge_engine.yaml",
            "secure_code_intelligence_engine.yaml",
            "infrastructure_security_analyzer.yaml",
            "assessment_orchestrator.yaml",
            "workflow_intelligence_engine.yaml",
            "engagement_analytics_engine.yaml",
        ]
        for fname in expected:
            path = os.path.join(yaml_dir, fname)
            assert os.path.exists(path), f"YAML definition missing: {fname}"

    def test_yaml_files_valid(self):
        import os
        import yaml
        yaml_dir = os.path.join(os.path.dirname(__file__), "..", "tools", "definitions")
        expected = [
            "finding_correlation_engine.yaml",
            "attack_path_generator.yaml",
            "verification_agent.yaml",
            "browser_security_operator.yaml",
            "attack_surface_mapper.yaml",
            "evidence_intelligence_engine.yaml",
            "executive_report_generator.yaml",
            "threat_intelligence_aggregator.yaml",
            "vulnerability_knowledge_engine.yaml",
            "secure_code_intelligence_engine.yaml",
            "infrastructure_security_analyzer.yaml",
            "assessment_orchestrator.yaml",
            "workflow_intelligence_engine.yaml",
            "engagement_analytics_engine.yaml",
        ]
        for fname in expected:
            path = os.path.join(yaml_dir, fname)
            with open(path) as f:
                data = yaml.safe_load(f)
            assert "name" in data, f"{fname} missing 'name' field"
            assert "command" in data, f"{fname} missing 'command' field"
            assert "capabilities" in data, f"{fname} missing 'capabilities' field"

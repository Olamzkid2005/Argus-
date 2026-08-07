"""Lifecycle integration tests for the ai-surface pipeline.

Tests the full lifecycle:
  1. Phase activation via _activate_ai_surface_analysis (scan_type gate)
  2. Tool generation via _ai_surface_analysis_tools
  3. ReconContextService.build_and_save() — ai-surface field population
  4. Full pipeline: real JSON → AISurfaceParser → FindingNormalizer → ReconContext
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from models.recon_context import ReconContext
from orchestrator_pkg.planning.phases._types import ToolTask
from orchestrator_pkg.planning.phases.ai_surface_analysis import (
    _activate_ai_surface_analysis,
    _ai_surface_analysis_tools,
)
from orchestrator_pkg.recon_context_service import ReconContextService
from parsers.normalizer import FindingNormalizer
from parsers.parsers.ai_surface import AISurfaceParser

# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "ai_surface_sample.json"


@pytest.fixture
def real_ai_surface_json(sample_fixture_path) -> str:
    """Load the real ai-surface scan output (19 findings, 8 categories)."""
    return sample_fixture_path.read_text(encoding="utf-8")


@pytest.fixture
def parsed_findings(real_ai_surface_json) -> list[dict]:
    """Parse real ai-surface JSON through AISurfaceParser."""
    return AISurfaceParser().parse(real_ai_surface_json)


@pytest.fixture
def normalizer() -> FindingNormalizer:
    return FindingNormalizer()


# ═══════════════════════════════════════════════════════════════════
# Phase activation tests
# ═══════════════════════════════════════════════════════════════════


def test_phase_activation_repo_scan():
    """scan_type='repo' → phase activates."""
    rc = ReconContext(target_url="https://github.com/example/repo", scan_type="repo")
    activated, reason = _activate_ai_surface_analysis(rc)
    assert activated, f"Should activate for repo scan, got: {reason}"
    assert "source code access available" in reason.lower()


def test_phase_activation_url_scan():
    """scan_type='url' → phase does NOT activate."""
    rc = ReconContext(target_url="https://example.com", scan_type="url")
    activated, reason = _activate_ai_surface_analysis(rc)
    assert not activated, f"Should NOT activate for URL scan, got: {reason}"
    assert "url-scan" in reason.lower()


def test_phase_activation_default_scan_type():
    """Default scan_type='url' → phase does NOT activate."""
    rc = ReconContext(target_url="https://example.com")  # scan_type defaults to "url"
    activated, reason = _activate_ai_surface_analysis(rc)
    assert not activated, f"Should NOT activate with default scan_type, got: {reason}"


def test_phase_activation_none_context():
    """None context → phase does NOT activate (graceful degradation)."""
    activated, reason = _activate_ai_surface_analysis(None)
    assert not activated, f"Should NOT activate for None context, got: {reason}"


def test_phase_activation_unknown_scan_type():
    """Unknown scan_type → phase does NOT activate."""
    rc = ReconContext(target_url="https://example.com", scan_type="api")
    activated, reason = _activate_ai_surface_analysis(rc)
    assert not activated, f"Should NOT activate for unknown scan_type, got: {reason}"


# ═══════════════════════════════════════════════════════════════════
# Tool generation tests
# ═══════════════════════════════════════════════════════════════════


def test_phase_tools_generated():
    """_ai_surface_analysis_tools returns the expected ToolTask."""
    rc = ReconContext(target_url="https://github.com/example/repo", scan_type="repo")
    tools = _ai_surface_analysis_tools(rc)
    assert len(tools) == 1, f"Expected 1 tool, got {len(tools)}"
    task = tools[0]
    assert isinstance(task, ToolTask), f"Expected ToolTask, got {type(task)}"
    assert task.tool_name == "ai-surface"
    assert "{target}" in (task.args_template or [])[0] if task.args_template else False
    assert task.timeout == 300
    assert task.priority == 10


def test_phase_tools_with_none_context():
    """_ai_surface_analysis_tools handles None gracefully."""
    tools = _ai_surface_analysis_tools(None)
    assert len(tools) == 1
    assert tools[0].tool_name == "ai-surface"


# ═══════════════════════════════════════════════════════════════════
# ReconContextService.build_and_save() tests
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_save_recon_context():
    """Mock save_recon_context to avoid Redis dependency."""
    with patch("orchestrator_pkg.recon_context_service.save_recon_context") as mock:
        yield mock


def test_recon_context_service_populates_ai_surface_fields(
    parsed_findings, mock_save_recon_context
):
    """build_and_save with ai-surface findings populates all ai-surface fields."""
    ctx = ReconContextService.build_and_save(
        engagement_id="test-eng-001",
        findings=parsed_findings,
        repo_url="https://github.com/example/repo",
    )
    assert ctx is not None
    assert ctx.has_source_access is True
    assert len(ctx.ai_surface_categories) == 8  # All 8 categories present
    assert "mcp-server" in ctx.ai_surface_categories
    assert "llm-sdk" in ctx.ai_surface_categories
    assert "agent-framework" in ctx.ai_surface_categories
    assert "env-key" in ctx.ai_surface_categories
    assert "model-gateway" in ctx.ai_surface_categories
    assert "ai-infra" in ctx.ai_surface_categories
    assert "api" in ctx.ai_surface_categories
    assert "vector-store" in ctx.ai_surface_categories
    # 4 confirmed + 11 likely + 4 none = 19 total
    assert ctx.ai_surface_confirmed_risk_count == 4
    assert ctx.ai_surface_likely_risk_count == 11
    # Specific flags
    assert ctx.has_mcp_servers is True
    assert ctx.has_agent_frameworks is True
    assert ctx.has_vector_stores is True
    assert ctx.has_model_gateways is True
    # Verify save was called
    mock_save_recon_context.assert_called_once()


def test_recon_context_service_counts_by_verdict(
    parsed_findings, mock_save_recon_context
):
    """Confirm and likely counts match the real ai-surface verdict distribution."""
    ctx = ReconContextService.build_and_save(
        engagement_id="test-eng-002",
        findings=parsed_findings,
        repo_url="https://github.com/example/repo",
    )
    # From real scan: 4 confirmed (3 mcp-server + 1 agent-framework), 11 likely, 4 none
    assert ctx.ai_surface_confirmed_risk_count == 4
    assert ctx.ai_surface_likely_risk_count == 11
    # Sum should not exceed total findings
    assert (
        ctx.ai_surface_confirmed_risk_count + ctx.ai_surface_likely_risk_count <= 19
    )


def test_recon_context_service_with_non_ai_findings(mock_save_recon_context):
    """build_and_save with no ai-surface findings leaves ai-surface fields at defaults."""
    non_ai_findings = [
        {
            "type": "SQL_INJECTION",
            "severity": "HIGH",
            "confidence": 0.9,
            "endpoint": "https://example.com/api",
            "evidence": {"payload": "' OR 1=1--"},
            "source_tool": "nuclei",
        }
    ]
    ctx = ReconContextService.build_and_save(
        engagement_id="test-eng-003",
        findings=non_ai_findings,
        repo_url="https://github.com/example/repo",
    )
    assert ctx is not None
    assert ctx.ai_surface_categories == []
    assert ctx.ai_surface_confirmed_risk_count == 0
    assert ctx.ai_surface_likely_risk_count == 0
    assert ctx.has_mcp_servers is False
    assert ctx.has_agent_frameworks is False
    assert ctx.has_vector_stores is False
    assert ctx.has_model_gateways is False
    assert ctx.has_source_access is True  # Still set for repo scans


def test_recon_context_service_empty_findings(mock_save_recon_context):
    """build_and_save with empty findings returns a valid ReconContext with defaults."""
    ctx = ReconContextService.build_and_save(
        engagement_id="test-eng-004",
        findings=[],
        repo_url="https://github.com/example/repo",
    )
    assert ctx is not None
    assert ctx.findings_count == 0
    assert ctx.ai_surface_categories == []
    assert ctx.ai_surface_confirmed_risk_count == 0
    assert ctx.ai_surface_likely_risk_count == 0
    assert ctx.has_source_access is True


# ═══════════════════════════════════════════════════════════════════
# Full pipeline integration tests
# ═══════════════════════════════════════════════════════════════════


def test_full_pipeline_real_json_to_recon_context(
    real_ai_surface_json, normalizer, mock_save_recon_context
):
    """Full E2E: real ai-surface JSON → parser → normalizer → ReconContext.

    This is the ultimate integration test — validates every layer of the
    ai-surface integration pipeline with real data.
    """
    # Step 1: Parse
    parser = AISurfaceParser()
    findings = parser.parse(real_ai_surface_json)
    assert len(findings) == 19, f"Parser: expected 19 findings, got {len(findings)}"

    # Step 2: Normalize
    normalized = normalizer.normalize_batch(findings, "ai-surface")
    assert len(normalized) == 19, f"Normalizer: expected 19, got {len(normalized)}"

    # Step 3: Build ReconContext
    ctx = ReconContextService.build_and_save(
        engagement_id="test-eng-full-pipeline",
        findings=findings,
        repo_url="https://github.com/example/repo",
    )
    assert ctx is not None
    assert ctx.findings_count == 19
    assert ctx.scan_type == "repo"
    assert ctx.has_source_access is True

    # Verify ai-surface fields
    assert len(ctx.ai_surface_categories) == 8
    assert ctx.ai_surface_confirmed_risk_count == 4
    assert ctx.ai_surface_likely_risk_count == 11
    assert ctx.has_mcp_servers is True
    assert ctx.has_agent_frameworks is True
    assert ctx.has_vector_stores is True
    assert ctx.has_model_gateways is True

    # Verify the context can produce an LLM summary (smoke test)
    summary = ctx.to_llm_summary()
    assert "scan type" in summary.lower()
    assert "repo" in summary.lower()
    assert "findings" in summary.lower()
    # The ReconContext is valid and ready for consumption


def test_full_pipeline_with_url_scan_does_not_activate(mock_save_recon_context):
    """URL scan type → phase activation check returns False even with ai-surface data."""
    rc = ReconContext(
        target_url="https://example.com",
        scan_type="url",
        ai_surface_categories=["mcp-server"],
        ai_surface_confirmed_risk_count=3,
        has_mcp_servers=True,
    )
    activated, reason = _activate_ai_surface_analysis(rc)
    assert not activated, (
        f"Phase should NOT activate for URL scan even with ai-surface data, "
        f"got: {reason}"
    )


def test_full_pipeline_context_roundtrip(parsed_findings, mock_save_recon_context):
    """ReconContext.to_dict() → ReconContext.from_dict() preserves ai-surface fields."""
    # Build
    ctx = ReconContextService.build_and_save(
        engagement_id="test-eng-roundtrip",
        findings=parsed_findings,
        repo_url="https://github.com/example/repo",
    )
    # Serialize
    data = ctx.to_dict()
    # Deserialize
    restored = ReconContext.from_dict(data)

    # Verify ai-surface fields survive roundtrip
    assert restored.ai_surface_categories == ctx.ai_surface_categories
    assert restored.ai_surface_confirmed_risk_count == ctx.ai_surface_confirmed_risk_count
    assert restored.ai_surface_likely_risk_count == ctx.ai_surface_likely_risk_count
    assert restored.has_mcp_servers == ctx.has_mcp_servers
    assert restored.has_agent_frameworks == ctx.has_agent_frameworks
    assert restored.has_vector_stores == ctx.has_vector_stores
    assert restored.has_model_gateways == ctx.has_model_gateways
    assert restored.has_source_access == ctx.has_source_access
    assert restored.scan_type == ctx.scan_type
    assert restored.findings_count == ctx.findings_count


@pytest.mark.parametrize(
    "scan_type,expected",
    [
        ("repo", True),
        ("url", False),
        ("api", False),
        ("", False),
    ],
)
def test_phase_activation_parametrized(scan_type, expected):
    """Phase activation is correctly gated by scan_type — parametrized."""
    rc = ReconContext(target_url="https://example.com", scan_type=scan_type)
    activated, _ = _activate_ai_surface_analysis(rc)
    assert activated == expected, (
        f"scan_type='{scan_type}' → activated={activated}, expected={expected}"
    )

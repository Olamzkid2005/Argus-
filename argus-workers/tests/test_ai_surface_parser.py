"""Tests for the ai-surface JSON parser — unit + integration."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.finding import EvidenceStrength, VulnerabilityFinding
from parsers.normalizer import FindingNormalizer
from parsers.parsers.ai_surface import AISurfaceParser


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "ai_surface_sample.json"


@pytest.fixture
def parser() -> AISurfaceParser:
    return AISurfaceParser()


@pytest.fixture
def normalizer() -> FindingNormalizer:
    return FindingNormalizer()


@pytest.fixture
def parsed_findings(parser, sample_fixture_path) -> list[dict]:
    raw = sample_fixture_path.read_text(encoding="utf-8")
    return parser.parse(raw)


# ═══════════════════════════════════════════════════════════════════
# Unit tests (parser output structure)
# ═══════════════════════════════════════════════════════════════════


def test_parse_full_report(parsed_findings, sample_fixture_path):
    """Verify that parsing the sample report produces correct findings."""
    raw = sample_fixture_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    expected_count = data.get("findings_count", 0)
    assert len(parsed_findings) == expected_count, (
        f"Expected {expected_count} findings, got {len(parsed_findings)}"
    )

    # Verify required fields are present on every finding
    for finding in parsed_findings:
        assert "type" in finding
        assert finding["type"].startswith("AI_SURFACE_")
        assert "severity" in finding
        assert "confidence" in finding
        assert 0.0 <= finding["confidence"] <= 1.0
        assert "endpoint" in finding
        assert "evidence" in finding
        assert "source_tool" in finding
        assert finding["source_tool"] == "ai-surface"
        # Extra metadata the parser adds
        assert "ai_surface_verdict" in finding
        assert "ai_surface_category" in finding


def test_parse_all_categories(parsed_findings):
    """All 8 ai-surface categories are represented in the parsed output."""
    categories_in_output: set[str] = set()
    for f in parsed_findings:
        cat = f["ai_surface_category"]
        categories_in_output.add(cat)
        # Each category should have its specific type prefix
        prefixes = {
            "mcp-server": "AI_SURFACE_MCP_SERVER",
            "llm-sdk": "AI_SURFACE_LLM_SDK",
            "agent-framework": "AI_SURFACE_AGENT_FRAMEWORK",
            "env-key": "AI_SURFACE_ENV_KEY",
            "model-gateway": "AI_SURFACE_MODEL_GATEWAY",
            "ai-infra": "AI_SURFACE_AI_INFRA",
            "api": "AI_SURFACE_API",
            "vector-store": "AI_SURFACE_VECTOR_STORE",
        }
        expected_prefix = prefixes.get(cat)
        assert expected_prefix is not None, (
            f"Unknown category '{cat}' in parsed findings — add to prefixes dict"
        )
        assert f["type"].startswith(expected_prefix), (
            f"Category '{cat}' type '{f['type']}' doesn't start with '{expected_prefix}'"
        )

    expected_categories = {
        "mcp-server", "llm-sdk", "agent-framework", "env-key",
        "model-gateway", "ai-infra", "api", "vector-store",
    }
    assert categories_in_output == expected_categories, (
        f"Expected categories {expected_categories}, got {categories_in_output}"
    )


def test_parse_finding_type_format(parsed_findings):
    """Verify finding type format: AI_SURFACE_{CATEGORY}_{SANITIZED_NAME}."""
    mcp_findings = [f for f in parsed_findings if "MCP_SERVER" in f["type"]]
    assert len(mcp_findings) == 3
    for f in mcp_findings:
        assert f["type"].startswith("AI_SURFACE_MCP_SERVER_")


def test_parse_evidence_structure(parsed_findings):
    """Verify the evidence dict contains expected structural fields."""
    # Find a finding with audit (deep-dive finding)
    audited = [f for f in parsed_findings if f["evidence"].get("audit")]
    assert len(audited) > 0, "Expected at least one finding with audit"

    for f in audited:
        evidence = f["evidence"]
        # Core fields
        assert "surface" in evidence
        assert "category" in evidence
        assert "detector_name" in evidence
        assert "verdict" in evidence
        assert "files" in evidence
        assert "risk_indicators" in evidence
        assert "permissions" in evidence
        # Audit sub-structure
        audit = evidence["audit"]
        assert "risk_flags" in audit
        assert "secrets" in audit
        assert "trust_score" in audit
        assert "owasp_mappings" in audit


def test_parse_risk_flags_structure(parsed_findings):
    """Verify risk_flags within audit have required fields."""
    for f in parsed_findings:
        audit = f["evidence"].get("audit")
        if not audit:
            continue
        for rf in audit.get("risk_flags", []):
            assert "flag" in rf
            assert "severity" in rf
            assert "description" in rf
            assert "remediation" in rf
            # OWASP is a common field
            if "owasp" in rf:
                assert isinstance(rf["owasp"], list)


def test_parse_bridges_structure(parsed_findings):
    """Verify bridge entries have required fields when present."""
    bridged = [f for f in parsed_findings if f["evidence"].get("bridges")]
    assert len(bridged) > 0, "Expected at least one finding with bridges"
    for f in bridged:
        for bridge in f["evidence"]["bridges"]:
            assert "sku" in bridge
            assert "label" in bridge
            assert "status" in bridge
            assert bridge["status"] in ("live", "coming")


def test_parse_confidence_range_by_verdict(parsed_findings):
    """Confidence scores match their verdict tiers."""
    for f in parsed_findings:
        verdict = f["ai_surface_verdict"]
        if verdict == "confirmed":
            assert f["confidence"] >= 0.85, (
                f"CONFIRMED finding '{f['type']}' has confidence {f['confidence']}, expected >= 0.85"
            )
        elif verdict == "likely":
            assert 0.4 <= f["confidence"] <= 0.6, (
                f"LIKELY finding '{f['type']}' has confidence {f['confidence']}, expected 0.4-0.6"
            )
        else:
            # Inventory with risk indicators → 0.5; pure inventory → 0.5
            assert f["confidence"] == 0.5, (
                f"Inventory finding '{f['type']}' has confidence {f['confidence']}, expected 0.5"
            )


def test_parse_endpoint_format_by_category(parsed_findings):
    """Endpoint format matches category type."""
    for f in parsed_findings:
        cat = f["ai_surface_category"]
        ep = f["endpoint"]
        if cat == "llm-sdk" or cat == "env-key":
            assert ep.startswith("file:"), (
                f"{cat} endpoint should be file: prefix, got '{ep}'"
            )
        elif cat == "api":
            # API findings in our fixture use method+path format
            assert " " in ep or "file:" in ep, (
                f"api endpoint should have method+path, got '{ep}'"
            )
        else:
            assert ep != "", f"{cat} finding has empty endpoint"


# ═══════════════════════════════════════════════════════════════════
# Integration tests (VulnerabilityFinding schema conformance)
# ═══════════════════════════════════════════════════════════════════


def test_integration_all_findings_normalize(parsed_findings, normalizer):
    """Every parsed finding can be normalized to a valid VulnerabilityFinding.

    This is the primary integration contract — the parser output MUST be
    consumable by the FindingNormalizer without validation errors.
    """
    normalized = normalizer.normalize_batch(parsed_findings, "ai-surface")
    assert len(normalized) == len(parsed_findings), (
        f"Expected {len(parsed_findings)} normalized findings, "
        f"got {len(normalized)}. Some findings failed validation."
    )

    for nf in normalized:
        assert isinstance(nf, VulnerabilityFinding)
        assert isinstance(nf.type, str)
        assert nf.type != ""
        assert nf.severity is not None
        assert 0.0 <= nf.confidence <= 1.0
        assert isinstance(nf.endpoint, str)
        assert isinstance(nf.evidence, dict)
        assert nf.source_tool == "ai-surface"


def test_integration_normalize_sets_evidence_strength(parsed_findings, normalizer):
    """Normalization assigns evidence strength to ai-surface findings."""
    normalized = normalizer.normalize_batch(parsed_findings, "ai-surface")
    for nf in normalized:
        assert nf.evidence_strength is not None
        assert nf.fp_likelihood is not None
        assert 0.0 <= nf.fp_likelihood <= 1.0


def test_integration_normalize_preserves_ai_surface_fields(parsed_findings, normalizer):
    """The normalizer passes through ai-surface-specific evidence fields."""
    normalized = normalizer.normalize_batch(parsed_findings, "ai-surface")
    for nf, raw in zip(normalized, parsed_findings, strict=False):
        # Core fields are preserved
        assert nf.type == raw["type"]  # _normalize_type falls through for AI_SURFACE_* types
        # Evidence dict should contain ai-surface fields
        if raw["evidence"].get("audit"):
            assert "audit" in nf.evidence
            assert "risk_flags" in nf.evidence["audit"]
        if raw["evidence"].get("bridges"):
            assert "bridges" in nf.evidence


def test_integration_normalize_handles_verified_flag(parsed_findings, normalizer):
    """Findings without verified flag get MINIMAL evidence strength."""
    normalized = normalizer.normalize_batch(parsed_findings, "ai-surface")
    for nf in normalized:
        # ai-surface findings are static analysis — no request/response
        # So evidence_strength should be MINIMAL (normalizer default for unverified findings)
        assert nf.evidence_strength == EvidenceStrength.MINIMAL, (
            f"Expected MINIMAL evidence for static analysis finding, "
            f"got {nf.evidence_strength}"
        )


def test_integration_direct_vulnerability_finding_construction(parsed_findings):
    """Parser output fields can construct VulnerabilityFinding directly.

    This tests the tightest integration path: can the parser output
    be used to construct a VulnerabilityFinding without the normalizer?
    """
    for raw in parsed_findings:
        try:
            vf = VulnerabilityFinding(
                type=raw["type"],
                severity=raw["severity"],
                confidence=raw["confidence"],
                endpoint=raw["endpoint"],
                evidence=raw["evidence"],
                source_tool=raw["source_tool"],
            )
            assert vf.type == raw["type"]
            assert vf.severity.value == raw["severity"]
            assert vf.confidence == raw["confidence"]
            assert vf.endpoint == raw["endpoint"]
            assert vf.evidence == raw["evidence"]
            assert vf.source_tool == raw["source_tool"]
        except ValidationError as e:
            pytest.fail(f"VulnerabilityFinding construction failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# Edge case unit tests
# ═══════════════════════════════════════════════════════════════════


def test_parse_confirmed_verdict_high_confidence():
    """CONFIRMED verdict with high severity → confidence in upper range (0.85-0.95)."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            "surface": "MCP Server: stripe-mcp",
            "category": "mcp-server",
            "evidence": {"files": [".mcp.json"], "snippet": "...", "metadata": {}},
            "permissions": ["refund", "charge"],
            "risk_indicators": ["financial action exposed"],
            "detector_name": "mcp_audit",
            "severity": "high",
            "audit": {"risk_flags": [{"flag": "financial-action", "severity": "high"}]},
            "verdict": "confirmed"
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    assert findings[0]["confidence"] >= 0.85
    assert findings[0]["severity"] == "HIGH"


def test_parse_likely_verdict_medium_confidence():
    """LIKELY verdict → confidence in lower range (0.4-0.6)."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            "surface": "Anthropic SDK",
            "category": "llm-sdk",
            "evidence": {"files": ["src/llm_service.py"], "snippet": "from anthropic import Anthropic", "metadata": {}},
            "permissions": [],
            "risk_indicators": ["non-literal data flows into LLM call"],
            "detector_name": "llm_sdks",
            "severity": None,
            "audit": None,
            "verdict": "likely"
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    assert 0.4 <= findings[0]["confidence"] <= 0.6


def test_parse_inventory_no_verdict():
    """Pure inventory finding (no verdict, no severity) → default confidence (0.5)."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            "surface": "AWS Bedrock",
            "category": "llm-sdk",
            "evidence": {"files": ["src/workflow.py"], "snippet": "...", "metadata": {}},
            "permissions": [],
            "risk_indicators": [],
            "detector_name": "llm_sdks",
            "severity": None,
            "audit": None,
            "verdict": None
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    assert findings[0]["confidence"] == 0.5


def test_parse_api_finding():
    """API category findings extract method + path as endpoint."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            "surface": "REST API: GET /orders/{order_id}",
            "category": "api",
            "evidence": {
                "files": ["src/api.py"],
                "snippet": "@app.get(\"/orders/{order_id}\")",
                "line_numbers": [19],
                "metadata": {
                    "method": "GET",
                    "path": "/orders/{order_id}",
                    "framework": "fastapi"
                }
            },
            "permissions": [],
            "risk_indicators": ["object-id in path (BOLA candidate)"],
            "detector_name": "api_endpoints",
            "severity": None,
            "audit": None,
            "bridges": [{"sku": "api-runtime", "label": "Test in APIsec", "url": "https://apisec.ai", "status": "live"}],
            "disposition": "validate-runtime",
            "runtime_status": "live",
            "runtime_question": "Is this endpoint exploitable?",
            "verdict": "likely"
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    assert findings[0]["endpoint"] == "GET /orders/{order_id}"
    assert findings[0]["severity"] == "INFO"  # null severity → INFO


def test_parse_invalid_json():
    """Invalid JSON returns empty list, does not crash."""
    parser = AISurfaceParser()
    findings = parser.parse("{invalid json!!!")
    assert findings == []


def test_parse_empty_findings():
    """Report with no findings returns empty list."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 0,
        "findings": []
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert findings == []


def test_parse_sanitizes_special_chars_in_type():
    """Surface names with special characters get sanitized in type generation."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            "surface": "MCP Server (in-house): <src/orders_mcp.py>",
            "category": "mcp-server",
            "evidence": {"files": ["src/orders.py"], "snippet": "", "metadata": {}},
            "permissions": [],
            "risk_indicators": [],
            "detector_name": "mcp_audit",
            "severity": None,
            "audit": None,
            "bridges": [],
            "disposition": "resolve-here",
            "runtime_status": "n/a",
            "runtime_question": None,
            "verdict": None
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    typ = findings[0]["type"]
    # All special chars (angle brackets, parens, colons) should be stripped
    for ch in ("<", ">", "(", ")", ":", "."):
        assert ch not in typ, f"Special char '{ch}' found in type: {typ}"
    # Type should start with the correct category prefix
    assert typ.startswith("AI_SURFACE_MCP_SERVER_"), f"Unexpected type prefix: {typ}"
    # Only uppercase ASCII, digits, and underscores are allowed
    assert all(c.isupper() or c.isdigit() or c == "_" for c in typ), (
        f"Type contains lowercase or other chars: {typ}"
    )
    # Should not be unreasonably long
    assert len(typ) <= 100, f"Type too long: {len(typ)} chars ({typ})"


def test_parse_file_finding_no_endpoint():
    """Finding with no files and no metadata defaults to UNKNOWN endpoint."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            "surface": "Suspicious Activity",
            "category": "unknown",
            "evidence": {"files": [], "snippet": "", "metadata": {}},
            "permissions": [],
            "risk_indicators": [],
            "detector_name": "unknown",
            "severity": None,
            "audit": None,
            "bridges": [],
            "disposition": "resolve-here",
            "runtime_status": "n/a",
            "runtime_question": None,
            "verdict": None
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    assert findings[0]["endpoint"] == "UNKNOWN"


def test_parse_missing_fields_structure():
    """Missing optional fields in input produce safe defaults in output."""
    raw = json.dumps({
        "schema_version": "1.0",
        "findings_count": 1,
        "findings": [{
            # Minimal finding — only required fields
            "surface": "Test",
            "category": "mcp-server",
            "evidence": {"files": ["test.py"], "metadata": {}},
            "permissions": [],
            "risk_indicators": [],
            "detector_name": "test",
            "severity": None,
            "audit": None,
            "bridges": [],
            "disposition": "resolve-here",
            "runtime_status": "n/a",
            "runtime_question": None,
            "verdict": None
        }]
    })
    parser = AISurfaceParser()
    findings = parser.parse(raw)
    assert len(findings) == 1
    f = findings[0]
    # All required fields should have safe values
    assert f["type"] == "AI_SURFACE_MCP_SERVER_TEST"
    assert f["severity"] == "INFO"  # null → INFO
    assert f["confidence"] == 0.5  # no verdict, no risk indicators → 0.5
    assert f["endpoint"] == "file:test.py"
    assert f["evidence"]["verdict"] is None
    assert f["evidence"]["risk_indicators"] == []
    assert f["ai_surface_verdict"] is None
    assert f["ai_surface_category"] == "mcp-server"

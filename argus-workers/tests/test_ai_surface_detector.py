"""Tests for AI/LLM Surface Detection.

Tests both the standalone detect_ai_surface() function and the
end-to-end fixture-based detection using the ai-chatbot Flask app.

Coverage:
  - Chatbot widget detection from HTML (Intercom patterns)
  - AI API endpoint detection from ReconContext api_endpoints
  - LLM provider header detection from response headers
  - Advisory finding generation (build_ai_advisory_finding)
  - Negative case: no AI detection on static HTML
  - E2E: fixture app triggers advisory finding via HTTP fetch
"""

import os
import sys
import urllib.request
import urllib.error

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.recon_context import ReconContext
from tools.ai_surface_detector import (
    detect_ai_surface,
    build_ai_advisory_finding,
    CHATBOT_PROVIDER_PATTERNS,
    AI_API_PATHS,
)


class TestAiSurfaceDetectorUnit:
    """Unit tests for the AI surface detector — no external dependencies."""

    def test_chatbot_widget_detected_from_html(self):
        """Intercom widget pattern in HTML should set has_ai_chatbot=True."""
        html = """<html><head><script src="https://widget.intercom.io/widget/abc123"></script></head></html>"""
        ctx = ReconContext(target_url="https://example.com")
        detect_ai_surface(ctx, html_content=html)
        assert ctx.has_ai_chatbot is True
        assert ctx.llm_provider_detected == "intercom"

    def test_drift_widget_detected_from_html(self):
        """Drift chatbot widget pattern should be detected."""
        html = """<html><script src="https://js.drift.com/drift.js"></script></html>"""
        ctx = ReconContext(target_url="https://example.com")
        detect_ai_surface(ctx, html_content=html)
        assert ctx.has_ai_chatbot is True
        assert ctx.llm_provider_detected == "drift"

    def test_tawk_widget_detected_from_html(self):
        """Tawk.to widget pattern should be detected."""
        html = """<html><script src="https://embed.tawk.to/abc123"></script></html>"""
        ctx = ReconContext(target_url="https://example.com")
        detect_ai_surface(ctx, html_content=html)
        assert ctx.has_ai_chatbot is True
        assert ctx.llm_provider_detected == "tawk"

    def test_ai_api_endpoint_detected_from_recon_context(self):
        """/api/chat in api_endpoints should set has_ai_chatbot=True and populate ai_endpoints."""
        ctx = ReconContext(
            target_url="https://example.com",
            api_endpoints=["/api/chat", "/api/users", "/graphql"],
        )
        detect_ai_surface(ctx)
        assert ctx.has_ai_chatbot is True
        assert "/api/chat" in ctx.ai_endpoints

    def test_openai_completions_endpoint_detected(self):
        """/v1/chat/completions should be detected as AI API path."""
        ctx = ReconContext(
            target_url="https://api.example.com",
            api_endpoints=["/v1/chat/completions", "/v1/models"],
        )
        detect_ai_surface(ctx)
        assert ctx.has_ai_chatbot is True
        assert "/v1/chat/completions" in ctx.ai_endpoints

    def test_provider_header_detection(self):
        """Response headers with AI provider signatures should trigger detection."""
        html = "<html><body>Hello</body></html>"
        headers = {"x-request-id": "req_abc123", "openai-version": "2024-01-01"}
        ctx = ReconContext(target_url="https://example.com")
        detect_ai_surface(ctx, html_content=html, response_headers=headers)
        assert ctx.has_ai_chatbot is True
        assert ctx.llm_provider_detected == "openai"

    def test_openai_content_pattern_detected(self):
        """ChatGPT/OpenAI references in page content should trigger detection."""
        html = """<html><body><p>Powered by ChatGPT and OpenAI technology</p></body></html>"""
        ctx = ReconContext(target_url="https://example.com")
        detect_ai_surface(ctx, html_content=html)
        assert ctx.has_ai_chatbot is True
        assert ctx.llm_provider_detected == "openai"

    def test_no_false_positive_on_static_html(self):
        """Static HTML without any AI patterns should not trigger detection."""
        html = """<html><body><h1>Hello, world!</h1><p>Static site content.</p></body></html>"""
        ctx = ReconContext(target_url="https://example.com")
        detect_ai_surface(ctx, html_content=html)
        assert ctx.has_ai_chatbot is False
        assert ctx.ai_endpoints == []

    def test_no_false_positive_on_regular_endpoints(self):
        """Regular API endpoints should not be mistaken for AI endpoints."""
        ctx = ReconContext(
            target_url="https://example.com",
            api_endpoints=["/api/users", "/api/products", "/api/orders"],
        )
        detect_ai_surface(ctx)
        assert ctx.has_ai_chatbot is False
        assert ctx.ai_endpoints == []

    def test_advisory_finding_built_with_chatbot(self):
        """Advisory finding should be generated when AI surface is detected."""
        ctx = ReconContext(
            target_url="https://example.com",
            has_ai_chatbot=True,
            ai_endpoints=["/api/chat"],
            llm_provider_detected="openai",
        )
        finding = build_ai_advisory_finding(ctx, "https://example.com")
        assert finding is not None
        assert finding["type"] == "AI_SURFACE_DETECTED"
        assert finding["severity"] == "INFO"
        assert finding["confidence"] == 0.9  # Chatbot detected = high confidence
        assert "description" in finding
        assert "remediation" in finding

    def test_advisory_finding_built_with_endpoints_only(self):
        """Advisory finding should be generated when only endpoints match (no chatbot)."""
        ctx = ReconContext(
            target_url="https://example.com",
            has_ai_chatbot=True,
            ai_endpoints=["/v1/completions"],
        )
        finding = build_ai_advisory_finding(ctx, "https://example.com")
        assert finding is not None
        assert finding["type"] == "AI_SURFACE_DETECTED"
        assert finding["severity"] == "INFO"
        assert finding["confidence"] == 0.9  # has_ai_chatbot=True = high confidence
        assert "PyRIT" in finding["remediation"]

    def test_no_finding_when_no_ai_surface(self):
        """build_ai_advisory_finding should return None when no AI surface detected."""
        ctx = ReconContext(target_url="https://example.com")
        finding = build_ai_advisory_finding(ctx, "https://example.com")
        assert finding is None

    def test_all_chatbot_providers_have_patterns(self):
        """All known chatbot providers should have at least one detection pattern."""
        for provider, patterns in CHATBOT_PROVIDER_PATTERNS.items():
            assert len(patterns) > 0, f"Provider '{provider}' has no patterns"

    def test_all_ai_api_paths_are_non_empty(self):
        """All AI API paths should be non-empty strings."""
        for path in AI_API_PATHS:
            assert path.startswith("/") or path == path, f"API path '{path}' looks suspicious"


# E2E tests auto-skip when Flask is not installed or RUN_E2E_TESTS=1 is not set.
# Flask is listed in requirements-dev.txt and available in CI.
_has_flask = True
_skip_e2e_reason = ""
try:
    import flask  # noqa: F401
except ImportError:
    _has_flask = False
    _skip_e2e_reason = "Flask not installed — install with: pip install flask"
if not os.environ.get("RUN_E2E_TESTS"):
    _skip_e2e_reason = (
        _skip_e2e_reason or "E2E tests require RUN_E2E_TESTS=1 env var"
    )


@pytest.mark.skipif(
    not os.environ.get("RUN_E2E_TESTS") or not _has_flask,
    reason=_skip_e2e_reason or "E2E tests not enabled",
)
class TestAiSurfaceDetectorIntegration:
    """Integration tests using the ai-chatbot Flask fixture.

    These tests start the ai-chatbot Flask app as a subprocess, fetch its
    homepage, and run the AI surface detector against real HTTP responses.
    They are skipped when Flask is not installed or RUN_E2E_TESTS=1 is unset.
    """

    @pytest.mark.parametrize("fixture_app", ["ai-chatbot"], indirect=True)
    def test_endpoint_detection_via_http(self, fixture_app):
        """Fetch the fixture homepage and verify detector finds AI patterns.

        This test starts the ai-chatbot Flask app, fetches its homepage,
        and runs the AI surface detector against the fetched HTML and
        any discovered API endpoints.
        """
        # Fetch the homepage HTML
        try:
            resp = urllib.request.urlopen(f"{fixture_app}/", timeout=5)
            html_content = resp.read().decode("utf-8")
            response_headers = dict(resp.headers)
        except (urllib.error.URLError, OSError) as e:
            pytest.fail(f"Could not fetch fixture homepage: {e}")

        ctx = ReconContext(target_url=fixture_app)
        detect_ai_surface(ctx, html_content=html_content, response_headers=response_headers)

        # The fixture has Intercom script tags in HTML
        assert ctx.has_ai_chatbot is True, "Chatbot should be detected on fixture homepage"
        assert ctx.llm_provider_detected == "intercom"

        # Probe known AI API paths
        ai_endpoints_found = []
        for path in ["/api/chat", "/api/v1/completions"]:
            try:
                probe_url = f"{fixture_app}{path}"
                if "completions" in path:
                    req = urllib.request.Request(probe_url, data=b'{"prompt":"test"}', method="POST")
                    resp = urllib.request.urlopen(req, timeout=3)
                else:
                    resp = urllib.request.urlopen(f"{probe_url}?message=hi", timeout=3)
                if resp.status == 200:
                    ai_endpoints_found.append(path)
            except (urllib.error.URLError, OSError):
                pass

        assert len(ai_endpoints_found) > 0, f"Should discover AI endpoints, found: {ai_endpoints_found}"

    @pytest.mark.skipif(
        not os.environ.get("RUN_E2E_TESTS"),
        reason="E2E tests require RUN_E2E_TESTS=1 env var (needs Flask installed)",
    )
    @pytest.mark.parametrize("fixture_app", ["ai-chatbot"], indirect=True)
    def test_advisory_finding_generated_from_fixture(self, fixture_app):
        """The full pipeline: fetch fixture → detect AI → generate advisory finding."""
        try:
            resp = urllib.request.urlopen(f"{fixture_app}/", timeout=5)
            html_content = resp.read().decode("utf-8")
            response_headers = dict(resp.headers)
        except (urllib.error.URLError, OSError) as e:
            pytest.fail(f"Could not fetch fixture homepage: {e}")

        ctx = ReconContext(target_url=fixture_app)
        detect_ai_surface(ctx, html_content=html_content, response_headers=response_headers)

        finding = build_ai_advisory_finding(ctx, fixture_app)
        assert finding is not None, "Advisory finding should be generated"
        assert finding["type"] == "AI_SURFACE_DETECTED"
        assert finding["severity"] == "INFO"
        assert "description" in finding
        assert "remediation" in finding

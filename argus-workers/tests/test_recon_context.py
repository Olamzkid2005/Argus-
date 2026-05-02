"""Tests for ReconContext dataclass."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.recon_context import ReconContext


class TestReconContext:
    def test_to_llm_summary_stays_under_token_limit(self):
        """Summary must stay under ~800 tokens (3200 chars as proxy)."""
        ctx = ReconContext(
            target_url="https://example.com",
            live_endpoints=[f"https://example.com/page/{i}" for i in range(100)],
            subdomains=[f"sub{i}.example.com" for i in range(50)],
            open_ports=[{"port": 80, "service": "http"}, {"port": 443, "service": "https"}],
            tech_stack=["WordPress 6.4", "PHP 8.1", "nginx", "MySQL"],
            crawled_paths=[f"/path/{i}" for i in range(50)],
            parameter_bearing_urls=[f"https://example.com/api?id={i}" for i in range(30)],
            auth_endpoints=["/login", "/oauth/authorize"],
            api_endpoints=["/api/v1/users", "/api/v1/posts", "/graphql"],
            findings_count=500,
            has_login_page=True,
            has_api=True,
            has_file_upload=True,
        )
        summary = ctx.to_llm_summary()
        assert len(summary) < 3200, f"Summary too long: {len(summary)} chars"

    def test_auth_detection_from_crawled_paths(self):
        """has_login_page should be True when auth endpoints exist."""
        ctx = ReconContext(
            target_url="https://example.com",
            auth_endpoints=["/login"],
            has_login_page=True,
        )
        summary = ctx.to_llm_summary()
        assert "LOGIN" in summary

    def test_api_detection(self):
        """has_api should be True when API endpoints exist."""
        ctx = ReconContext(
            target_url="https://example.com",
            api_endpoints=["/api/v1/users"],
            has_api=True,
        )
        summary = ctx.to_llm_summary()
        assert "API" in summary

    def test_empty_context_summary(self):
        """Empty context should produce a valid summary without errors."""
        ctx = ReconContext(target_url="https://example.com")
        summary = ctx.to_llm_summary()
        assert "example.com" in summary
        assert "Live endpoints: 0" in summary

    def test_to_dict_and_from_dict_roundtrip(self):
        """Serialization roundtrip should preserve data."""
        ctx = ReconContext(
            target_url="https://example.com",
            live_endpoints=["https://example.com/a"],
            has_login_page=True,
        )
        d = ctx.to_dict()
        restored = ReconContext.from_dict(d)
        assert restored.target_url == ctx.target_url
        assert restored.live_endpoints == ctx.live_endpoints
        assert restored.has_login_page is True

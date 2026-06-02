"""Tests for Target Memory system."""

from database.repositories.target_profile_repository import (
    TargetProfileRepository,
)


class TestTargetProfile:
    def test_extract_domain_full_url(self):
        assert TargetProfileRepository._extract_domain(
            "https://www.example.com/path"
        ) == "www.example.com"

    def test_extract_domain_with_port(self):
        assert TargetProfileRepository._extract_domain(
            "example.com:8080"
        ) == "example.com:8080"

    def test_extract_domain_no_scheme(self):
        assert TargetProfileRepository._extract_domain(
            "example.com"
        ) == "example.com"

    def test_to_llm_context_empty_for_first_scan(self):
        result = TargetProfileRepository.to_llm_context(None, {})
        assert result == ""

    def test_to_llm_context_none_profile(self):
        result = TargetProfileRepository.to_llm_context(None, None)
        assert result == ""

    def test_to_llm_context_shows_prior_scans(self):
        result = TargetProfileRepository.to_llm_context(None, {
            "total_scans": 3,
            "best_tools": [
                {"tool": "nuclei", "finding_count": 5}
            ],
            "noisy_tools": ["nikto"],
            "confirmed_finding_types": ["XSS", "SQLI"],
            "high_value_endpoints": ["/api/admin/users"],
        })
        assert "3 prior scans" in result
        assert "nuclei" in result
        assert "nikto" in result
        assert "XSS" in result
        assert "/api/admin/users" in result

    def test_to_llm_context_empty_when_no_tools(self):
        result = TargetProfileRepository.to_llm_context(None, {
            "total_scans": 1,
            "best_tools": [],
            "noisy_tools": [],
            "confirmed_finding_types": [],
            "high_value_endpoints": [],
        })
        assert "1 prior scan" in result
        # Should not mention any tools since none were found
        assert "Tools that found" not in result

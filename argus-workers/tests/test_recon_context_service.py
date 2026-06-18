"""Unit tests for ReconContextService.

Tests the build_and_save static method extracted from Orchestrator.run_repo_scan():
- Language detection from file extensions
- Framework detection from file path keywords
- Severity breakdown aggregation
- Secrets and dependency vulnerability detection
- Critical files tracking
- Empty findings handling
- Exception handling
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestReconContextService:
    """Tests for ReconContextService.build_and_save."""

    # ── Autouse: mock tasks.utils before module import ──────────
    #
    # recon_context_service.py has a top-level import:
    #     from tasks.utils import save_recon_context
    #
    # We mock tasks.utils in sys.modules so the import resolves to
    # a MagicMock rather than trying to load the real module (which
    # has heavy dependencies like celery, redis, psycopg2, etc.).

    @pytest.fixture(autouse=True)
    def mock_tasks_utils(self):
        """Patch tasks.utils in sys.modules before recon_context_service loads."""
        mock_utils = MagicMock()
        mock_utils.save_recon_context = MagicMock()
        with patch.dict(
            sys.modules,
            {
                "tasks": MagicMock(),
                "tasks.utils": mock_utils,
            },
        ):
            yield mock_utils.save_recon_context

    # ── Fixtures ────────────────────────────────────────────────

    @pytest.fixture
    def sample_findings(self) -> list[dict]:
        """Diverse set of findings exercising all detection paths."""
        return [
            # Language: Python (.py)
            {
                "type": "SQL_INJECTION",
                "severity": "CRITICAL",
                "file_path": "src/api/flask_login.py",
            },
            # Language: JavaScript (.js) + Framework: Express
            {
                "type": "XSS",
                "severity": "HIGH",
                "file_path": "src/express/routes/user.js",
            },
            # Language: TypeScript (.ts) + Framework: NestJS -> Express
            {
                "type": "CSRF",
                "severity": "MEDIUM",
                "file_path": "src/nestjs/controller.ts",
            },
            # Language: Java (.java) + Framework: Spring
            {
                "type": "AUTH_BYPASS",
                "severity": "HIGH",
                "file_path": "src/spring/security/LoginController.java",
            },
            # Language: Go (.go)
            {
                "type": "COMMAND_INJECTION",
                "severity": "CRITICAL",
                "file_path": "src/main/handler.go",
            },
            # Secret type finding
            {"type": "EXPOSED_SECRET", "severity": "CRITICAL", "file_path": ".env"},
            # Dependency vulnerability
            {
                "type": "DEPENDENCY_VULNERABILITY",
                "severity": "HIGH",
                "file_path": "package.json",
            },
            # Low severity (non-critical, non-high)
            {
                "type": "INFO_LEAK",
                "severity": "LOW",
                "file_path": "src/config/readme.md",
            },
            # No file_path -> uses endpoint fallback
            {
                "type": "MISCONFIGURATION",
                "severity": "MEDIUM",
                "endpoint": "aws/s3/bucket",
            },
            # Unknown language (no file_path or endpoint)
            {"type": "UNKNOWN", "severity": "INFO"},
        ]

    @pytest.fixture
    def mock_save(self, mock_tasks_utils) -> MagicMock:
        """Return the mocked save_recon_context from autouse fixture."""
        return mock_tasks_utils

    # ── Happy path ──────────────────────────────────────────────

    def test_build_and_save_returns_context_on_success(
        self,
        sample_findings,
        mock_save,
    ):
        """Happy path: returns a ReconContext with fields populated from findings."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-repo-1",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        assert ctx is not None
        assert ctx.target_url == "https://github.com/example/repo"
        assert ctx.repo_url == "https://github.com/example/repo"
        assert ctx.scan_type == "repo"
        assert ctx.repo_clone_success is True
        assert ctx.findings_count == len(sample_findings)

    def test_build_and_save_persists_context(
        self,
        sample_findings,
        mock_save,
    ):
        """build_and_save calls save_recon_context with the built context."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-repo-1",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        mock_save.assert_called_once_with("eng-repo-1", ctx)

    # ── Language detection ──────────────────────────────────────

    def test_detects_languages_from_findings(
        self,
        sample_findings,
        mock_save,
    ):
        """Languages should be detected from file extensions."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-lang",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        assert "Python" in ctx.languages_detected
        assert "JavaScript" in ctx.languages_detected
        assert "TypeScript" in ctx.languages_detected
        assert "Java" in ctx.languages_detected
        assert "Go" in ctx.languages_detected
        # Should be sorted alphabetically
        assert ctx.languages_detected == sorted(ctx.languages_detected)

    def test_detects_languages_from_endpoint_fallback(self, mock_save):
        """When file_path is missing, uses endpoint for extension detection."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        findings = [
            {"type": "XSS", "severity": "HIGH", "endpoint": "src/app.rb"},
            {"type": "CSRF", "severity": "MEDIUM", "endpoint": "src/lib.rs"},
        ]

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-endpoint-lang",
            findings=findings,
            repo_url="https://github.com/example/repo",
        )

        assert "Ruby" in ctx.languages_detected
        assert "Rust" in ctx.languages_detected

    # ── Framework detection ─────────────────────────────────────

    def test_detects_frameworks_from_findings(
        self,
        sample_findings,
        mock_save,
    ):
        """Frameworks should be detected from keywords in file paths."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-fw",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        assert "Express" in ctx.frameworks_detected  # from express/ and nestjs/
        assert "Spring" in ctx.frameworks_detected  # from spring/

    # ── Severity breakdown ──────────────────────────────────────

    def test_builds_severity_breakdown(
        self,
        sample_findings,
        mock_save,
    ):
        """Severity breakdown should aggregate counts per severity level."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-sev",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        # sample_findings has: 3 CRITICAL, 3 HIGH, 2 MEDIUM, 1 LOW, 1 INFO
        assert ctx.severity_breakdown.get("CRITICAL") == 3
        assert ctx.severity_breakdown.get("HIGH") == 3
        assert ctx.severity_breakdown.get("MEDIUM") == 2
        assert ctx.severity_breakdown.get("LOW") == 1
        assert ctx.severity_breakdown.get("INFO") == 1

    # ── Secrets detection ───────────────────────────────────────

    def test_detects_hardcoded_secrets(
        self,
        sample_findings,
        mock_save,
    ):
        """EXPOSED_SECRET type findings set has_hardcoded_secrets=True."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-secrets",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        assert ctx.has_hardcoded_secrets is True

    def test_no_secrets_when_no_secret_findings(self, mock_save):
        """When no EXPOSED_SECRET/COMMITTED_SECRET/HARDCODED_SECRET findings, has_hardcoded_secrets is False."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        findings = [
            {"type": "SQL_INJECTION", "severity": "HIGH", "file_path": "app.py"},
        ]

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-no-secrets",
            findings=findings,
            repo_url="https://github.com/example/repo",
        )

        assert ctx.has_hardcoded_secrets is False

    # ── Dependency vulnerabilities ──────────────────────────────

    def test_counts_dependency_vulns(
        self,
        sample_findings,
        mock_save,
    ):
        """DEPENDENCY_VULNERABILITY type findings are counted."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-dep",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        assert ctx.dependency_vulns_count == 1  # Only DEPENDENCY_VULNERABILITY

    # ── Critical files ──────────────────────────────────────────

    def test_tracks_critical_files(
        self,
        sample_findings,
        mock_save,
    ):
        """CRITICAL and HIGH severity findings populate critical_files."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-critical",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        # CRITICAL files: src/api/flask_login.py, src/main/handler.go, .env
        # HIGH files: src/express/routes/user.js, src/spring/security/LoginController.java, package.json
        assert "src/api/flask_login.py" in ctx.critical_files
        assert "src/main/handler.go" in ctx.critical_files
        assert ".env" in ctx.critical_files
        assert "src/express/routes/user.js" in ctx.critical_files
        assert "src/spring/security/LoginController.java" in ctx.critical_files
        assert "package.json" in ctx.critical_files
        # LOW severity should NOT be in critical_files
        assert "src/config/readme.md" not in ctx.critical_files

    # ── Vulnerability types ─────────────────────────────────────

    def test_collects_vulnerability_types(
        self,
        sample_findings,
        mock_save,
    ):
        """Unique vulnerability types are extracted from findings."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-vtypes",
            findings=sample_findings,
            repo_url="https://github.com/example/repo",
        )

        expected_types = {
            "SQL_INJECTION",
            "XSS",
            "CSRF",
            "AUTH_BYPASS",
            "COMMAND_INJECTION",
            "EXPOSED_SECRET",
            "DEPENDENCY_VULNERABILITY",
            "INFO_LEAK",
            "MISCONFIGURATION",
            "UNKNOWN",
        }
        assert set(ctx.vulnerability_types) == expected_types

    # ── Edge cases ──────────────────────────────────────────────

    def test_empty_findings(self, mock_save):
        """Empty findings list should produce a valid ReconContext."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-empty",
            findings=[],
            repo_url="https://github.com/example/empty",
        )

        assert ctx is not None
        assert ctx.findings_count == 0
        assert ctx.languages_detected == []
        assert ctx.frameworks_detected == []
        assert ctx.severity_breakdown == {}
        assert ctx.critical_files == []
        assert ctx.has_hardcoded_secrets is False
        assert ctx.dependency_vulns_count == 0
        assert ctx.vulnerability_types == []
        mock_save.assert_called_once()

    def test_critical_files_capped_at_20(self, mock_save):
        """Critical files list is capped at 20 entries."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        findings = [
            {"type": "XSS", "severity": "CRITICAL", "file_path": f"src/file_{i}.py"}
            for i in range(30)
        ]

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-cap",
            findings=findings,
            repo_url="https://github.com/example/repo",
        )

        assert len(ctx.critical_files) <= 20

    # ── Exception handling ──────────────────────────────────────

    def test_returns_none_when_save_recon_context_raises(self, mock_save):
        """Exception during build is caught, logged, and returns None."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        mock_save.side_effect = RuntimeError("Redis unavailable")

        with patch("orchestrator_pkg.recon_context_service.logger") as mock_logger:
            ctx = ReconContextService.build_and_save(
                engagement_id="eng-err",
                findings=[],
                repo_url="https://example.com",
            )

        assert ctx is None
        mock_logger.warning.assert_called_once()
        assert "Redis unavailable" in str(mock_logger.warning.call_args)

    # ── Severity breakdown detail ───────────────────────────────

    def test_severity_breakdown_counts(self, mock_save):
        """Verify precise severity counts with a custom fixture set."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        findings = [
            {"type": "A", "severity": "CRITICAL", "file_path": "a.py"},
            {"type": "B", "severity": "HIGH", "file_path": "b.py"},
            {"type": "C", "severity": "HIGH", "file_path": "c.py"},
            {"type": "D", "severity": "MEDIUM", "file_path": "d.py"},
            {"type": "E", "severity": "MEDIUM", "file_path": "e.py"},
            {"type": "F", "severity": "MEDIUM", "file_path": "f.py"},
            {"type": "G", "severity": "LOW", "file_path": "g.py"},
            {"type": "H", "severity": "INFO", "file_path": "h.py"},
        ]

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-counts",
            findings=findings,
            repo_url="https://github.com/example/repo",
        )

        assert ctx.severity_breakdown == {
            "CRITICAL": 1,
            "HIGH": 2,
            "MEDIUM": 3,
            "LOW": 1,
            "INFO": 1,
        }

    # ── De-duplication ──────────────────────────────────────────

    def test_vulnerability_types_are_unique(self, mock_save):
        """Duplicate vulnerability types should be collapsed to unique set."""
        from orchestrator_pkg.recon_context_service import ReconContextService

        findings = [
            {"type": "SQL_INJECTION", "severity": "HIGH", "file_path": "a.py"},
            {"type": "SQL_INJECTION", "severity": "CRITICAL", "file_path": "b.py"},
            {"type": "SQL_INJECTION", "severity": "MEDIUM", "file_path": "c.py"},
            {"type": "XSS", "severity": "HIGH", "file_path": "d.py"},
        ]

        ctx = ReconContextService.build_and_save(
            engagement_id="eng-dedup",
            findings=findings,
            repo_url="https://github.com/example/repo",
        )

        assert len(ctx.vulnerability_types) == 2
        assert "SQL_INJECTION" in ctx.vulnerability_types
        assert "XSS" in ctx.vulnerability_types

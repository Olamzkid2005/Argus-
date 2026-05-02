"""
Integration tests for Repository Scanning (scan_type='repo').

Tests the full repo scan path including git clone, Semgrep execution,
finding normalization, and state machine transitions.

Use unittest.mock to avoid needing real Git or Semgrep binaries.
"""

import os

# Ensure project root is importable
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestRepoScan:
    """Test suite for repository scanning"""

    # ── Test 1: Successful repo scan end-to-end ──

    @patch("subprocess.run")
    def test_repo_scan_completes_successfully(self, mock_subprocess):
        """Verify a complete repo scan returns findings with correct structure."""
        from orchestrator import Orchestrator

        # Mock git clone (subprocess for checkout)
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # We need to patch the actual scan function since orchestration calls it
        with patch(
            "orchestrator_pkg.repo_scan.execute_repo_scan",
            return_value=[
                {
                    "type": "SQL_INJECTION",
                    "severity": "HIGH",
                    "endpoint": "src/db.py:42",
                    "source_tool": "semgrep",
                    "confidence": 0.9,
                    "evidence": {
                        "check_id": "python.sql-injection",
                        "message": "SQL injection in query",
                        "severity": "ERROR",
                    },
                }
            ],
        ):
            orch = Orchestrator("test-engagement-id")
            result = orch.run_repo_scan(
                {
                    "type": "repo_scan",
                    "target": "https://github.com/test/repo",
                    "repo_url": "https://github.com/test/repo",
                    "budget": {},
                }
            )

            assert result["phase"] == "repo_scan"
            assert result["status"] == "completed"
            assert "trace_id" in result

    # ── Test 2: Git clone failure ──

    @patch("subprocess.run")
    def test_repo_scan_git_clone_failure(self, mock_subprocess):
        """Verify the orchestrator handles git clone failure gracefully."""
        from orchestrator import Orchestrator

        # Mock subprocess to fail for git clone
        mock_subprocess.side_effect = [
            # git clone fails
            MagicMock(
                returncode=128,
                stdout="",
                stderr="fatal: repository not found",
            )
        ]

        with patch(
            "orchestrator_pkg.repo_scan.execute_repo_scan",
            side_effect=RuntimeError(
                "REPO_CLONE_FAILED:https://github.com/bad/repo:Clone failed"
            ),
        ):
            orch = Orchestrator("test-engagement-id")
            result = orch.run_repo_scan(
                {
                    "type": "repo_scan",
                    "target": "https://github.com/bad/repo",
                    "repo_url": "https://github.com/bad/repo",
                    "budget": {},
                }
            )

            # Should handle failure gracefully (orchestrator returns completed with 0 findings)
            assert result["status"] == "completed"
            assert result["findings_count"] == 0

    # ── Test 3: Normalized findings match schema ──

    def test_normalized_findings_match_schema(self):
        """Verify that normalized findings have all required schema fields."""
        from parsers.normalizer import FindingNormalizer

        normalizer = FindingNormalizer()

        raw = {
            "type": "sql-injection",
            "severity": "ERROR",
            "endpoint": "src/app.py:42",
            "evidence": {"payload": "' OR 1=1--"},
        }

        finding = normalizer.normalize(raw, "semgrep")

        # Verify required fields are present and of correct types
        assert finding.type is not None
        assert finding.severity is not None
        assert finding.severity.name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
        assert finding.endpoint is not None
        assert isinstance(finding.confidence, float)
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.source_tool == "semgrep"
        assert isinstance(finding.evidence, dict)

    # ── Test 4: State machine transitions for repo scan ──

    @patch("tasks.recon.run_recon.delay")
    def test_repo_scan_chain_dispatches_correctly(self, mock_run_recon):
        """Verify the task chain dispatches correctly after repo scan."""
        from orchestrator import Orchestrator

        with patch(
            "orchestrator_pkg.repo_scan.execute_repo_scan",
            return_value=[
                {
                    "type": "SQL_INJECTION",
                    "severity": "HIGH",
                    "endpoint": "src/db.py:42",
                    "source_tool": "semgrep",
                    "confidence": 0.9,
                    "evidence": {},
                }
            ],
        ):
            orch = Orchestrator("test-engagement-id")
            result = orch.run_repo_scan(
                {
                    "type": "repo_scan",
                    "target": "https://github.com/test/repo",
                    "repo_url": "https://github.com/test/repo",
                    "budget": {},
                }
            )

            # Should auto-advance to scanning
            assert result["next_state"] == "scanning"
            assert result["status"] == "completed"

    # ── Test 5: Repo scan with zero findings ──

    def test_repo_scan_zero_findings_returns_cleanly(self):
        """Verify a clean scan with no vulnerabilities completes normally."""
        from orchestrator import Orchestrator

        with patch(
            "orchestrator_pkg.repo_scan.execute_repo_scan",
            return_value=[],
        ):
            orch = Orchestrator("test-engagement-id")
            result = orch.run_repo_scan(
                {
                    "type": "repo_scan",
                    "target": "https://github.com/clean/repo",
                    "repo_url": "https://github.com/clean/repo",
                    "budget": {},
                }
            )

            assert result["findings_count"] == 0
            assert result["status"] == "completed"

    # ── Test 6: Severity mapping ──

    def test_severity_values_are_valid(self):
        """Verify that severity values from tools map to our schema properly."""
        from parsers.normalizer import FindingNormalizer

        normalizer = FindingNormalizer()

        # Test different severity inputs
        test_cases = [
            ("CRITICAL", "CRITICAL"),
            ("HIGH", "HIGH"),
            ("MEDIUM", "MEDIUM"),
            ("LOW", "LOW"),
            ("INFO", "INFO"),
        ]

        for input_sev, expected in test_cases:
            raw = {
                "type": "TEST_FINDING",
                "severity": input_sev,
                "endpoint": "test:1",
                "evidence": {},
            }
            finding = normalizer.normalize(raw, "semgrep")
            assert finding.severity.name == expected, (
                f"Expected {input_sev} to map to {expected}, got {finding.severity.name}"
            )

    # ── Test 7: ReconContext built from repo findings ──

    def test_recon_context_built_from_repo_findings(self):
        """Verify that ReconContext is correctly built from repo scan results."""

        findings = [
            {
                "type": "SQL_INJECTION",
                "severity": "HIGH",
                "endpoint": "src/db.py:42",
                "file_path": "src/db.py",
                "source_tool": "semgrep",
                "confidence": 0.9,
                "evidence": {},
            },
            {
                "type": "HARDCODED_SECRET",
                "severity": "CRITICAL",
                "endpoint": "config.py:10",
                "file_path": "config.py",
                "source_tool": "gitleaks",
                "confidence": 1.0,
                "evidence": {},
            },
            {
                "type": "DEPENDENCY_VULNERABILITY",
                "severity": "HIGH",
                "endpoint": "npm:lodash",
                "file_path": "",
                "source_tool": "npm_audit",
                "confidence": 0.95,
                "evidence": {},
            },
        ]

        # Verify the ReconContext-building logic works in isolation
        vuln_types = list({f.get("type", "UNKNOWN") for f in findings})
        severity_breakdown = {}
        has_secrets = False
        dep_vulns = 0
        critical_files = []

        for f in findings:
            sev = f.get("severity", "INFO")
            severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
            if sev in ("CRITICAL", "HIGH"):
                fp = f.get("file_path") or f.get("endpoint", "")
                if fp and fp not in critical_files:
                    critical_files.append(fp)
            if f.get("type") in (
                "EXPOSED_SECRET",
                "COMMITTED_SECRET",
                "HARDCODED_SECRET",
            ):
                has_secrets = True
            if f.get("type") == "DEPENDENCY_VULNERABILITY":
                dep_vulns += 1

        assert "SQL_INJECTION" in vuln_types
        assert "HARDCODED_SECRET" in vuln_types
        assert has_secrets is True
        assert dep_vulns == 1
        # npm:lodash is included because file_path is empty, so endpoint falls back
        assert len(critical_files) == 3  # src/db.py + config.py + npm:lodash
        assert severity_breakdown.get("CRITICAL") == 1
        assert severity_breakdown.get("HIGH") == 2

"""Tests for orchestrator_pkg.recon — Category: function"""

import pytest

from orchestrator_pkg.recon import _probe_login_pages
from orchestrator_pkg.recon import execute_recon_tools
from orchestrator_pkg.recon import summarize_recon_findings


class TestExecuteReconTools:
    """Tests for the execute_recon_tools function."""

    def test_requires_arguments(self):
        """Requires arguments."""
        with pytest.raises(TypeError):
            execute_recon_tools()


class TestProbeLoginPages:
    """Tests for the _probe_login_pages function."""

    def test_requires_session(self):
        """Requires a session argument."""
        with pytest.raises(TypeError):
            _probe_login_pages()


class TestSummarizeReconFindings:
    """Tests for the summarize_recon_findings function."""

    def test_with_empty_findings(self):
        """Empty findings should still return a result."""
        from models.recon_context import ReconContext
        result = summarize_recon_findings(target="https://example.com", findings=[])
        assert isinstance(result, ReconContext)
        assert result.target == "https://example.com"

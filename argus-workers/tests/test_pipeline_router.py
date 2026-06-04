"""Tests for pipeline_router.py — pipeline routing functions."""

from unittest.mock import MagicMock, patch

from pipeline_router import execute_recon_pipeline, execute_scan_pipeline


class TestExecuteReconPipeline:
    def test_invalid_target_returns_empty(self):
        findings, ctx = execute_recon_pipeline(MagicMock(), "", {})
        assert findings == []
        assert ctx is None

    def test_none_target_returns_empty(self):
        findings, ctx = execute_recon_pipeline(MagicMock(), None, {})
        assert findings == []
        assert ctx is None

    def test_valid_target_delegates_to_recon(self):
        ctx = MagicMock()
        with patch("orchestrator_pkg.recon.execute_recon_tools") as mock_recon:
            mock_recon.return_value = ([{"type": "XSS"}], "recon_context")
            findings, rctx = execute_recon_pipeline(ctx, "https://example.com", {}, "normal")
            assert len(findings) == 1
            assert rctx == "recon_context"
            mock_recon.assert_called_with(ctx, "https://example.com", {}, "normal")


class TestExecuteScanPipeline:
    def test_delegates_to_scan_tools(self):
        ctx = MagicMock()
        with patch("orchestrator_pkg.scan.execute_scan_tools") as mock_scan:
            mock_scan.return_value = [{"type": "XSS"}]
            findings = execute_scan_pipeline(
                ctx, ["https://example.com"], {},
                skip_tools={"nmap"},
                tech_stack=["python"],
            )
            assert len(findings) == 1
            mock_scan.assert_called_once()

    def test_kwargs_passed_correctly(self):
        ctx = MagicMock()
        with patch("orchestrator_pkg.scan.execute_scan_tools") as mock_scan:
            mock_scan.return_value = []
            execute_scan_pipeline(
                ctx, ["https://example.com"], {}, "aggressive",
                auth_config={"user": "admin"},
                recon_context="mock_ctx",
            )
            args, kwargs = mock_scan.call_args
            # args is a tuple of positional arguments
            # aggressiveness is 4th positional arg (index 3)
            assert args[3] == "aggressive"
            # auth_config is 5th positional arg (index 4)
            assert args[4] == {"user": "admin"}
            # recon_context is passed as keyword
            assert kwargs.get("recon_context") == "mock_ctx"

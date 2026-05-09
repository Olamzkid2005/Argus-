"""Tests for parallel executor fallback behavior."""
from unittest.mock import MagicMock, patch


class TestParallelExecutor:
    """Test that parallel executor falls back to sequential when feature flag is off."""

    @patch("pipeline_executor.is_enabled")
    def test_sequential_when_flag_off(self, mock_is_enabled):
        """Test that tools run sequentially when PARALLEL_EXECUTION is disabled."""
        mock_is_enabled.return_value = False

        from pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(
            tool_runner=MagicMock(),
            parser=MagicMock(),
            normalizer=MagicMock(),
            ws_publisher=MagicMock(),
        )

        executor._exec_httpx = MagicMock(return_value="result1")
        executor._exec_katana = MagicMock(return_value="result2")

        tools = [
            ("httpx", lambda: executor._exec_httpx("target", "eng-1", "domain")),
            ("katana", lambda: executor._exec_katana("target", "eng-1", "domain", "3")),
        ]
        results = executor._execute_tools_parallel(tools)

        assert len(results) == 2
        assert results == ["result1", "result2"]
        mock_is_enabled.assert_called_once_with("PARALLEL_EXECUTION")
        executor._exec_httpx.assert_called_once()
        executor._exec_katana.assert_called_once()

    @patch("pipeline_executor.is_enabled")
    def test_parallel_when_flag_on(self, mock_is_enabled):
        """Test that tools run via ThreadPoolExecutor when PARALLEL_EXECUTION is enabled."""
        mock_is_enabled.return_value = True

        with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
            mock_instance = MagicMock()
            mock_executor.return_value = mock_instance

            from pipeline_executor import PipelineExecutor

            executor = PipelineExecutor(
                tool_runner=MagicMock(),
                parser=MagicMock(),
                normalizer=MagicMock(),
                ws_publisher=MagicMock(),
            )

            executor._exec_httpx = MagicMock(return_value="result1")
            executor._exec_katana = MagicMock(return_value="result2")

            tools = [
                ("httpx", lambda: executor._exec_httpx("target", "eng-1", "domain")),
                ("katana", lambda: executor._exec_katana("target", "eng-1", "domain", "3")),
            ]
            results = executor._execute_tools_parallel(tools)

            assert len(results) == 2
            mock_is_enabled.assert_called_once_with("PARALLEL_EXECUTION")
            assert mock_executor.called, "ThreadPoolExecutor was not used when PARALLEL_EXECUTION is enabled"

    @patch("pipeline_executor.is_enabled")
    def test_execute_recon_tools_sequential_path(self, mock_is_enabled):
        """Test that execute_recon_tools uses sequential calls when flag is off."""
        mock_is_enabled.return_value = False

        from pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(
            tool_runner=MagicMock(),
            parser=MagicMock(),
            normalizer=MagicMock(),
            ws_publisher=MagicMock(),
        )

        executor._exec_httpx = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_katana = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_amass = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_subfinder = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_ffuf = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_alterx = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_naabu = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_whatweb = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_nikto = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_gau = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_waybackurls = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )

        results = executor.execute_recon_tools(
            target="https://example.com",
            engagement_id="eng-1",
            aggressiveness="default",
        )

        assert len(results) == 11
        executor._exec_httpx.assert_called_once()
        executor._exec_katana.assert_called_once()
        executor._exec_amass.assert_called_once()
        executor._exec_subfinder.assert_called_once()

    @patch("pipeline_executor.is_enabled")
    def test_execute_scan_tools_sequential_path(self, mock_is_enabled):
        """Test that execute_scan_tools uses sequential calls when flag is off."""
        mock_is_enabled.return_value = False

        from pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(
            tool_runner=MagicMock(),
            parser=MagicMock(),
            normalizer=MagicMock(),
            ws_publisher=MagicMock(),
        )

        executor._exec_nuclei = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_dalfox = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_sqlmap = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_arjun = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_jwt_tool = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_commix = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )
        executor._exec_testssl = MagicMock(
            return_value=MagicMock(success=True, findings=[], duration_ms=100)
        )

        results = executor.execute_scan_tools(
            target="https://example.com",
            engagement_id="eng-1",
            aggressiveness="default",
        )

        assert len(results) == 7

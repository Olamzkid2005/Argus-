"""
Tests for ArjunScanner tool.
"""

from unittest.mock import MagicMock, mock_open, patch

import pytest

from tool_core.base import ToolContext
from tool_core.result import ToolStatus
from tools.arjun_scanner import ArjunScanner
from tools.tool_runner import ToolRunner


@pytest.fixture
def mock_tool_runner():
    mock = MagicMock(spec=ToolRunner)
    result = MagicMock()
    result.success = True
    result.stdout = '{"params": ["id", "page"]}'
    result.stderr = ""
    result.error_message = None
    mock.run.return_value = result
    return mock


OUTPUT_PATH = "/tmp/arjun_test.json"
FAKE_PARSED = [{"type": "PARAMETER_DISCOVERY", "param": "id"}]


def _make_context(**overrides):
    kwargs = dict(target="https://example.com/api", timeout=60, engagement_id="eng-123", aggressiveness="normal")
    kwargs.update(overrides)
    return MagicMock(spec=ToolContext, **kwargs)


class TestArjunScanner:
    """Tests for ArjunScanner.execute()."""

    @pytest.fixture(autouse=True)
    def _patch_tempfile_os(self):
        with (
            patch("tools.arjun_scanner.tempfile.mkstemp", return_value=(3, OUTPUT_PATH)) as mock_mkstemp,
            patch("tools.arjun_scanner.os.close") as mock_close,
            patch("tools.arjun_scanner.os.remove") as mock_remove,
        ):
            self._mock_mkstemp = mock_mkstemp
            self._mock_close = mock_close
            self._mock_remove = mock_remove
            yield

    def test_execute_success_parses_findings(self, mock_tool_runner):
        scanner = ArjunScanner(tool_runner=mock_tool_runner)
        with (
            patch("tools.arjun_scanner.os.path.exists", return_value=True),
            patch("tools.arjun_scanner.os.path.getsize", return_value=100),
            patch("builtins.open", mock_open(read_data='{"params": ["id"]}')),
            patch("parsers.parsers.arjun.ArjunParser.parse", return_value=FAKE_PARSED),
        ):
            result = scanner.execute(_make_context())

        assert result.status == ToolStatus.SUCCESS
        assert len(result.findings) == 1
        assert result.findings[0]["param"] == "id"
        assert result.findings[0]["source_tool"] == "arjun"
        mock_tool_runner.run.assert_called_once()

    def test_execute_tool_failure_returns_nonzero_exit(self, mock_tool_runner):
        mock_tool_runner.run.return_value.success = False
        mock_tool_runner.run.return_value.stderr = "error output"
        mock_tool_runner.run.return_value.error_message = "arjun crashed"

        scanner = ArjunScanner(tool_runner=mock_tool_runner)
        result = scanner.execute(_make_context())

        assert result.status == ToolStatus.NONZERO_EXIT
        assert result.stderr == "error output"
        assert "arjun crashed" in result.error_message
        assert result.finished_at is not None

    def test_execute_no_output_file_returns_success_empty(self, mock_tool_runner):
        scanner = ArjunScanner(tool_runner=mock_tool_runner)
        with patch("tools.arjun_scanner.os.path.exists", return_value=False):
            result = scanner.execute(_make_context())

        assert result.status == ToolStatus.SUCCESS_EMPTY
        assert len(result.findings) == 0

    def test_execute_exception_returns_exception_status(self, mock_tool_runner):
        mock_tool_runner.run.side_effect = RuntimeError("unexpected crash")

        scanner = ArjunScanner(tool_runner=mock_tool_runner)
        result = scanner.execute(_make_context())

        assert result.status == ToolStatus.EXCEPTION
        assert "unexpected crash" in result.error_message
        assert result.finished_at is not None

    def test_execute_cleans_up_temp_file_in_finally(self, mock_tool_runner):
        mock_tool_runner.run.side_effect = RuntimeError("crash")

        scanner = ArjunScanner(tool_runner=mock_tool_runner)
        with patch("tools.arjun_scanner.os.path.exists", return_value=True):
            scanner.execute(_make_context())

        self._mock_remove.assert_called_once_with(OUTPUT_PATH)

    def test_thread_count_varies_by_aggressiveness(self, mock_tool_runner):
        scanner = ArjunScanner(tool_runner=mock_tool_runner)

        for aggr, expected in [("passive", "10"), ("normal", "20"), ("aggressive", "50")]:
            mock_tool_runner.run.reset_mock()
            with patch("tools.arjun_scanner.os.path.exists", return_value=False):
                scanner.execute(_make_context(aggressiveness=aggr))
            call_args = mock_tool_runner.run.call_args
            assert call_args is not None
            args_list = call_args[0][1]
            idx = args_list.index("-t")
            assert args_list[idx + 1] == expected, f"expected -t {expected} for {aggr}, got {args_list}"

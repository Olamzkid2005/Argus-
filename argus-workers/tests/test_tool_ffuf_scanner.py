"""
Tests for FfufScanner tool.
"""

from unittest.mock import MagicMock, patch

import pytest

from tool_core.base import ToolContext
from tool_core.result import ToolStatus
from tools.ffuf_scanner import FfufScanner
from tools.tool_runner import ToolRunner


@pytest.fixture
def mock_tool_runner():
    mock = MagicMock(spec=ToolRunner)
    result = MagicMock()
    result.success = True
    result.stdout = '{"results": []}'
    result.stderr = ""
    result.error_message = None
    result.status = None
    mock.run.return_value = result
    return mock


def _make_context(**overrides):
    kwargs = dict(target="https://example.com/FUZZ", timeout=60, aggressiveness="normal")
    kwargs.update(overrides)
    return MagicMock(spec=ToolContext, **kwargs)


class TestFfufScanner:
    """Tests for FfufScanner."""

    @pytest.fixture(autouse=True)
    def _mock_parser(self):
        with patch("parsers.parsers.ffuf.FfufParser.parse", return_value=[]):
            yield

    def test_execute_success_parses_json_stdout(self, mock_tool_runner):
        mock_tool_runner.run.return_value.stdout = (
            '{"results": [{"url": "https://example.com/admin", "status": 200}]}'
        )
        parsed = [{"type": "DIRECTORY_FOUND", "url": "https://example.com/admin"}]
        with patch("parsers.parsers.ffuf.FfufParser.parse", return_value=parsed):
            scanner = FfufScanner(tool_runner=mock_tool_runner)
            result = scanner.execute(_make_context())

        assert result.status == ToolStatus.SUCCESS
        assert len(result.findings) == 1
        assert result.findings[0]["url"] == "https://example.com/admin"
        assert result.findings[0]["source_tool"] == "ffuf"
        mock_tool_runner.run.assert_called_once()

    def test_execute_nonzero_exit_returns_nonzero_exit(self, mock_tool_runner):
        mock_tool_runner.run.return_value.success = False
        mock_tool_runner.run.return_value.status = None
        mock_tool_runner.run.return_value.stderr = "error"
        mock_tool_runner.run.return_value.error_message = "ffuf failed"

        scanner = FfufScanner(tool_runner=mock_tool_runner)
        result = scanner.execute(_make_context())

        assert result.status == ToolStatus.NONZERO_EXIT
        assert result.stderr == "error"

    def test_execute_timeout_returns_timeout(self, mock_tool_runner):
        mock_tool_runner.run.return_value.success = False
        mock_tool_runner.run.return_value.status = ToolStatus.TIMEOUT
        mock_tool_runner.run.return_value.stdout = ""
        mock_tool_runner.run.return_value.error_message = "timed out"

        scanner = FfufScanner(tool_runner=mock_tool_runner)
        result = scanner.execute(_make_context())

        assert result.status == ToolStatus.TIMEOUT

    def test_execute_exception_returns_exception(self, mock_tool_runner):
        mock_tool_runner.run.side_effect = RuntimeError("unexpected error")

        scanner = FfufScanner(tool_runner=mock_tool_runner)
        result = scanner.execute(_make_context())

        assert result.status == ToolStatus.EXCEPTION
        assert "unexpected error" in result.error_message

    def test_aggressiveness_affects_wordlist_and_extra_args(self, mock_tool_runner):
        scanner = FfufScanner(tool_runner=mock_tool_runner)

        cases = [
            ("passive", "common.txt", []),
            ("normal", "common.txt", []),
            ("aggressive", "extended.txt", ["-t", "100", "-mc", "all"]),
        ]
        for aggr, expected_wordlist, expected_extra in cases:
            mock_tool_runner.run.reset_mock()
            with patch("tools.ffuf_scanner.FfufScanner._get_wordlist_path", return_value=f"/words/{expected_wordlist}"):
                scanner.execute(_make_context(aggressiveness=aggr))
            call_args = mock_tool_runner.run.call_args
            assert call_args is not None
            args_list = call_args[0][1]
            w_idx = args_list.index("-w")
            assert args_list[w_idx + 1] == f"/words/{expected_wordlist}", f"{aggr}: expected -w /words/{expected_wordlist}"
            if expected_extra:
                for extra in expected_extra:
                    assert extra in args_list, f"{aggr}: expected {extra} in args {args_list}"

    def test_get_wordlist_path_resolves_path(self):
        expected = "/custom/path/common.txt"
        with patch("tools.tool_cache.get_wordlist_path", return_value=expected, create=True):
            path = FfufScanner._get_wordlist_path("common.txt")

        assert path == expected

    def test_get_wordlist_path_fallback_to_common_locations(self):
        name = "common.txt"
        fallback_bases = ["/usr/share/wordlists", "/usr/share/ffuf", "/home/user/wordlists"]

        def _isfile_side_effect(path):
            for b in fallback_bases:
                if path == f"{b}/{name}":
                    if b == "/usr/share/ffuf":
                        return True
            return False

        with (
            patch("tools.tool_cache.get_wordlist_path", side_effect=ImportError, create=True),
            patch("os.path.isfile", side_effect=_isfile_side_effect),
            patch("os.path.expanduser", return_value="/home/user"),
        ):
            path = FfufScanner._get_wordlist_path(name)

        assert path == "/usr/share/ffuf/common.txt"

    def test_get_wordlist_path_fallback_returns_name_when_not_found(self):
        name = "nonexistent.txt"
        with (
            patch("tools.tool_cache.get_wordlist_path", side_effect=ImportError, create=True),
            patch("os.path.isfile", return_value=False),
            patch("os.path.expanduser", return_value="/home/user"),
        ):
            path = FfufScanner._get_wordlist_path(name)

        assert path == name

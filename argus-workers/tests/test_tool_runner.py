"""
Tests for Tool Runner
"""

# ruff: noqa: S108  # test sandbox uses tempfile, not hardcoded /tmp/

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cache import CacheMode
from tool_core.result import ToolStatus
from tools.tool_runner import SecurityError, ToolRunner

# Skip tests that require Unix commands (echo, sleep) on Windows
_windows_skip = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Test requires Unix commands (echo/sleep) not available on Windows",
)


class TestToolRunner:
    """Test suite for ToolRunner"""

    def setup_method(self):
        """Setup test fixtures"""
        self.sandbox_dir = tempfile.mkdtemp(prefix="test_sandbox_")
        self.runner = ToolRunner(sandbox_dir=self.sandbox_dir)

    def teardown_method(self):
        """Cleanup after tests"""
        self.runner.cleanup()

    def test_is_dangerous_detects_rm_rf(self):
        """Test that dangerous rm -rf pattern is detected"""
        assert self.runner.is_dangerous("rm", ["-rf", "/"])
        assert self.runner.is_dangerous("rm", ["-fr", "/tmp"])

    def test_is_dangerous_detects_drop_table(self):
        """Test that SQL DROP TABLE is detected"""
        assert self.runner.is_dangerous("psql", ["-c", "DROP TABLE users"])

    def test_is_dangerous_allows_safe_commands(self):
        """Test that safe commands are allowed"""
        assert not self.runner.is_dangerous("echo", ["hello"])
        assert not self.runner.is_dangerous("ls", ["-la"])

    def test_run_blocks_dangerous_commands(self):
        """Test that dangerous commands are blocked"""
        with pytest.raises(SecurityError):
            self.runner.run("rm", ["-rf", "/"])

    @_windows_skip
    def test_run_executes_safe_command(self):
        """Test that safe commands execute successfully"""
        result = self.runner.run("echo", ["test"])

        assert result.success is True
        assert "test" in result.stdout
        assert result.returncode == 0

    @_windows_skip
    def test_run_captures_stderr(self):
        """Test that stderr is captured"""
        result = self.runner.run("ls", ["/nonexistent"])

        assert result.success is False
        assert result.returncode != 0
        assert len(result.stderr) > 0

    @_windows_skip
    def test_run_enforces_timeout(self):
        """Test that timeout is enforced"""
        result = self.runner.run("sleep", ["10"], timeout=1)

        assert result.success is False
        assert result.is_timeout is True
        assert "timed out" in result.stderr.lower()

    def test_locked_env_has_minimal_variables(self):
        """Test that locked environment has minimal variables"""
        env = self.runner._locked_env()

        assert "PATH" in env
        assert "HOME" in env
        assert "TMPDIR" in env
        # Should not have dangerous variables
        assert "LD_PRELOAD" not in env

    def test_sandbox_directory_exists(self):
        """Test that sandbox directory is created"""
        assert Path(self.sandbox_dir).exists()
        assert Path(self.sandbox_dir).is_dir()


class TestToolRunnerStreamingScopeValidation:
    """
    Tests for scope validation in the streaming ToolRunner.run_streaming() path.

    These verify that scope validation fires BEFORE any subprocess is spawned,
    returning SCOPE_ERROR immediately for out-of-scope targets.
    """

    def setup_method(self):
        self.sandbox_dir = tempfile.mkdtemp(prefix="test_sandbox_stream_")
        self.runner = ToolRunner(sandbox_dir=self.sandbox_dir)
        # Dummy on_line callback — scope blocks before it's ever called
        self.noop_callback = lambda line: None

    def teardown_method(self):
        self.runner.cleanup()

    # ── Scope blocks out-of-scope targets ─────────────────────────────────

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_streaming_scope_blocks_out_of_scope_target(self, mock_load_scope):
        """run_streaming returns SCOPE_ERROR for out-of-scope targets."""
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        result = self.runner.run_streaming(
            "echo", ["https://evil.com/test"], timeout=5, on_line=self.noop_callback,
        )
        assert result.status == ToolStatus.SCOPE_ERROR
        assert "not in authorized scope" in result.stderr

    @_windows_skip
    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_streaming_scope_allows_in_scope_target(self, mock_load_scope):
        """run_streaming allows in-scope targets (scope check passes)."""
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        result = self.runner.run_streaming(
            "echo", ["https://allowed.com/path"], timeout=5, on_line=self.noop_callback,
        )
        # Should NOT be blocked by scope (may still fail at execution — that's fine)
        assert result.status != ToolStatus.SCOPE_ERROR

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_streaming_scope_blocks_ip_out_of_range(self, mock_load_scope):
        """run_streaming blocks IP addresses outside authorized CIDR."""
        mock_load_scope.return_value = {"domains": [], "ipRanges": ["10.0.0.0/24"]}
        result = self.runner.run_streaming(
            "echo", ["http://10.0.1.50/path"], timeout=5, on_line=self.noop_callback,
        )
        assert result.status == ToolStatus.SCOPE_ERROR
        assert "not in authorized scope" in result.stderr

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_streaming_scope_blocks_plain_hostname_out_of_scope(self, mock_load_scope):
        """run_streaming blocks plain hostname targets (non-URL) out of scope."""
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        result = self.runner.run_streaming(
            "echo", ["evil.com"], timeout=5, on_line=self.noop_callback,
        )
        assert result.status == ToolStatus.SCOPE_ERROR

    # ── No scope configured (no engagement) ───────────────────────────────

    @_windows_skip
    def test_streaming_no_scope_when_args_have_no_target(self):
        """run_streaming skips scope when args have no recognizable target."""
        result = self.runner.run_streaming(
            "echo", ["-v"], timeout=5, on_line=self.noop_callback,
        )
        assert result.status != ToolStatus.SCOPE_ERROR

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_streaming_no_scope_configured_blocks_all_fail_closed(
        self, mock_load_scope
    ):
        """run_streaming fails closed when authorized_scope is empty."""
        mock_load_scope.return_value = {"domains": [], "ipRanges": []}
        result = self.runner.run_streaming(
            "echo", ["https://any-target.com/test"], timeout=5, on_line=self.noop_callback,
        )
        assert result.status == ToolStatus.SCOPE_ERROR

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_streaming_target_without_scope_fails_closed(self, mock_load_scope):
        """run_streaming fails closed when scope returns None (no engagement)."""
        mock_load_scope.return_value = None
        result = self.runner.run_streaming(
            "echo", ["https://any-host.com"], timeout=5, on_line=self.noop_callback,
        )
        assert result.status == ToolStatus.SCOPE_ERROR


class TestToolRunnerScopeValidation:
    """
    Tests for scope validation in the synchronous ToolRunner.run() path.

    These verify that scope validation runs **before** the cache check,
    preventing stale-cached results from bypassing scope enforcement
    when the authorized scope changes.
    """

    def setup_method(self):
        self.sandbox_dir = tempfile.mkdtemp(prefix="test_sandbox_scope_")
        self.runner = ToolRunner(sandbox_dir=self.sandbox_dir)

    def teardown_method(self):
        self.runner.cleanup()

    # ── Scope blocks out-of-scope targets ─────────────────────────────────

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_scope_blocks_out_of_scope_target(self, mock_load_scope):
        """Scope validation returns SCOPE_ERROR for out-of-scope targets."""
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        result = self.runner.run("echo", ["https://evil.com/test"])
        assert result.status == ToolStatus.SCOPE_ERROR
        assert "not in authorized scope" in result.stderr

    @_windows_skip
    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_scope_allows_in_scope_target(self, mock_load_scope):
        """Scope validation allows in-scope targets (tool proceeds to execution)."""
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        result = self.runner.run("echo", ["https://allowed.com/path"])
        # Should NOT be blocked by scope
        assert result.status != ToolStatus.SCOPE_ERROR

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_scope_blocks_ip_out_of_range(self, mock_load_scope):
        """Scope validation blocks IP addresses outside authorized CIDR."""
        mock_load_scope.return_value = {"domains": [], "ipRanges": ["10.0.0.0/24"]}
        result = self.runner.run("echo", ["http://10.0.1.50/path"])
        assert result.status == ToolStatus.SCOPE_ERROR
        assert "not in authorized scope" in result.stderr

    # ── Cache-before-scope bypass prevention ──────────────────────────────

    @patch.object(ToolRunner, "_load_authorized_scope")
    @patch("tools.tool_runner.cache")
    def test_cache_bypass_prevented_when_out_of_scope(
        self, mock_cache, mock_load_scope
    ):
        """
        Scope validation runs BEFORE cache check.
        Even with a cached result available, out-of-scope targets return
        SCOPE_ERROR instead of the cached success.
        """
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        # Simulate a cache hit with a successful result
        mock_cache.get.return_value = {
            "stdout": "cached-result-contents",
            "stderr": "",
            "returncode": 0,
            "tool": "echo",
            "success": True,
            "duration_ms": 5,
            "timeout": False,
            "error": None,
            "trace_id": "",
        }

        result = self.runner.run("echo", ["https://evil.com/test"])

        # Scope must block before cache is checked
        assert result.status == ToolStatus.SCOPE_ERROR
        assert "cached-result-contents" not in result.stdout
        assert "not in authorized scope" in result.stderr

    @patch.object(ToolRunner, "_load_authorized_scope")
    @patch("tools.tool_runner.cache")
    def test_cache_hit_returned_when_in_scope(self, mock_cache, mock_load_scope):
        """
        When target IS in scope, cached results are returned normally
        (cache works as expected after scope passes).
        """
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        mock_cache.get.return_value = {
            "stdout": "cached-in-scope-output",
            "stderr": "",
            "returncode": 0,
            "tool": "echo",
            "success": True,
            "duration_ms": 5,
            "timeout": False,
            "error": None,
            "trace_id": "",
        }

        result = self.runner.run("echo", ["https://allowed.com/test"])

        # Cached result should be returned since scope passes
        assert result.status != ToolStatus.SCOPE_ERROR
        assert result.stdout == "cached-in-scope-output"

    @patch.object(ToolRunner, "_load_authorized_scope")
    @patch("tools.tool_runner.cache")
    def test_cache_bypass_refresh_mode_also_scope_blocked(
        self, mock_cache, mock_load_scope
    ):
        """
        In REFRESH mode (which skips cache reads), scope validation still
        runs first and blocks out-of-scope targets.
        """
        mock_load_scope.return_value = {"domains": ["allowed.com"], "ipRanges": []}
        mock_cache.get.return_value = {
            "stdout": "stale-cached",
            "stderr": "",
            "returncode": 0,
            "tool": "echo",
            "success": True,
            "duration_ms": 5,
            "timeout": False,
            "error": None,
            "trace_id": "",
        }

        result = self.runner.run(
            "echo", ["https://evil.com/test"], cache_mode=CacheMode.REFRESH
        )

        # Scope blocks even in REFRESH mode (no cached result returned)
        assert result.status == ToolStatus.SCOPE_ERROR
        assert "not in authorized scope" in result.stderr

    # ── No scope configured (no engagement) ───────────────────────────────

    @_windows_skip
    def test_no_scope_when_args_have_no_target(self):
        """
        When args don't contain a recognizable target (no URL, no hostname
        with dot), scope validation is entirely skipped.
        """
        # ToolRunner has no engagement_id → _load_authorized_scope returns None
        # But args like ["-v"] have no dot/URL → _extract_target returns None
        # → scope block is skipped entirely
        result = self.runner.run("echo", ["-v"])
        assert result.status != ToolStatus.SCOPE_ERROR

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_no_scope_configured_blocks_all_targets_fail_closed(
        self, mock_load_scope
    ):
        """
        When authorized_scope is empty (no domains, no IP ranges), the
        system fails closed: ALL targets are blocked.
        """
        # Empty scope = no authorized domains/IPs = block everything
        mock_load_scope.return_value = {"domains": [], "ipRanges": []}
        result = self.runner.run("echo", ["https://any-target.com/test"])
        assert result.status == ToolStatus.SCOPE_ERROR

    @patch.object(ToolRunner, "_load_authorized_scope")
    def test_target_without_scope_fails_closed(self, mock_load_scope):
        """
        When authorized_scope returns None (no engagement),
        scope validation fails closed: any target is blocked.
        Only args without any recognizable target skip scope entirely.
        """
        # Return None explicitly (as if no engagement_id)
        mock_load_scope.return_value = None
        result = self.runner.run("echo", ["https://any-host.com"])
        # Even with scope=None, ScopeValidator blocks all targets
        # (empty domains/IPs → fail-closed)
        assert result.status == ToolStatus.SCOPE_ERROR


class TestExtractTarget:
    """Tests for ToolRunner._extract_target() target identification."""

    def setup_method(self):
        self.runner = ToolRunner()

    def teardown_method(self):
        self.runner.cleanup()

    # ── URL targets (always caught first) ────────────────────────────────

    def test_url_target_https(self):
        """https:// URLs are always extracted as targets."""
        assert self.runner._extract_target(["https://example.com"]) == "https://example.com"

    def test_url_target_http(self):
        """http:// URLs are always extracted as targets."""
        assert self.runner._extract_target(["http://10.0.0.1/path"]) == "http://10.0.0.1/path"

    def test_url_with_path_and_query(self):
        """URL with path, query, and fragment is correctly identified."""
        url = "https://example.com/api/v1?foo=bar#section"
        assert self.runner._extract_target([url]) == url

    def test_url_preferred_over_hostname(self):
        """URL target is preferred over plain hostname in the same args."""
        result = self.runner._extract_target(["-u", "https://target.com/path"])
        assert result == "https://target.com/path"

    # ── Flag-aware extraction (new second pass) ─────────────────────────

    def test_flag_u_extracts_next_arg(self):
        """Value after -u flag is extracted as target."""
        assert self.runner._extract_target(["-u", "example.com"]) == "example.com"

    def test_flag_url_extracts_next_arg(self):
        """Value after --url flag is extracted as target."""
        assert self.runner._extract_target(["--url", "example.com"]) == "example.com"

    def test_flag_host_extracts_next_arg(self):
        """Value after -host flag is extracted as target."""
        assert self.runner._extract_target(["-host", "10.0.0.1"]) == "10.0.0.1"

    def test_flag_target_extracts_next_arg(self):
        """Value after --target flag is extracted as target."""
        assert self.runner._extract_target(["--target", "staging.app.com"]) == "staging.app.com"

    def test_flag_combined_format(self):
        """--url=value combined format extracts the value."""
        assert self.runner._extract_target(["--url=example.com"]) == "example.com"

    def test_flag_extracts_target_without_dot(self):
        """Flag-aware pass extracts targets that have no dot (e.g. localhost)."""
        assert self.runner._extract_target(["-u", "localhost"]) == "localhost"

    def test_flag_skips_when_value_is_another_flag(self):
        """If value after -u starts with -, it's another flag, not a target."""
        assert self.runner._extract_target(["-u", "-json"]) is None

    def test_flag_no_value_returns_none(self):
        """When flag is the last arg with no value, no target is extracted."""
        assert self.runner._extract_target(["-u"]) is None

    def test_flag_does_not_match_unknown_flag(self):
        """Unknown flags like -t (template path) are NOT treated as target flags."""
        assert self.runner._extract_target(["-t", "api-security.yaml"]) is None

    def test_flag_preferred_over_positional_hostname(self):
        """Flag-extracted target takes priority over positional hostname."""
        result = self.runner._extract_target(["--url", "target.com", "output.txt"])
        assert result == "target.com"

    # ── Hostname/IP targets (correctly identified) ───────────────────────

    def test_plain_hostname(self):
        """Plain hostname with dot is extracted."""
        assert self.runner._extract_target(["example.com"]) == "example.com"

    def test_ip_address(self):
        """IP address with dots is extracted."""
        assert self.runner._extract_target(["10.0.0.1"]) == "10.0.0.1"

    def test_hostname_with_port(self):
        """Hostname with port suffix is extracted."""
        assert self.runner._extract_target(["example.com:8080"]) == "example.com:8080"

    def test_subdomain_hostname(self):
        """Subdomain hostname is extracted."""
        assert self.runner._extract_target(["sub.domain.example.com"]) == "sub.domain.example.com"

    # ── Non-target args correctly filtered out ───────────────────────────

    def test_skips_nse_script(self):
        """.nse script files are NOT identified as targets."""
        assert self.runner._extract_target(["--script", "http-vuln.nse"]) is None

    def test_skips_wordlist_txt(self):
        """.txt wordlist files are NOT identified as targets."""
        assert self.runner._extract_target(["-w", "wordlist.txt"]) is None

    def test_skips_json_config(self):
        """.json config files are NOT identified as targets."""
        assert self.runner._extract_target(["-f", "output.json"]) is None

    def test_skips_yaml_template(self):
        """.yaml template files are NOT identified as targets."""
        path = "~/nuclei-templates/api-security.yaml"
        assert self.runner._extract_target(["-t", path]) is None

    def test_skips_file_path_with_dot(self):
        """File paths with dots and slashes are NOT identified as targets."""
        assert self.runner._extract_target(["./some/file.conf"]) is None
        assert self.runner._extract_target(["/path/to/template.xml"]) is None

    def test_skips_bare_dot(self):
        """Bare '.' (current directory) is NOT identified as a target."""
        assert self.runner._extract_target(["--config", "auto", "."]) is None

    def test_skips_flag_starts_with_dash(self):
        """Flag args starting with '-' are NOT identified as targets."""
        assert self.runner._extract_target(["-json", "-silent"]) is None

    # ── Mixed args (target + non-target) ─────────────────────────────────

    def test_target_among_file_args_nse(self):
        """Real hostname is found even when .nse script is present."""
        result = self.runner._extract_target([
            "--script", "http-vuln.nse", "scanme.nmap.org",
        ])
        assert result == "scanme.nmap.org"

    def test_target_among_multiple_file_args(self):
        """Real hostname is found among multiple file-type args."""
        result = self.runner._extract_target([
            "-w", "wordlist.txt", "-u", "https://target.com/FUZZ",
        ])
        assert result == "https://target.com/FUZZ"

    # ── No target found ──────────────────────────────────────────────────

    def test_no_target_empty_args(self):
        """Empty args return None."""
        assert self.runner._extract_target([]) is None

    def test_no_target_plain_text(self):
        """Args without dots or URLs return None."""
        assert self.runner._extract_target(["-v"]) is None

    def test_no_target_known_extensions_only(self):
        """Args with only non-target file extensions return None."""
        result = self.runner._extract_target(["output.yaml", "config.json"])
        assert result is None

    def test_no_target_values_after_all_flags(self):
        """All non-flag values are non-target types, returns None."""
        result = self.runner._extract_target([
            "--script", "http-vuln.nse",
            "-iL", "targets.txt",
            "-oN", "results.nmap",
        ])
        assert result is None

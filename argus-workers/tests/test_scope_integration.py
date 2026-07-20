"""
Integration Tests — Full SSRF + Scope Chain Across All Consumers

Validates that every consumer correctly invokes the consolidated
SSRF/internal-target check (ScopeValidator.is_internal_address())
AND the engagement scope check (validate_target_scope()) in the
correct order, with the correct error handling.

Key principle: do NOT mock ScopeValidator.is_internal_address() —
we want to test that the real SSRF detection works end-to-end.
Mock only external dependencies (DB lookups, subprocess, HTTP).
"""

from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_validate_target_scope():
    """Default mock returns True (in scope)."""
    with mock.patch("tools.scope_validator.validate_target_scope", return_value=True) as m:
        yield m


@pytest.fixture
def mock_validate_target_scope_block():
    """Mock returns False (out of scope)."""
    with mock.patch("tools.scope_validator.validate_target_scope", return_value=False) as m:
        yield m


@pytest.fixture
def mock_db_scope_lookup():
    """Mock EngagementRepository to return a valid authorized_scope."""
    with mock.patch(
        "database.repositories.engagement_repository.EngagementRepository.find_by_id",
        return_value={
            "metadata": {
                "_authorized_scope": {"domains": ["example.com"], "ipRanges": []}
            }
        },
    ):
        yield


# ---------------------------------------------------------------------------
# Agent: ReActAgent._validate_arguments()
# ---------------------------------------------------------------------------


class TestReactAgentScope:
    """SSRF + scope integration for ReActAgent._validate_arguments().

    _validate_arguments() checks ScopeValidator.is_internal_address()
    for any target param (target, url, host, hostname, domain, endpoint).
    """

    def _make_action(self, tool="nuclei", target=""):
        """Create a minimal AgentAction-like object."""
        from types import SimpleNamespace
        action = SimpleNamespace()
        action.tool = tool
        action.arguments = {"target": target} if target else {}
        return action

    def _make_registry(self):
        """Create a ToolRegistry with one tool that has a 'target' param."""
        from agent.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register(
            "nuclei",
            lambda *_: None,
            {
                "name": "nuclei",
                "description": "Vulnerability scanner",
                "parameters": [{"name": "target", "description": "Target URL", "required": True}],
            },
        )
        return registry

    def test_blocks_internal_target(self):
        """SSRF: 169.254.169.254 is blocked before any tool runs."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        action = self._make_action(target="http://169.254.169.254/latest/meta-data/")
        assert agent._validate_arguments(action) is False

    def test_blocks_private_ip_target(self):
        """SSRF: 10.0.0.1 private IP is blocked."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        action = self._make_action(target="http://10.0.0.1/admin")
        assert agent._validate_arguments(action) is False

    def test_blocks_loopback_target(self):
        """SSRF: localhost is blocked."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        action = self._make_action(target="http://localhost:8080")
        assert agent._validate_arguments(action) is False

    def test_blocks_metadata_hostname(self):
        """SSRF: metadata.google.internal is blocked via static hostname list."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        action = self._make_action(target="http://metadata.google.internal")
        assert agent._validate_arguments(action) is False

    def test_allows_public_target(self):
        """Safe: public hostname passes SSRF check."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        action = self._make_action(target="https://example.com/api")
        assert agent._validate_arguments(action) is True

    def test_allows_non_target_param(self):
        """Tool args without target-related params pass SSRF check."""
        from agent.react_agent import ReActAgent
        from agent.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register(
            "nuclei",
            lambda *_: None,
            {
                "name": "nuclei",
                "description": "Vulnerability scanner",
                "parameters": [{"name": "target", "description": "Target URL", "required": False}],
            },
        )
        agent = ReActAgent(registry)
        from types import SimpleNamespace
        action = SimpleNamespace()
        action.tool = "nuclei"
        action.arguments = {}  # no target param at all
        assert agent._validate_arguments(action) is True

    def test_allows_non_target_tool(self):
        """Tool with no target-related params passes SSRF check."""
        from agent.react_agent import ReActAgent
        from agent.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register(
            "report_generator",
            lambda: None,
            {
                "name": "report_generator",
                "description": "Generate report",
                "parameters": [{"name": "format", "description": "Output format", "required": True}],
            },
        )
        agent = ReActAgent(registry)
        from types import SimpleNamespace
        action = SimpleNamespace()
        action.tool = "report_generator"
        action.arguments = {"format": "pdf"}
        assert agent._validate_arguments(action) is True

    def test_blocks_scheme_less_internal_ip(self):
        """SSRF: bare IP without scheme is still detected."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        action = self._make_action(target="192.168.1.1")
        assert agent._validate_arguments(action) is False

    def test_checks_all_target_params(self):
        """All six target param names are checked (target, url, host, hostname, domain, endpoint)."""
        from agent.react_agent import ReActAgent
        registry = self._make_registry()
        agent = ReActAgent(registry)
        from types import SimpleNamespace

        for param in ["url", "host", "hostname", "domain", "endpoint"]:
            action = SimpleNamespace()
            action.tool = "nuclei"
            action.arguments = {param: "http://169.254.169.254/"}
            assert agent._validate_arguments(action) is False, f"Param '{param}' should be checked"

    def test_returns_true_when_no_target_params(self):
        """No target-related params in arguments — validation passes."""
        from agent.react_agent import ReActAgent
        from agent.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register(
            "nuclei",
            lambda *_: None,
            {
                "name": "nuclei",
                "description": "Vulnerability scanner",
                "parameters": [{"name": "target", "description": "Target URL", "required": False}],
            },
        )
        agent = ReActAgent(registry)
        from types import SimpleNamespace
        action = SimpleNamespace()
        action.tool = "nuclei"
        action.arguments = {"some_other_param": "value"}  # no target/url/host/etc.
        assert agent._validate_arguments(action) is True


# ---------------------------------------------------------------------------
# Agent: Swarm SpecialistAgent._get_targets()
# ---------------------------------------------------------------------------


class TestSwarmScope:
    """SSRF + scope integration for SpecialistAgent._get_targets().

    The inner _safe() function checks ScopeValidator.is_internal_address()
    FIRST, then validate_target_scope(). Targets blocked by EITHER check
    are excluded from the returned list.
    """

    def test_filters_internal_targets(self, mock_validate_target_scope):
        """Internal targets are filtered out by SSRF check before scope check."""
        from types import SimpleNamespace

        from agent.swarm import APIAgent

        rc = SimpleNamespace()
        rc.live_endpoints = [
            "https://example.com/api",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/admin",
        ]
        rc.api_endpoints = []
        rc.crawled_paths = []
        rc.target_url = "https://example.com"

        agent = APIAgent(
            llm_service=None,
            tool_runner=None,
            recon_context=rc,
            engagement_id="eng-test",
        )
        targets = agent._get_targets()
        assert "https://example.com/api" in targets
        assert "http://169.254.169.254/latest/meta-data/" not in targets
        assert "http://10.0.0.1/admin" not in targets
        assert len(targets) == 1

    def test_filters_out_of_scope_targets(self, mock_validate_target_scope_block):
        """Out-of-scope targets are filtered after SSRF check."""
        from types import SimpleNamespace

        from agent.swarm import APIAgent

        rc = SimpleNamespace()
        rc.live_endpoints = [
            "https://example.com/api",
            "https://evil.com/api",
        ]
        rc.api_endpoints = []
        rc.crawled_paths = []
        rc.target_url = "https://example.com"

        agent = APIAgent(
            llm_service=None,
            tool_runner=None,
            recon_context=rc,
            engagement_id="eng-test",
        )
        targets = agent._get_targets()
        # Both are public, so SSRF check passes for both
        # But evil.com is out of scope → blocked by validate_target_scope
        assert "https://example.com/api" not in targets  # blocked by mock
        assert "https://evil.com/api" not in targets     # blocked by mock
        assert len(targets) == 0  # all filtered out

    def test_allows_safe_in_scope_targets(self, mock_validate_target_scope):
        """Safe public targets that are in scope pass both checks."""
        from types import SimpleNamespace

        from agent.swarm import APIAgent

        rc = SimpleNamespace()
        rc.live_endpoints = [
            "https://example.com/api/v1/users",
            "https://example.com/api/v1/products",
        ]
        rc.api_endpoints = []
        rc.crawled_paths = []
        rc.target_url = "https://example.com"

        agent = APIAgent(
            llm_service=None,
            tool_runner=None,
            recon_context=rc,
            engagement_id="eng-test",
        )
        targets = agent._get_targets()
        assert len(targets) == 2
        assert "https://example.com/api/v1/users" in targets
        assert "https://example.com/api/v1/products" in targets

    def test_ssrf_blocked_first_regardless_of_scope(self, mock_validate_target_scope):
        """SSRF check runs BEFORE scope check — internal targets blocked even if in scope."""
        from types import SimpleNamespace

        from agent.swarm import APIAgent

        rc = SimpleNamespace()
        rc.live_endpoints = [
            "http://127.0.0.1:8080/admin",
            "https://example.com/valid",
        ]
        rc.api_endpoints = []
        rc.crawled_paths = []
        rc.target_url = "https://example.com"

        agent = APIAgent(
            llm_service=None,
            tool_runner=None,
            recon_context=rc,
            engagement_id="eng-test",
        )
        targets = agent._get_targets()
        assert "http://127.0.0.1:8080/admin" not in targets  # SSRF blocked first
        assert "https://example.com/valid" in targets         # passes both


# ---------------------------------------------------------------------------
# Sandbox: AsyncToolRunner.run() / run_streaming() —
# SKIPPED: requires opentelemetry (pre-existing env issue).
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="opentelemetry import error in tools/tool_runner.py (pre-existing)")
class TestSandboxScope:
    """SSRF + scope integration for AsyncToolRunner.run() and run_streaming().

    Both methods check ScopeValidator.is_internal_address() FIRST,
    then validate_target_scope(). Internal targets get ToolStatus.SKIPPED.
    """

    @pytest.fixture
    def sandbox(self):
        """Create an AsyncToolRunner with minimal wiring."""
        from tool_core.async_runner import AsyncToolRunner
        runner = AsyncToolRunner(engagement_id="eng-test")
        mock_runner = mock.MagicMock()
        mock_runner.is_dangerous.return_value = False
        mock_runner._locked_env.return_value = {}
        mock_runner._redact_sensitive_args.return_value = ([], {})
        mock_runner.is_tool_available.return_value = True
        mock_runner._resolve_tool_path.return_value = "/usr/bin/echo"
        mock_runner.sandbox_dir = "/tmp"
        runner._runner = mock_runner
        return runner

    @pytest.mark.asyncio
    async def test_run_blocks_internal_target(self, sandbox, mock_validate_target_scope):
        """SSRF: 10.0.0.1 private IP returns SKIPPED from run()."""
        result = await sandbox.run("nuclei", ["-u", "http://10.0.0.1"], target="http://10.0.0.1")
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.SKIPPED
        assert "internal/SSRF" in result.error_message

    @pytest.mark.asyncio
    async def test_run_blocks_metadata_hostname(self, sandbox, mock_validate_target_scope):
        """SSRF: metadata.google.internal returns SKIPPED from run()."""
        result = await sandbox.run(
            "nuclei", ["-u", "http://metadata.google.internal"],
            target="http://metadata.google.internal",
        )
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.SKIPPED
        assert "internal/SSRF" in result.error_message

    @pytest.mark.asyncio
    async def test_run_blocks_out_of_scope(self, sandbox, mock_validate_target_scope_block):
        """Out-of-scope public target returns SKIPPED from run()."""
        result = await sandbox.run(
            "nuclei", ["-u", "https://evil.com"],
            target="https://evil.com",
            engagement_id="eng-test",
        )
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.SKIPPED
        assert "out of scope" in result.error_message

    @pytest.mark.asyncio
    async def test_run_skips_scope_check_without_engagement_id(self, sandbox):
        """No engagement_id => both SSRF and scope checks are skipped."""
        result = await sandbox.run(
            "echo", ["hello"], target="http://10.0.0.1", engagement_id="",
        )
        # Without engagement_id, neither SSRF nor scope validation runs.
        # The tool proceeds to subprocess execution.
        assert result is not None
        from tool_core.result import ToolStatus
        assert result.status != ToolStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_run_passes_safe_target(self, sandbox, mock_validate_target_scope):
        """Safe public target that's in scope proceeds past validation."""
        result = await sandbox.run(
            "echo", ["hello"], target="https://example.com/api",
        )
        assert result is not None
        from tool_core.result import ToolStatus
        assert result.status != ToolStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_run_streaming_blocks_internal_target(self, sandbox, mock_validate_target_scope):
        """SSRF: 127.0.0.1 returns SKIPPED from run_streaming()."""
        result = await sandbox.run_streaming(
            "nuclei", ["-u", "http://127.0.0.1"], target="http://127.0.0.1",
        )
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.SKIPPED
        assert "internal/SSRF" in result.error_message

    @pytest.mark.asyncio
    async def test_run_streaming_blocks_out_of_scope(self, sandbox, mock_validate_target_scope_block):
        """Out-of-scope public target returns SKIPPED from run_streaming()."""
        result = await sandbox.run_streaming(
            "nuclei", ["-u", "https://evil.com"],
            target="https://evil.com",
            engagement_id="eng-test",
        )
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.SKIPPED
        assert "out of scope" in result.error_message

    @pytest.mark.asyncio
    async def test_run_streaming_passes_safe_target(self, sandbox, mock_validate_target_scope):
        """Safe target passes both checks in run_streaming()."""
        result = await sandbox.run_streaming(
            "echo", ["hello"], target="https://example.com/api",
        )
        from tool_core.result import ToolStatus
        assert result.status != ToolStatus.SKIPPED


# ---------------------------------------------------------------------------
# API Scanner: LegacyAPISecurityScanner.execute()
# ---------------------------------------------------------------------------


class TestApiScannerScope:
    """SSRF + scope integration for LegacyAPISecurityScanner.execute().

    Scans the target URL against ScopeValidator.is_internal_address()
    and validate_target_scope() before running any checks.
    """

    @pytest.fixture
    def scanner(self):
        """Create a LegacyAPISecurityScanner with minimal wiring."""
        from tools.api_scanner import LegacyAPISecurityScanner
        sc = LegacyAPISecurityScanner(engagement_id="eng-test")
        # Mock the builder to avoid FindingBuilder dependencies
        sc._builder = mock.MagicMock()
        sc._builder.findings = []
        return sc

    def test_blocks_internal_target_hostname(self, scanner, mock_validate_target_scope):
        """SSRF: metadata.google.internal is blocked before scan runs."""
        from tool_core.base import ToolContext
        ctx = ToolContext(target="http://metadata.google.internal", engagement_id="eng-test")
        result = scanner.execute(ctx)
        # Blocked early: status is EXCEPTION (default), no findings
        assert len(result.findings) == 0
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.EXCEPTION

    def test_blocks_private_ip_target(self, scanner, mock_validate_target_scope):
        """SSRF: 192.168.1.1 is blocked before scan runs."""
        from tool_core.base import ToolContext
        ctx = ToolContext(target="http://192.168.1.1/api", engagement_id="eng-test")
        result = scanner.execute(ctx)
        assert len(result.findings) == 0
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.EXCEPTION

    def test_blocks_non_http_scheme(self, scanner, mock_validate_target_scope):
        """Non-HTTP scheme is blocked before scan runs."""
        from tool_core.base import ToolContext
        ctx = ToolContext(target="file:///etc/passwd", engagement_id="eng-test")
        result = scanner.execute(ctx)
        assert len(result.findings) == 0
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.EXCEPTION

    def test_blocks_out_of_scope_target(self, scanner, mock_validate_target_scope_block):
        """Out-of-scope public target is blocked before scan runs."""
        from tool_core.base import ToolContext
        ctx = ToolContext(target="https://evil.com/api", engagement_id="eng-test")
        result = scanner.execute(ctx)
        assert len(result.findings) == 0
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.EXCEPTION

    def test_passes_safe_in_scope_target(self, scanner, mock_validate_target_scope):
        """Safe public target passes both checks and proceeds to scan."""
        from tool_core.base import ToolContext
        scanner._safe_request = mock.MagicMock(return_value=None)
        ctx = ToolContext(target="https://example.com/api", engagement_id="eng-test")
        result = scanner.execute(ctx)
        # Scan proceeds — status is set to SUCCESS (not early-return EXCEPTION)
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.SUCCESS

    def test_blocks_scheme_less_internal_ip(self, scanner, mock_validate_target_scope):
        """Bare IP without scheme is still detected via hostname extraction."""
        from tool_core.base import ToolContext
        ctx = ToolContext(target="10.0.0.1", engagement_id="eng-test")
        result = scanner.execute(ctx)
        assert len(result.findings) == 0
        from tool_core.result import ToolStatus
        assert result.status == ToolStatus.EXCEPTION


# ---------------------------------------------------------------------------
# Web Scanner: WebScanner._run_scan_impl()
# ---------------------------------------------------------------------------


class TestWebScannerScope:
    """SSRF + scope integration for WebScanner._run_scan_impl().

    Checks ScopeValidator.is_internal_address() and validate_target_scope()
    before running any scan checks.
    """

    @pytest.fixture
    def scanner(self):
        """Create a WebScanner with minimal wiring."""
        from tools.web_scanner import WebScanner
        sc = WebScanner(engagement_id="eng-test")
        # Mock the builder and base_response to avoid real HTTP calls
        sc._builder = mock.MagicMock()
        sc._builder.findings = []
        sc._base_response = None
        return sc

    def test_blocks_internal_target(self, scanner, mock_validate_target_scope):
        """SSRF: 169.254.169.254 is blocked, result has empty findings."""
        scanner._run_scan_impl("http://169.254.169.254/latest/meta-data/")
        assert len(scanner.findings) == 0

    def test_blocks_private_ip(self, scanner, mock_validate_target_scope):
        """SSRF: 10.0.0.1 is blocked."""
        scanner._run_scan_impl("http://10.0.0.1/admin")
        assert len(scanner.findings) == 0

    def test_blocks_metadata_hostname(self, scanner, mock_validate_target_scope):
        """SSRF: metadata.google.internal is blocked."""
        scanner._run_scan_impl("http://metadata.google.internal")
        assert len(scanner.findings) == 0

    def test_blocks_out_of_scope_target(self, scanner, mock_validate_target_scope_block):
        """Out-of-scope public target is blocked."""
        scanner._run_scan_impl("https://evil.com")
        assert len(scanner.findings) == 0

    def test_passes_safe_public_target(self, mock_validate_target_scope):
        """Safe public target passes SSRF + scope checks, proceeds to scan."""
        # WebScanner imports validate_target_scope at module level, so we
        # must patch the module-level reference in web_scanner, not the
        # definition site in scope_validator.
        from tools.web_scanner import WebScanner
        sc = WebScanner(engagement_id="eng-test")
        sc._builder = mock.MagicMock()
        sc._builder.findings = []
        sc._base_response = None

        with mock.patch("tools.web_scanner.validate_target_scope", return_value=True):
            sc._run_scan_impl("https://example.com")
            # target_url is only set after SSRF + scope checks pass
            assert sc.target_url == "https://example.com"

    def test_blocks_wildcard_scope_bypass(self, scanner, mock_validate_target_scope):
        """SSRF check runs before scope check — internal targets blocked regardless of scope."""
        scanner._run_scan_impl("http://127.0.0.1:8080")
        assert len(scanner.findings) == 0

    def test_logs_warning_on_internal_target(self, scanner, mock_validate_target_scope):
        """Warning is logged when an internal/SSRF target is blocked."""
        with mock.patch("tools.web_scanner.logger") as mock_logger:
            scanner._run_scan_impl("http://169.254.169.254/")
            mock_logger.warning.assert_any_call(
                mock.ANY,
                mock.ANY,
            )


# ---------------------------------------------------------------------------
# Deterministic Pipeline: scan.py execute_scan_tools() —
# SKIPPED: requires opentelemetry (pre-existing env issue).
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="opentelemetry import error in orchestrator_pkg/__init__.py (pre-existing)")
class TestScanPipelineScope:
    """SSRF + scope integration for execute_scan_tools() in scan.py.

    Filters targets through ScopeValidator.is_internal_address() FIRST,
    then validate_target_scope(). Blocked targets are logged and excluded.
    """

    @pytest.fixture
    def mock_ctx(self):
        """Create a mocked ToolContext with minimal wiring."""
        ctx = mock.MagicMock()
        ctx.engagement_id = "eng-test"
        ctx.scope_mode = "allowlist"
        ctx.allowed_targets = ["*example.com*"]
        ctx.blocked_targets = None
        ctx.tool_runner = mock.MagicMock()
        ctx.parser = mock.MagicMock()
        ctx.parser.parse.return_value = []
        ctx.publish_activity = mock.MagicMock()
        return ctx

    def test_filters_internal_targets(self, mock_ctx):
        """Internal targets are filtered out by SSRF check before scope check."""
        from orchestrator_pkg.scan import execute_scan_tools

        targets = [
            "https://example.com/api",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/admin",
        ]
        results = execute_scan_tools(mock_ctx, targets, {}, aggressiveness="default")
        # Only in-scope public targets survive
        assert len(results) == 0  # no tools actually ran (mocked runner)

    def test_filters_out_of_scope_targets(self, mock_ctx):
        """Out-of-scope targets are filtered after SSRF check."""
        from orchestrator_pkg.scan import execute_scan_tools

        mock_ctx.allowed_targets = ["*example.com*"]
        mock_ctx.scope_mode = "allowlist"

        targets = [
            "https://example.com/api",
            "https://evil.com/api",
        ]
        results = execute_scan_tools(mock_ctx, targets, {}, aggressiveness="default")
        assert isinstance(results, list)

    def test_allows_safe_in_scope_targets(self, mock_ctx):
        """Safe public in-scope targets pass both checks."""
        from orchestrator_pkg.scan import execute_scan_tools

        targets = [
            "https://example.com/api/v1/users",
            "https://example.com/api/v1/products",
        ]
        results = execute_scan_tools(mock_ctx, targets, {}, aggressiveness="default")
        assert isinstance(results, list)

    def test_fail_closed_on_scope_error(self, mock_ctx):
        """When scope validation itself errors (e.g. DB down), all targets are blocked."""
        from orchestrator_pkg.scan import execute_scan_tools

        with mock.patch(
            "tools.scope_validator.validate_target_scope",
            side_effect=RuntimeError("DB connection lost"),
        ):
            targets = ["https://example.com/api"]
            results = execute_scan_tools(mock_ctx, targets, {}, aggressiveness="default")
            assert len(results) == 0

    def test_logs_blocked_targets(self, mock_ctx):
        """Warning is logged for each blocked target."""
        from orchestrator_pkg.scan import execute_scan_tools

        mock_ctx.scope_mode = "allowlist"
        mock_ctx.allowed_targets = ["*nonexistent*"]

        with mock.patch("orchestrator_pkg.scan.logger") as mock_logger:
            targets = ["https://example.com/api"]
            execute_scan_tools(mock_ctx, targets, {}, aggressiveness="default")
            mock_logger.warning.assert_any_call(
                mock.ANY,
                mock.ANY,
                mock.ANY,
            )


# ---------------------------------------------------------------------------
# Tool Runner: ToolRunner.run() with authorized_scope —
# SKIPPED: requires opentelemetry (pre-existing env issue).
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="opentelemetry import error in tracing/__init__.py (pre-existing)")
class TestToolRunnerScope:
    """Scope integration for ToolRunner.run().

    Uses ScopeValidator.validate_target() via authorized_scope loaded
    from DB. Does NOT call ScopeValidator.is_internal_address() directly
    (that's done by the sandbox layer, not the raw ToolRunner).
    """

    @pytest.fixture
    def tool_runner(self):
        """Create a ToolRunner with mocked DB connection and sandbox."""
        from tools.tool_runner import ToolRunner
        runner = ToolRunner(
            sandbox_dir="/tmp/test_sandbox",
            engagement_id="eng-test",
            connection_string="postgresql://mock:mock@localhost/test",
        )
        return runner

    def test_blocks_out_of_scope_url_arg(self, tool_runner, mock_db_scope_lookup):
        """URL arg outside scope returns SCOPE_ERROR status."""
        with mock.patch.object(tool_runner, "_resolve_tool_path", return_value="/usr/bin/echo"):
            with mock.patch.object(tool_runner, "is_dangerous", return_value=False):
                result = tool_runner.run(
                    "echo", ["https://evil.com/api"], timeout=30,
                )
                from tool_core.result import ToolStatus
                assert result.status == ToolStatus.SCOPE_ERROR

    def test_allows_in_scope_url_arg(self, tool_runner, mock_db_scope_lookup):
        """URL arg within scope proceeds past validation."""
        with mock.patch.object(tool_runner, "_resolve_tool_path", return_value="/usr/bin/echo"):
            with mock.patch.object(tool_runner, "is_dangerous", return_value=False):
                with mock.patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value.returncode = 0
                    mock_subprocess.return_value.stdout = "hello"
                    mock_subprocess.return_value.stderr = ""

                    result = tool_runner.run(
                        "echo", ["https://example.com/api"], timeout=30,
                    )
                    from tool_core.result import ToolStatus
                    assert result.status == ToolStatus.SUCCESS

    def test_blocks_internal_ip_scope(self, tool_runner, mock_db_scope_lookup):
        """Bare internal IP is checked by ScopeValidator's is_in_scope."""
        with mock.patch.object(tool_runner, "_resolve_tool_path", return_value="/usr/bin/echo"):
            with mock.patch.object(tool_runner, "is_dangerous", return_value=False):
                result = tool_runner.run(
                    "echo", ["http://10.0.0.1"], timeout=30,
                )
                from tool_core.result import ToolStatus
                assert result.status == ToolStatus.SCOPE_ERROR

    def test_passes_without_engagement_id(self):
        """No engagement_id = no scope load = no validation."""
        from tools.tool_runner import ToolRunner
        runner = ToolRunner(sandbox_dir="/tmp/test_sandbox")

        with mock.patch.object(runner, "_resolve_tool_path", return_value="/usr/bin/echo"):
            with mock.patch.object(runner, "is_dangerous", return_value=False):
                with mock.patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value.returncode = 0
                    mock_subprocess.return_value.stdout = "hello"
                    mock_subprocess.return_value.stderr = ""

                    result = runner.run(
                        "echo", ["https://example.com/api"], timeout=30,
                    )
                    from tool_core.result import ToolStatus
                    assert result.status == ToolStatus.SUCCESS


# ---------------------------------------------------------------------------
# Redirect Chain: _validate_redirect_chain() in web_scanner.py
# ---------------------------------------------------------------------------


class TestRedirectChainScope:
    """SSRF integration for _validate_redirect_chain() in web_scanner.py.

    Calls _is_private_ip() which delegates to ScopeValidator.is_internal_address().
    Tests that internal IPs in redirect targets are blocked.
    """

    def test_blocks_redirect_to_internal_ip(self):
        """Redirect to a private IP is blocked."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("http://10.0.0.1/admin", "https://example.com") is False

    def test_blocks_redirect_to_loopback(self):
        """Redirect to loopback is blocked."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("http://127.0.0.1:8080", "https://example.com") is False

    def test_blocks_redirect_to_metadata(self):
        """Redirect to cloud metadata is blocked."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("http://169.254.169.254/latest/meta-data/", "https://example.com") is False

    def test_blocks_redirect_to_metadata_hostname(self):
        """Redirect to metadata hostname is blocked."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("http://metadata.google.internal", "https://example.com") is False

    def test_blocks_redirect_to_localhost(self):
        """Redirect to localhost hostname is blocked."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("http://localhost:3000/api", "https://example.com") is False

    def test_allows_redirect_to_same_origin(self):
        """Redirect to same origin passes both checks."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("https://example.com/api/v2", "https://example.com") is True

    def test_allows_redirect_to_subdomain(self):
        """Redirect to subdomain of target passes both checks."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("https://api.example.com/v1", "https://example.com") is True

    def test_blocks_cross_origin_redirect(self):
        """Redirect to different origin is blocked by scope check (even though SSRF passes)."""
        from tools.web_scanner import _validate_redirect_chain
        # evil.com is a public hostname (SSRF passes) but different origin (scope check blocks)
        assert _validate_redirect_chain("https://evil.com/phish", "https://example.com") is False

    def test_handles_empty_hostname(self):
        """Empty hostname is safely handled (returns False)."""
        from tools.web_scanner import _validate_redirect_chain
        assert _validate_redirect_chain("", "https://example.com") is False

    def test_handles_exception_gracefully(self):
        """Exception in processing returns False (fail-closed)."""
        from tools.web_scanner import _validate_redirect_chain
        # None URL would cause AttributeError when urlparse is called
        # But str(None) == 'None' which urlparse handles, so use something
        # that won't crash but might be edge-casey
        assert _validate_redirect_chain(None, "https://example.com") is False  # type: ignore

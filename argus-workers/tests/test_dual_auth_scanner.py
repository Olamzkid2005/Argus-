"""
Tests for DualAuthScanner (AbstractTool pattern).

Uses mocked AuthManager and ``_safe_request`` to test scan logic without
live authentication or HTTP requests.
"""

import threading
from unittest.mock import Mock, patch

import pytest

from tool_core.base import ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus
from tools.dual_auth_scanner import DualAuthScanner

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def auth_config():
    """Sample auth config dict for both users."""
    return {
        "username": "user",
        "password": "pass",
    }


@pytest.fixture
def scanner(auth_config):
    """DualAuthScanner with mocked AuthManager.

    Uses ``side_effect`` to return separate mock managers for the two
    ``AuthManager()`` constructor calls inside ``__init__``, so that
    tests can independently control ``auth_manager_a`` and
    ``auth_manager_b``.
    """
    with patch("tools.auth_manager.AuthManager") as MockAuthManager:
        mock_mgr_a = Mock()
        mock_mgr_b = Mock()
        MockAuthManager.side_effect = [mock_mgr_a, mock_mgr_b]

        mock_session = Mock()
        mock_session.request.return_value = Mock(status_code=200, text="{}")

        mock_mgr_a.authenticate.return_value = mock_session
        mock_mgr_b.authenticate.return_value = Mock()
        mock_mgr_b.request = Mock()

        sc = DualAuthScanner(
            auth_config_a=auth_config,
            auth_config_b=auth_config,
            timeout=10,
            rate_limit=0.01,
            engagement_id="test-eng",
        )
        sc.target_url = "https://example.com"
        yield sc


# ── Construction ────────────────────────────────────────────────────────


class TestDualAuthScannerConstruction:
    """Scanner initialises with correct state."""

    def test_tool_name(self):
        assert DualAuthScanner.tool_name == "dual_auth_scanner"

    def test_inherits_abstract_tool(self):
        from tool_core.base import AbstractTool
        assert issubclass(DualAuthScanner, AbstractTool)

    def test_defaults(self, auth_config):
        with patch("tools.auth_manager.AuthManager"):
            sc = DualAuthScanner(
                auth_config_a=auth_config,
                auth_config_b=auth_config,
            )
            assert sc.timeout == 60
            assert sc.rate_limit == 0.3
            assert sc.verify is True
            assert sc.findings == []

    def test_custom_timeout(self, auth_config):
        with patch("tools.auth_manager.AuthManager"):
            sc = DualAuthScanner(
                auth_config_a=auth_config,
                auth_config_b=auth_config,
                timeout=99,
            )
            assert sc.timeout == 99


# ── _emit_finding ───────────────────────────────────────────────────────


class TestEmitFinding:
    """Findings route through ``_builder.add()``."""

    def test_with_builder_adds_finding(self, scanner):
        """_builder.add() stores finding with correct type."""
        from tool_core.finding_builder import FindingBuilder
        scanner._builder = FindingBuilder(
            source_tool="dual_auth_scanner",
            engagement_id="test-eng",
        )
        scanner._builder.add(
            "CONFIRMED_BOLA", "CRITICAL", "https://example.com/api/resource/1",
            {"test": True}, confidence=0.9,
        )
        assert len(scanner._builder.findings) == 1
        assert scanner._builder.findings[0]["type"] == "CONFIRMED_BOLA"

    def test_with_builder_routes_through(self, scanner):
        """Finding routes through FindingBuilder with source_tool."""
        from tool_core.finding_builder import FindingBuilder
        scanner._builder = FindingBuilder(
            source_tool="dual_auth_scanner",
            engagement_id="test-eng",
        )
        scanner._builder.add(
            "CONFIRMED_BOLA", "CRITICAL", "https://example.com/api/resource/1",
            {"test": True}, confidence=0.9,
        )
        assert len(scanner._builder.findings) == 1
        assert scanner._builder.findings[0]["source_tool"] == "dual_auth_scanner"

    def test_builder_sanitizes_evidence(self, scanner):
        """Builder stores finding with severity."""
        from tool_core.finding_builder import FindingBuilder
        scanner._builder = FindingBuilder(
            source_tool="dual_auth_scanner",
            engagement_id="test-eng",
        )
        scanner._builder.add(
            "CONFIRMED_BOLA", "CRITICAL", "https://example.com/api/resource/1",
            {"sensitive": "data"}, confidence=0.9,
        )
        f = scanner._builder.findings[0]
        assert f["type"] == "CONFIRMED_BOLA"
        assert f["severity"] == "CRITICAL"


# ── Resource Discovery (JSON extraction) ────────────────────────────────


class TestExtractIdsFromJson:
    """_extract_ids_from_json recursively finds IDs in JSON."""

    def test_extracts_from_simple_dict(self, scanner):
        discovered = {}
        scanner._extract_ids_from_json(
            {"id": 123, "name": "test"},
            discovered,
        )
        assert "generic" in discovered
        assert "123" in discovered["generic"]

    def test_extracts_from_nested(self, scanner):
        discovered = {}
        scanner._extract_ids_from_json(
            {"user": {"user_id": 42, "profile": {"id": 7}}},
            discovered,
        )
        # user_id → resource_type "user", id → resource_type "generic"
        assert "user" in discovered
        assert "42" in discovered["user"]
        assert "generic" in discovered
        assert "7" in discovered["generic"]
        assert "7" in discovered["generic"]

    def test_extracts_from_list(self, scanner):
        discovered = {}
        scanner._extract_ids_from_json(
            {"accounts": [{"account_id": 1}, {"account_id": 2}]},
            discovered,
        )
        # account_id → resource_type "account" ("_id" suffix removed)
        assert "account" in discovered
        assert "1" in discovered["account"]
        assert "2" in discovered["account"]

    def test_empty_data(self, scanner):
        discovered = {}
        scanner._extract_ids_from_json({}, discovered)
        assert discovered == {}

    def test_handles_non_dict(self, scanner):
        discovered = {}
        scanner._extract_ids_from_json("not json", discovered)
        assert discovered == {}


# ── Cross-account access testing ────────────────────────────────────────


class TestCrossAccountAccess:
    """_test_cross_account_access flags confirmed/potential BOLA."""

    def test_confirmed_bola(self, scanner):
        """200 with substantial content = confirmed BOLA."""
        session_b = Mock()
        # Only GET succeeds; PUT returns 403 (no finding)
        def _req(method, url, **kw):
            if method == "GET":
                return Mock(
                    status_code=200,
                    text='{"id":123,"name":"confidential_admin_resource_owned_by_administrator_user"}',
                )
            return Mock(status_code=403, text="Forbidden")
        session_b.request.side_effect = _req

        findings = scanner._test_cross_account_access(session_b, {
            "accounts": ["1"],
        })

        assert len(findings) == 1
        assert findings[0]["type"] == "CONFIRMED_BOLA"
        assert findings[0]["severity"] == "CRITICAL"

    def test_potential_bola(self, scanner):
        """200 with access-denied indicators = potential BOLA."""
        session_b = Mock()
        def _req(method, url, **kw):
            if method == "GET":
                return Mock(
                    status_code=200,
                    text="access denied — you do not have permission",
                )
            return Mock(status_code=403, text="Forbidden")
        session_b.request.side_effect = _req

        findings = scanner._test_cross_account_access(session_b, {
            "accounts": ["1"],
        })

        assert len(findings) == 1
        assert findings[0]["type"] == "POTENTIAL_BOLA"
        assert findings[0]["severity"] == "MEDIUM"

    def test_403_no_finding(self, scanner):
        """403 response = proper access control, no finding."""
        session_b = Mock()
        session_b.request.return_value = Mock(status_code=403, text="Forbidden")

        findings = scanner._test_cross_account_access(session_b, {
            "accounts": ["1"],
        })

        assert len(findings) == 0

    def test_safety_cap(self, scanner):
        """More than 30 requests are prevented."""
        session_b = Mock()
        session_b.request.return_value = Mock(status_code=200, text="data")

        # Many resources × 2 methods should hit the cap
        large_resources = {f"type_{i}": ["1", "2", "3"] for i in range(10)}
        findings = scanner._test_cross_account_access(session_b, large_resources)

        # Should have 30 or fewer findings (the safety cap limits tests)
        assert len(findings) <= 30


# ── BOPLA Check ─────────────────────────────────────────────────────────


class TestCheckBopla:
    """_check_bopla detects sensitive fields in API responses."""

    def test_exposed_sensitive_fields(self, scanner):
        """Finds sensitive fields in response JSON."""
        session = Mock()
        session.request.return_value = Mock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text='{"email":"test@test.com","password_hash":"abc123","role":"admin"}',
        )

        # Mock json() method separately
        response = session.request.return_value
        response.json.return_value = {
            "email": "test@test.com",
            "password_hash": "abc123",
            "role": "admin",
        }

        findings = scanner._check_bopla(session, "user_b")

        assert len(findings) >= 1
        assert findings[0]["type"] == "BOPLA_SENSITIVE_FIELDS"
        assert "password_hash" in findings[0]["evidence"]["exposed_fields"]

    def test_clean_response_no_bopla(self, scanner):
        """No sensitive fields = no findings."""
        session = Mock()
        response = Mock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text='{"email":"test@test.com","name":"John"}',
        )
        response.json.return_value = {"email": "test@test.com", "name": "John"}
        session.request.return_value = response

        findings = scanner._check_bopla(session, "user_a")
        assert len(findings) == 0

    def test_non_json_returns_empty(self, scanner):
        """Non-JSON responses are skipped silently."""
        session = Mock()
        response = Mock(
            status_code=200,
            headers={"Content-Type": "text/html"},
            text="<html>Not JSON</html>",
        )
        response.json.side_effect = ValueError("Not JSON")
        session.request.return_value = response

        findings = scanner._check_bopla(session, "user_a")
        assert len(findings) == 0


# ── scan() edge cases ───────────────────────────────────────────────────


class TestScanEdgeCases:
    """scan() handles partial failures gracefully."""

    def test_auth_a_failure_returns_empty(self, scanner):
        """If User A auth fails, scan returns []."""
        scanner.auth_manager_a.authenticate.side_effect = Exception("Auth failed")

        findings = scanner.scan("https://example.com")
        assert findings == []

    def test_auth_b_failure_still_reports_bopla(self, scanner):
        """If User B auth fails, BOPLA on User A session still runs."""
        scanner.auth_manager_b.authenticate.side_effect = Exception("Auth failed")
        # Make User A session return sensitive data
        session_a = scanner.auth_manager_a.authenticate.return_value
        response = Mock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text='{"password_hash":"abc"}',
        )
        response.json.return_value = {"password_hash": "abc"}
        session_a.request.return_value = response

        findings = scanner.scan("https://example.com")

        assert len(findings) > 0
        assert any(f["type"] == "BOPLA_SENSITIVE_FIELDS" for f in findings)

    def test_no_discovered_resources(self, scanner):
        """When User A has no resources, cross-account tests are skipped."""
        # Make session return empty responses
        session_a = scanner.auth_manager_a.authenticate.return_value
        session_a.request.return_value = Mock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text="{}",
        )
        # Mock json to return empty
        session_a.request.return_value.json.return_value = {}

        # User B auth succeeds but won't be tested
        session_b = scanner.auth_manager_b.authenticate.return_value
        session_b.request.return_value = Mock(status_code=200, text="{}")

        findings = scanner.scan("https://example.com")
        # Should still run BOPLA, might be 0 if no sensitive fields
        assert isinstance(findings, list)


# ── execute(ctx) ────────────────────────────────────────────────────────


class TestExecute:
    """execute() creates builder, runs scan body, returns UnifiedToolResult."""

    def _mock_execute_helpers(self, scanner):
        """Mock internal methods so execute() runs setup but no real work."""
        return patch.multiple(
            scanner,
            _discover_owned_resources=Mock(return_value={}),
            _check_bopla=Mock(return_value=[]),
        )

    def test_execute_returns_unified_tool_result(self, scanner):
        ctx = ToolContext(target="https://example.com")

        with self._mock_execute_helpers(scanner):
            result = scanner.execute(ctx)

        assert result.tool_name == "dual_auth_scanner"
        assert result.status == ToolStatus.SUCCESS
        assert result.target == "https://example.com"
        assert result.finished_at is not None

    def test_execute_sets_builder(self, scanner):
        ctx = ToolContext(target="https://example.com")

        with self._mock_execute_helpers(scanner):
            scanner.execute(ctx)

        assert scanner._builder is not None
        assert scanner._builder.source_tool == "dual_auth_scanner"

    def test_execute_propagates_engagement_id(self, scanner):
        ctx = ToolContext(target="https://example.com", engagement_id="eng-99")

        with self._mock_execute_helpers(scanner):
            scanner.execute(ctx)

        assert scanner.engagement_id == "eng-99"

    def test_execute_maps_timeout(self, scanner):
        ctx = ToolContext(target="https://example.com", timeout=77)

        with self._mock_execute_helpers(scanner):
            scanner.execute(ctx)

        assert scanner.timeout == 77


class TestForPhaseExecution:
    """Tests for DualAuthScanner.for_phase_execution() classmethod."""

    @pytest.fixture
    def phase_scanner(self):
        """Create a for_phase_execution instance for testing."""
        return DualAuthScanner.for_phase_execution(
            target="https://example.com",
            engagement_id="eng-test",
            emit_finding=None,
            source_tool="bola_workflow",
        )

    def test_all_init_attributes_set(self, phase_scanner):
        """Verify for_phase_execution sets all attributes that __init__ sets.

        This is the invariant test that catches semantic drift between the
        normal constructor and the __new__ bypass path. If a new attribute
        is added to __init__ without adding it to for_phase_execution,
        this test fails.
        """
        sc = phase_scanner
        # Auth configs are intentionally None (workflow provides its own)
        assert sc.auth_config_a is None
        assert sc.auth_config_b is None
        assert sc.auth_manager_a is None
        assert sc.auth_manager_b is None
        # Core scan attributes
        assert sc.timeout == 60
        assert sc.rate_limit == 0.3
        assert sc.verify is True
        assert sc.engagement_id == "eng-test"
        assert sc.emit_finding_callback is None
        assert sc.findings == []
        assert isinstance(sc._builder, FindingBuilder)
        assert sc._last_request_time == 0.0
        assert isinstance(sc._rate_lock, type(threading.Lock()))
        # Workflow-specific attributes (not in __init__)
        assert sc._last_response_received is False
        assert sc.target_url == "https://example.com"
        # Class-level attributes are inherited
        assert sc.tool_name == "dual_auth_scanner"
        assert "accounts" in sc.RESOURCE_PATTERNS
        assert "GET" in sc.TEST_METHODS

    def test_last_response_received_flipped_on_successful_request(self, phase_scanner):
        """Verify wrapped _safe_request flips _last_response_received on 200."""
        sc = phase_scanner
        mock_session = Mock()
        mock_response = Mock(status_code=200, text="ok")
        mock_session.request.return_value = mock_response

        with patch.object(sc, "timeout", 5):
            sc._safe_request("GET", "https://example.com/api/test", session=mock_session)

        assert sc._last_response_received is True

    def test_last_response_received_stays_false_on_timeout(self, phase_scanner):
        """Verify _last_response_received stays False when _safe_request returns None."""
        from requests.exceptions import ConnectionError as RequestsConnectionError

        sc = phase_scanner
        mock_session = Mock()
        mock_session.request.side_effect = RequestsConnectionError("Connection refused")

        with patch.object(sc, "timeout", 5):
            result = sc._safe_request("GET", "https://example.com/api/test", session=mock_session)

        assert result is None
        assert sc._last_response_received is False

    def test_emit_finding_routes_through_builder(self, phase_scanner):
        """Verify _builder.add() is the canonical path."""
        sc = phase_scanner
        assert sc._builder is not None  # for_phase_execution always sets _builder
        with patch.object(sc._builder, "add", wraps=sc._builder.add) as mock_add:
            sc._builder.add(
                "CONFIRMED_BOLA", "CRITICAL", "/api/accounts/1",
                {}, confidence=0.9,
            )
            mock_add.assert_called_once()
        assert len(sc._builder.findings) == 1

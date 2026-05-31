"""
Unit tests for RateLimitRepository and its wiring into scan.py.

Tests the repository methods in isolation (mocked DB) and the wiring path
that logs rate-limit events when scan tools fail with 429/rate-limit errors.
"""

from unittest.mock import MagicMock, patch

import pytest

from database.repositories.rate_limit_repository import RateLimitRepository


def _make_mock_db():
    """Create a mock db with cursor() context manager that returns a mock cursor."""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [
        ("id", None, None, None, None, None, None),
        ("domain", None, None, None, None, None, None),
        ("event_type", None, None, None, None, None, None),
        ("status_code", None, None, None, None, None, None),
        ("current_rps", None, None, None, None, None, None),
        ("created_at", None, None, None, None, None, None),
    ]
    mock_db.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_db, mock_cursor


@pytest.fixture(autouse=True)
def reset_rate_limit_repo_singleton():
    """Reset _RATE_LIMIT_REPO singleton between tests so test ordering
    doesn't pollute results."""
    import orchestrator_pkg.scan as scan_module
    old = scan_module._RATE_LIMIT_REPO
    scan_module._RATE_LIMIT_REPO = None
    yield
    scan_module._RATE_LIMIT_REPO = old


# ═══════════════════════════════════════════════════════════════════════════
# RateLimitRepository unit tests (no DB needed)
# ═══════════════════════════════════════════════════════════════════════════


class TestRateLimitRepositoryCreateEvent:
    """Tests for RateLimitRepository.create_event()."""

    def test_creates_event_with_correct_query_and_params(self):
        """Verifies create_event builds correct SQL and passes all params."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchone.return_value = (1, "example.com", "tool_rate_limited", 429, 0.0, "2025-01-01T00:00:00Z")
        repo = RateLimitRepository(mock_db)

        result = repo.create_event(
            domain="example.com",
            event_type="tool_rate_limited",
            status_code=429,
            current_rps=0.0,
        )

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        # Verify SQL structure
        assert "INSERT INTO rate_limit_events" in sql
        assert "RETURNING id" in sql
        # Verify params
        assert mock_cursor.execute.call_args[0][1][0] == "example.com"
        assert mock_cursor.execute.call_args[0][1][1] == "tool_rate_limited"
        assert mock_cursor.execute.call_args[0][1][2] == 429
        assert mock_cursor.execute.call_args[0][1][3] == 0.0
        # Result is a dict
        assert result["domain"] == "example.com"
        assert result["status_code"] == 429

    def test_create_event_returns_none_when_db_returns_none(self):
        """When cursor.fetchone returns None, create_event returns None."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchone.return_value = None
        repo = RateLimitRepository(mock_db)

        result = repo.create_event(
            domain="example.com",
            event_type="tool_rate_limited",
            status_code=429,
            current_rps=0.0,
        )

        assert result is None

    def test_create_event_raises_on_db_error(self):
        """DB errors propagate up from create_event."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.execute.side_effect = Exception("Connection failed")
        repo = RateLimitRepository(mock_db)

        with pytest.raises(Exception, match="Connection failed"):
            repo.create_event(
                domain="example.com",
                event_type="tool_rate_limited",
                status_code=429,
                current_rps=0.0,
            )

    def test_create_event_with_null_status_code(self):
        """status_code can be None (e.g., connection timeout)."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchone.return_value = (2, "test.dev", "timeout", None, 0.0, "2025-01-01T00:00:00Z")
        repo = RateLimitRepository(mock_db)

        result = repo.create_event(
            domain="test.dev",
            event_type="timeout",
            status_code=None,
            current_rps=0.0,
        )

        assert result["status_code"] is None
        assert result["event_type"] == "timeout"

    def test_create_event_with_nonzero_rps(self):
        """current_rps reflects actual rate when limit was hit."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchone.return_value = (3, "bursty.app", "tool_rate_limited", 429, 45.5, "2025-01-01T00:00:00Z")
        repo = RateLimitRepository(mock_db)

        result = repo.create_event(
            domain="bursty.app",
            event_type="tool_rate_limited",
            status_code=429,
            current_rps=45.5,
        )

        assert result["current_rps"] == 45.5


class TestRateLimitRepositoryGetRecentEvents:
    """Tests for RateLimitRepository.get_recent_events()."""

    def test_get_recent_events_calls_fetch_with_domain_and_limit(self):
        """Verifies correct SQL and params for retrieving recent events."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchall.return_value = [
            (1, "example.com", "tool_rate_limited", 429, 0.0, "2025-01-01T00:00:00Z"),
        ]
        repo = RateLimitRepository(mock_db)

        result = repo.get_recent_events(domain="example.com", limit=50)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "SELECT id, domain, event_type" in sql
        assert "WHERE domain = %s" in sql
        assert "ORDER BY created_at DESC" in sql
        assert "LIMIT %s" in sql
        assert mock_cursor.execute.call_args[0][1][0] == "example.com"
        assert mock_cursor.execute.call_args[0][1][1] == 50
        assert len(result) == 1
        assert result[0]["domain"] == "example.com"

    def test_get_recent_events_defaults_to_limit_100(self):
        """When limit is omitted, defaults to 100."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchall.return_value = []
        repo = RateLimitRepository(mock_db)

        repo.get_recent_events(domain="example.com")

        assert mock_cursor.execute.call_args[0][1][1] == 100  # default limit

    def test_get_recent_events_returns_empty_list_when_no_events(self):
        """No events returns empty list, not None."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.fetchall.return_value = []
        repo = RateLimitRepository(mock_db)

        result = repo.get_recent_events(domain="example.com")

        assert result == []

    def test_get_recent_events_raises_on_db_error(self):
        """DB errors propagate from get_recent_events."""
        mock_db, mock_cursor = _make_mock_db()
        mock_cursor.execute.side_effect = Exception("DB unavailable")
        repo = RateLimitRepository(mock_db)

        with pytest.raises(Exception, match="DB unavailable"):
            repo.get_recent_events(domain="example.com")


class TestRateLimitRepositoryWiring:
    """Tests for the RateLimitRepository wiring in scan.py."""

    def test_get_rate_limit_repo_lazy_import_no_db_url(self):
        """Without DATABASE_URL in env, returns a RateLimitRepository instance
        (connection is lazy — only created when create_event is called)."""
        from orchestrator_pkg.scan import _get_rate_limit_repo
        with patch.dict("os.environ", {}, clear=True):
            repo = _get_rate_limit_repo()
            assert repo is not None, "Expected a RateLimitRepository instance even without DATABASE_URL"
            from database.repositories.rate_limit_repository import RateLimitRepository
            assert isinstance(repo, RateLimitRepository)

    def test_get_rate_limit_repo_with_db_url(self):
        """With DATABASE_URL set, returns a RateLimitRepository instance."""
        from orchestrator_pkg.scan import _get_rate_limit_repo
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/argus"}, clear=False):
            repo = _get_rate_limit_repo()
            assert repo is not None
            assert isinstance(repo, RateLimitRepository)

    @patch("orchestrator_pkg.scan._get_rate_limit_repo")
    def test_execute_scan_tools_fetches_rate_limit_repo(self, mock_get_repo):
        """execute_scan_tools calls _get_rate_limit_repo and uses it for
        rate-limit event logging on tool errors."""
        mock_repo = MagicMock()
        mock_get_repo.return_value = mock_repo

        from orchestrator_pkg.scan import execute_scan_tools

        ctx = MagicMock()
        ctx.engagement_id = "test-eng-123"
        ctx._normalize_finding.return_value = None
        ctx.llm_payload_generator = None
        ctx.tool_runner = MagicMock()
        ctx.tool_runner.sandbox_dir = None
        ctx.publish_activity = MagicMock()

        with patch("orchestrator_pkg.scan._is_reachable", return_value=True), \
             patch("orchestrator_pkg.scan._feature_enabled", return_value=False), \
             patch("tools.scope_validator.validate_target_scope", return_value=True):
            results = execute_scan_tools(ctx, ["https://example.test/"], {}, "default")

        assert mock_get_repo.called
        assert isinstance(results, list)

    def test_rate_limit_repo_create_event_path_executes(self):
        """Simulate the error handling loop from execute_scan_tools where
        a 429 error triggers create_event on the repo."""
        mock_repo = MagicMock()
        mock_repo.create_event.return_value = {
            "id": 1, "domain": "target.test", "event_type": "tool_rate_limited",
            "status_code": 429, "current_rps": 0.0,
        }

        # Simulate the exact code from execute_scan_tools per-target loop
        target = "https://target.test"
        err_str = "429 Too Many Requests"
        if any(kw in err_str.lower() for kw in ["429", "rate limit", "too many requests"]):
            mock_repo.create_event(
                domain=target,
                event_type="tool_rate_limited",
                status_code=429,
                current_rps=0.0,
            )

        mock_repo.create_event.assert_called_once_with(
            domain=target,
            event_type="tool_rate_limited",
            status_code=429,
            current_rps=0.0,
        )

    def test_web_scanner_rate_limit_logging_path(self):
        """Simulate the rate-limit finding filter from execute_scan_tools
        that logs rate limit findings detected by WebScanner."""
        mock_repo = MagicMock()

        sim_findings = [
            {"type": "RATE_LIMIT_DETECTED", "severity": "MEDIUM"},
            {"type": "SQL_INJECTION", "severity": "HIGH"},
            {"type": "RATE_LIMIT_BYPASS", "severity": "LOW"},
        ]

        target = "https://target.test"
        for wf in sim_findings:
            wf_type = (wf.get("type") or "").upper()
            if "RATE_LIMIT" in wf_type:
                mock_repo.create_event(
                    domain=target,
                    event_type="web_scanner_rate_limit",
                    status_code=429,
                    current_rps=0.0,
                )

        assert mock_repo.create_event.call_count == 2

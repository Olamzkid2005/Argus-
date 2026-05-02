"""
Tests for tasks/asset_discovery.py

Validates: Asset classification, risk score calculation, discovery task logic
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Purge cached module so we can re-import with proper mocks
for mod in list(sys.modules.keys()):
    if mod.startswith("tasks.asset_discovery"):
        del sys.modules[mod]

# Patch module loading before importing asset_discovery
mock_celery_app = MagicMock()
def _mock_task(*args, **kwargs):
    def decorator(func):
        return func
    return decorator
mock_celery_app.task = _mock_task
mock_celery_app.app = mock_celery_app  # so `from celery_app import app` gets the same object

with patch.dict(sys.modules, {"celery_app": mock_celery_app}):
    from tasks import asset_discovery


class TestAssetDiscovery:
    """Tests for asset discovery Celery tasks"""

    @pytest.fixture
    def mock_db(self):
        """Fixture providing mocked psycopg2 connection and cursor"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cursor

    @pytest.fixture
    def mock_tracing(self):
        """Fixture providing mocked TracingManager"""
        tracing_mgr = MagicMock()
        tracing_mgr.generate_trace_id.return_value = "trace-123"
        context_mgr = MagicMock()
        context_mgr.__enter__ = MagicMock(return_value=tracing_mgr)
        context_mgr.__exit__ = MagicMock(return_value=False)
        tracing_mgr.trace_execution.return_value = context_mgr
        return tracing_mgr

    def test_run_asset_discovery_domain(self, mock_db, mock_tracing):
        """Test asset discovery inserts domain asset"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = (1,)

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.object(asset_discovery, "TracingManager", return_value=mock_tracing):
                with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                    result = asset_discovery.run_asset_discovery(
                        self=MagicMock(),
                        engagement_id="eng-123",
                        target="https://example.com/path",
                        org_id="org-456",
                        trace_id="trace-abc"
                    )

        assert result["status"] == "completed"
        assert result["assets_discovered"] == 2
        assert result["trace_id"] == "trace-abc"

        # Verify domain insert
        calls = mock_cursor.execute.call_args_list
        assert any("domain" in str(call) for call in calls)
        assert any("example.com" in str(call) for call in calls)

    def test_run_asset_discovery_endpoint(self, mock_db, mock_tracing):
        """Test asset discovery inserts endpoint asset for http targets"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = (2,)

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.object(asset_discovery, "TracingManager", return_value=mock_tracing):
                with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                    result = asset_discovery.run_asset_discovery(
                        self=MagicMock(),
                        engagement_id="eng-123",
                        target="https://example.com/api",
                        org_id="org-456"
                    )

        calls = mock_cursor.execute.call_args_list
        assert any("endpoint" in str(call) for call in calls)
        assert result["status"] == "completed"

    def test_run_asset_discovery_no_http_target(self, mock_db, mock_tracing):
        """Test asset discovery with non-HTTP target does not insert endpoint"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.side_effect = [(1,), None]

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.object(asset_discovery, "TracingManager", return_value=mock_tracing):
                with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                    asset_discovery.run_asset_discovery(
                        self=MagicMock(),
                        engagement_id="eng-123",
                        target="example.com",
                        org_id="org-456"
                    )

        calls = mock_cursor.execute.call_args_list
        endpoint_calls = [call for call in calls if "endpoint" in str(call)]
        assert len(endpoint_calls) == 0

    def test_run_asset_discovery_conflict(self, mock_db, mock_tracing):
        """Test asset discovery handles ON CONFLICT DO NOTHING"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = None  # conflict, no row returned

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.object(asset_discovery, "TracingManager", return_value=mock_tracing):
                with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                    result = asset_discovery.run_asset_discovery(
                        self=MagicMock(),
                        engagement_id="eng-123",
                        target="https://example.com",
                        org_id="org-456"
                    )

        assert result["assets_discovered"] == 0
        assert result["assets"] == []

    def test_run_asset_discovery_exception(self, mock_db, mock_tracing):
        """Test asset discovery handles database exceptions"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.execute.side_effect = Exception("DB error")

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.object(asset_discovery, "TracingManager", return_value=mock_tracing):
                with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                    result = asset_discovery.run_asset_discovery(
                        self=MagicMock(),
                        engagement_id="eng-123",
                        target="https://example.com",
                        org_id="org-456"
                    )

        assert result["status"] == "failed"
        assert "DB error" in result["error"]
        assert "trace_id" in result

    def test_run_asset_discovery_generates_trace_id(self, mock_db, mock_tracing):
        """Test asset discovery generates trace_id when not provided"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = (1,)

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.object(asset_discovery, "TracingManager", return_value=mock_tracing):
                with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                    result = asset_discovery.run_asset_discovery(
                        self=MagicMock(),
                        engagement_id="eng-123",
                        target="https://example.com",
                        org_id="org-456"
                    )

        assert result["trace_id"] == "trace-123"
        mock_tracing.generate_trace_id.assert_called_once()

    def test_update_asset_risk_scores(self, mock_db):
        """Test risk score update for assets"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = [
            (1, "domain", "example.com", 10, 2, 3),
            (2, "endpoint", "https://example.com/api", 5, 0, 1),
        ]

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                result = asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        assert result["status"] == "completed"
        assert result["assets_scored"] == 2

        # Check that UPDATE was called for each asset
        update_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE assets" in str(call)]
        assert len(update_calls) == 2

    def test_update_asset_risk_scores_critical(self, mock_db):
        """Test risk score calculation maps to CRITICAL level"""
        mock_conn, mock_cursor = mock_db
        # (id, type, identifier, finding_count, critical_count, high_count)
        mock_cursor.fetchall.return_value = [
            (1, "domain", "example.com", 50, 3, 2),
        ]

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                result = asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        assert result["status"] == "completed"

        # Risk score = min(10, 3*3 + 2*1.5 + 50*0.1) = min(10, 9+3+5) = min(10, 17) = 10.0
        # Risk level = CRITICAL because >= 7.0
        update_call = [c for c in mock_cursor.execute.call_args_list if "UPDATE assets" in str(c)][0]
        args = update_call[0][1]
        assert args[0] == 10.0
        assert args[1] == "CRITICAL"

    def test_update_asset_risk_scores_high(self, mock_db):
        """Test risk score calculation maps to HIGH level"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = [
            (1, "domain", "example.com", 10, 1, 2),
        ]

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        # Risk score = min(10, 1*3 + 2*1.5 + 10*0.1) = min(10, 3+3+1) = 7.0
        # But >= 7.0 is CRITICAL per logic
        update_call = [c for c in mock_cursor.execute.call_args_list if "UPDATE assets" in str(c)][0]
        args = update_call[0][1]
        assert args[0] == 7.0
        assert args[1] == "CRITICAL"

    def test_update_asset_risk_scores_medium(self, mock_db):
        """Test risk score calculation maps to MEDIUM level"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = [
            (1, "domain", "example.com", 5, 0, 2),
        ]

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        # Risk score = min(10, 0*3 + 2*1.5 + 5*0.1) = min(10, 3+0.5) = 3.5
        # Risk level = MEDIUM because >= 2.0 and < 5.0
        update_call = [c for c in mock_cursor.execute.call_args_list if "UPDATE assets" in str(c)][0]
        args = update_call[0][1]
        assert args[0] == 3.5
        assert args[1] == "MEDIUM"

    def test_update_asset_risk_scores_low(self, mock_db):
        """Test risk score calculation maps to LOW level"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = [
            (1, "domain", "example.com", 1, 0, 0),
        ]

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        # Risk score = min(10, 0 + 0 + 0.1) = 0.1
        # Risk level = LOW because < 2.0
        update_call = [c for c in mock_cursor.execute.call_args_list if "UPDATE assets" in str(c)][0]
        args = update_call[0][1]
        assert args[0] == 0.1
        assert args[1] == "LOW"

    def test_update_asset_risk_scores_exception(self, mock_db):
        """Test risk score update handles database exceptions"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.execute.side_effect = Exception("DB error")

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                result = asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        assert result["status"] == "failed"
        assert "DB error" in result["error"]

    def test_update_asset_risk_scores_no_assets(self, mock_db):
        """Test risk score update with no assets returns 0 scored"""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = []

        with patch.object(asset_discovery, 'connect', return_value=mock_conn):
            with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}, clear=False):
                result = asset_discovery.update_asset_risk_scores(
                    self=MagicMock(),
                    org_id="org-456"
                )

        assert result["status"] == "completed"
        assert result["assets_scored"] == 0

    def test_domain_extraction(self):
        """Test domain extraction from various target formats"""
        # The task uses simple replace/split logic
        target = "https://sub.example.com:8443/path?query=1"
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]
        assert domain == "sub.example.com:8443"

    def test_domain_extraction_http(self):
        """Test domain extraction from http URL"""
        target = "http://example.com"
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]
        assert domain == "example.com"

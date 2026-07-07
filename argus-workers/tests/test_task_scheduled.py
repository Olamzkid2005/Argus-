"""
Tests for tasks/scheduled.py — Scheduled engagement task management.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from tasks.scheduled import (
    _build_budget_from_aggressiveness,
    _spawn_engagement,
    run_due_scans,
)


class TestBuildBudgetFromAggressiveness:
    """Test suite for _build_budget_from_aggressiveness"""

    def test_gentle_budget(self):
        budget = _build_budget_from_aggressiveness("gentle")
        assert budget == {"max_cycles": 2, "max_depth": 1}

    def test_default_budget(self):
        budget = _build_budget_from_aggressiveness("default")
        assert budget == {"max_cycles": 5, "max_depth": 3}

    def test_aggressive_budget(self):
        budget = _build_budget_from_aggressiveness("aggressive")
        assert budget == {"max_cycles": 8, "max_depth": 5}

    def test_exhaustive_budget(self):
        budget = _build_budget_from_aggressiveness("exhaustive")
        assert budget == {"max_cycles": 12, "max_depth": 7}

    def test_unknown_aggressiveness_defaults_to_default(self):
        budget = _build_budget_from_aggressiveness("unknown")
        assert budget == {"max_cycles": 5, "max_depth": 3}

    def test_none_aggressiveness_defaults_to_default(self):
        budget = _build_budget_from_aggressiveness(None)
        assert budget == {"max_cycles": 5, "max_depth": 3}


class TestRunDueScans:
    """Test suite for run_due_scans Celery task"""

    @patch("tasks.scheduled.os.getenv")
    def test_returns_skipped_when_no_database_url(self, mock_getenv):
        mock_getenv.return_value = None

        result = run_due_scans.run()

        assert result == {"status": "skipped", "reason": "no DATABASE_URL"}

    @pytest.mark.requires_db
    @patch("tasks.scheduled.run_recon")
    @patch("database.connection.connect")
    @patch("tasks.scheduled.os.getenv")
    def test_finds_due_schedules_and_spawns_engagements(
        self, mock_getenv, mock_connect, mock_run_recon
    ):
        mock_getenv.return_value = "postgres://localhost/argus"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        sched_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        mock_cursor.fetchall.return_value = [
            (
                sched_id,
                org_id,
                "https://example.com",
                {},
                "recon",
                "default",
                True,
                "test-user",
                "0 */6 * * *",
            ),
        ]
        mock_connect.return_value = mock_conn

        result = run_due_scans.run()

        assert result["status"] == "completed"
        assert result["spawned"] >= 1
        mock_connect.assert_called_once_with("postgres://localhost/argus")
        mock_run_recon.delay.assert_called_once()

    @pytest.mark.requires_db
    @patch("tasks.scheduled.run_recon")
    @patch("database.connection.connect")
    @patch("tasks.scheduled.os.getenv")
    def test_handles_schedule_failure_with_savepoint_rollback(
        self, mock_getenv, mock_connect, mock_run_recon
    ):
        mock_getenv.return_value = "postgres://localhost/argus"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        sched_id_1 = str(uuid.uuid4())
        sched_id_2 = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        mock_cursor.fetchall.return_value = [
            (
                sched_id_1,
                org_id,
                "https://bad.com",
                {},
                "recon",
                "default",
                True,
                "user-1",
                "0 */6 * * *",
            ),
            (
                sched_id_2,
                org_id,
                "https://good.com",
                {},
                "recon",
                "default",
                True,
                "user-2",
                "0 */6 * * *",
            ),
        ]
        mock_connect.return_value = mock_conn

        original_spawn = _spawn_engagement
        call_count = [0]

        def failing_spawn_once(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("DB failure on first spawn")
            return original_spawn(**kwargs)

        with patch("tasks.scheduled._spawn_engagement", side_effect=failing_spawn_once):
            result = run_due_scans.run()

        assert result["status"] == "completed"
        assert result["spawned"] >= 1

        savepoint_calls = [
            c
            for c in mock_cursor.execute.call_args_list
            if c[0][0] == "SAVEPOINT spawn_schedule"
        ]
        rollback_calls = [
            c
            for c in mock_cursor.execute.call_args_list
            if c[0][0] == "ROLLBACK TO SAVEPOINT spawn_schedule"
        ]
        assert len(savepoint_calls) >= 2
        assert len(rollback_calls) >= 1

        mock_conn.commit.assert_called_once()

    @pytest.mark.requires_db
    @patch("tasks.scheduled.run_recon")
    @patch("database.connection.connect")
    @patch("tasks.scheduled.os.getenv")
    def test_dispatches_repo_vs_recon_based_on_scan_type(
        self, mock_getenv, mock_connect, mock_run_recon
    ):
        mock_getenv.return_value = "postgres://localhost/argus"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        org_id = str(uuid.uuid4())
        mock_cursor.fetchall.return_value = [
            (
                str(uuid.uuid4()),
                org_id,
                "https://example.com",
                {},
                "recon",
                "default",
                True,
                "user-1",
                "0 */6 * * *",
            ),
            (
                str(uuid.uuid4()),
                org_id,
                "https://github.com/org/repo",
                {},
                "repo",
                "aggressive",
                True,
                "user-2",
                "0 */6 * * *",
            ),
        ]

        with patch("tasks.repo_scan.run_repo_scan") as mock_run_repo_scan:
            result = run_due_scans.run()

        assert result["status"] == "completed"
        assert result["spawned"] == 2
        mock_run_recon.delay.assert_called_once()
        mock_run_repo_scan.delay.assert_called_once()


class TestSpawnEngagement:
    """Test suite for _spawn_engagement helper"""

    @pytest.fixture
    def mock_db(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    @pytest.mark.requires_db
    def test_creates_engagement_with_all_required_fields(self, mock_db):
        mock_conn, mock_cursor = mock_db
        sched_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        result = _spawn_engagement(
            conn=mock_conn,
            sched_id=sched_id,
            org_id=org_id,
            target="https://example.com",
            scope={"domains": ["example.com"]},
            scan_type="recon",
            aggressiveness="default",
            agent_mode=True,
            created_by="test-user",
            cron_expression="0 */6 * * *",
            db_url="postgres://localhost/argus",
        )

        assert result["engagement_id"] is not None
        assert result["target"] == "https://example.com"
        assert result["scan_type"] == "recon"
        assert result["agent_mode"] is True
        assert result["aggressiveness"] == "default"

        insert_call = mock_cursor.execute.call_args_list[0]
        sql, params = insert_call[0]
        assert "INSERT INTO engagements" in sql
        assert params[0] == result["engagement_id"]
        assert params[1] == org_id
        assert params[2] == "https://example.com"
        assert params[3] == "scheduled"
        assert params[4] == '{"domains": ["example.com"]}'
        assert params[5] == "test-user"
        assert params[6] == "recon"
        assert params[7] == "default"
        assert params[8] is True

    @pytest.mark.requires_db
    def test_initializes_loop_budget_from_aggressiveness(self, mock_db):
        mock_conn, mock_cursor = mock_db
        sched_id = str(uuid.uuid4())

        result = _spawn_engagement(
            conn=mock_conn,
            sched_id=sched_id,
            org_id=str(uuid.uuid4()),
            target="https://example.com",
            scope={},
            scan_type="recon",
            aggressiveness="aggressive",
            agent_mode=False,
            created_by="user",
            cron_expression="0 */6 * * *",
            db_url="postgres://localhost/argus",
        )

        budget_call = mock_cursor.execute.call_args_list[1]
        sql, params = budget_call[0]
        assert "INSERT INTO loop_budgets" in sql
        assert params[2] == 8
        assert params[3] == 5
        assert result["engagement_id"] is not None

    @pytest.mark.requires_db
    def test_records_initial_state_and_looks_up_previous_engagement(self, mock_db):
        mock_conn, mock_cursor = mock_db
        prev_id = str(uuid.uuid4())
        sched_id = str(uuid.uuid4())

        mock_cursor.fetchone.return_value = (prev_id,)

        result = _spawn_engagement(
            conn=mock_conn,
            sched_id=sched_id,
            org_id=str(uuid.uuid4()),
            target="https://example.com",
            scope={},
            scan_type="recon",
            aggressiveness="default",
            agent_mode=True,
            created_by="user",
            cron_expression="0 */6 * * *",
            db_url="postgres://localhost/argus",
        )

        state_call = mock_cursor.execute.call_args_list[2]
        sql, params = state_call[0]
        assert "INSERT INTO engagement_states" in sql
        assert params[1] == result["engagement_id"]
        assert "Scheduled engagement auto-created" in sql

        lookup_call = mock_cursor.execute.call_args_list[3]
        sql2, params2 = lookup_call[0]
        assert "SELECT last_engagement_id" in sql2
        assert params2[0] == sched_id

        assert result["prev_engagement_id"] == prev_id

    @pytest.mark.requires_db
    def test_updates_scheduled_engagement_next_run_at(self, mock_db):
        mock_conn, mock_cursor = mock_db
        sched_id = str(uuid.uuid4())
        engagement_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        with patch(
            "tasks.scheduled.uuid.uuid4",
            side_effect=[
                uuid.UUID(engagement_id),
                uuid.UUID(str(uuid.uuid4())),
                uuid.UUID(str(uuid.uuid4())),
                uuid.UUID(str(uuid.uuid4())),
            ],
        ):
            result = _spawn_engagement(
                conn=mock_conn,
                sched_id=sched_id,
                org_id=org_id,
                target="https://example.com",
                scope={},
                scan_type="recon",
                aggressiveness="default",
                agent_mode=True,
                created_by="user",
                cron_expression="0 */6 * * *",
                db_url="postgres://localhost/argus",
            )

        update_call = mock_cursor.execute.call_args_list[4]
        sql, params = update_call[0]
        assert "UPDATE scheduled_engagements" in sql
        assert "next_run_at = %s" in sql
        assert params[1] == result["engagement_id"]
        assert params[2] == sched_id

    @pytest.mark.requires_db
    def test_scope_is_serialized_to_json_when_dict(self, mock_db):
        mock_conn, mock_cursor = mock_db
        sched_id = str(uuid.uuid4())

        result = _spawn_engagement(
            conn=mock_conn,
            sched_id=sched_id,
            org_id=str(uuid.uuid4()),
            target="https://example.com",
            scope={"domains": ["*.test.com"], "ipRanges": ["10.0.0.0/8"]},
            scan_type="recon",
            aggressiveness="gentle",
            agent_mode=False,
            created_by="admin",
            cron_expression="0 */6 * * *",
            db_url="postgres://localhost/argus",
        )

        insert_call = mock_cursor.execute.call_args_list[0]
        _, params = insert_call[0]
        assert params[4] == '{"domains": ["*.test.com"], "ipRanges": ["10.0.0.0/8"]}'
        assert result["engagement_id"] is not None

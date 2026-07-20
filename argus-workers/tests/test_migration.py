"""
Tests for runtime.migration — in-flight engagement migration with
feature-flag + timestamp gate.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from tool_core._compat import UTC


class TestMigrateEngagement:
    """Tests for migrate_engagement() gate logic."""

    NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
    ROLLOUT_TS = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    OLD_ENG = NOW - timedelta(days=60)  # before rollout
    NEW_ENG = NOW - timedelta(days=5)  # after rollout

    def setup_method(self):
        """Clear any cached rollout timestamp between tests."""
        from runtime.migration import _clear_rollout_cache

        _clear_rollout_cache()

    def _patch_has_snapshot(self, value: bool = False):
        """Patch _engagement_has_state_snapshot to avoid DB calls."""
        return patch(
            "runtime.migration._engagement_has_state_snapshot",
            return_value=value,
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_flag_off_skips_all(self):
        """When ENGAGEMENT_STATE flag is OFF, all engagements are skipped
        regardless of created_at."""
        from runtime.migration import migrate_engagement

        with patch("feature_flags.is_enabled", return_value=False):
            result = migrate_engagement("eng-new", created_at=self.NEW_ENG)
        assert result.status == "skipped"
        assert "feature flag" in result.reason

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_old_engagement_skipped_when_before_rollout(self):
        """Old engagements (pre-rollout) are skipped — kept on old path."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-old", created_at=self.OLD_ENG)
        assert result.status == "skipped"
        assert "in-flight" in result.reason
        assert "before rollout" in result.reason

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_new_engagement_migrated_after_rollout(self):
        """New engagements (post-rollout) are eligible for migration."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-new", created_at=self.NEW_ENG)
        assert result.status == "migrated"
        assert "eligible" in result.reason

    @patch.dict(os.environ, {}, clear=True)
    def test_no_rollout_timestamp_all_migrated(self):
        """When no rollout timestamp is set, all engagements are eligible."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-any", created_at=self.OLD_ENG)
        assert result.status == "migrated"

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_force_overrides_timestamp(self):
        """force=True bypasses the timestamp gate."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-old", created_at=self.OLD_ENG, force=True)
        assert result.status == "migrated"

    def test_engagement_not_found(self):
        """Unknown engagement returns error status."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(False),
            patch("runtime.migration._get_engagement_created_at", return_value=None),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-unknown")
        assert result.status == "error"
        assert "not found" in result.reason

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_already_migrated(self):
        """Engagements already with a state snapshot return 'already_live'."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(True),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-live", created_at=self.NEW_ENG)
        assert result.status == "already_live"

    @patch.dict(os.environ, {}, clear=True)
    def test_naive_datetime_converted(self):
        """Naive datetimes are treated as UTC."""
        from runtime.migration import migrate_engagement

        naive_dt = datetime(2026, 5, 20, 12, 0, 0)  # no tzinfo
        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-naive", created_at=naive_dt)
        assert result.status == "migrated"

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_rollout_at_boundary(self):
        """Engagement created exactly at rollout timestamp is migrated."""
        from runtime.migration import migrate_engagement

        # exactly at rollout
        boundary_dt = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-boundary", created_at=boundary_dt)
        assert result.status == "migrated"

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_old_path_continues_for_inflight(self):
        """Pre-rollout engagement returns 'skipped' with appropriate details."""
        from runtime.migration import migrate_engagement

        with (
            self._patch_has_snapshot(False),
            patch("feature_flags.is_enabled", return_value=True),
        ):
            result = migrate_engagement("eng-pre", created_at=self.OLD_ENG)
        assert result.status == "skipped"
        assert "created_at" in result.details
        assert "rollout_timestamp" in result.details
        # Verify the details include the timestamps
        assert result.details["rollout_timestamp"] == "2026-05-01T00:00:00+00:00"


class TestBatchMigration:
    """Tests for batch_migrate_pending_engagements()."""

    @patch.dict(os.environ, {}, clear=True)
    def test_empty_db_returns_empty(self):
        """Batch migration with no engagements returns empty list."""
        from runtime.migration import batch_migrate_pending_engagements

        with (
            patch(
                "runtime.migration._engagement_has_state_snapshot", return_value=False
            ),
            patch("database.connection.db_cursor") as mock_cursor,
        ):
            mock_cm = MagicMock()
            mock_cursor.return_value.__enter__.return_value = mock_cm
            mock_cm.fetchall.return_value = []

            results = batch_migrate_pending_engagements(limit=10)

        assert results == []

    @patch.dict(os.environ, {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-01T00:00:00+00:00"})
    def test_mixed_engagements_correct_statuses(self):
        """Batch correctly classifies old vs new engagements."""
        from runtime.migration import batch_migrate_pending_engagements

        datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
        old_ts = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
        new_ts = datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC)

        mock_rows = [
            ("eng-old-1", old_ts),
            ("eng-old-2", old_ts),
            ("eng-new-1", new_ts),
        ]

        with (
            patch(
                "runtime.migration._engagement_has_state_snapshot", return_value=False
            ),
            patch("database.connection.db_cursor") as mock_cursor,
            patch("feature_flags.is_enabled", return_value=True),
        ):
            mock_cm = MagicMock()
            mock_cursor.return_value.__enter__.return_value = mock_cm
            mock_cm.fetchall.return_value = mock_rows

            results = batch_migrate_pending_engagements(limit=10)

        assert len(results) == 3
        assert results[0].status == "skipped"  # old
        assert results[1].status == "skipped"  # old
        assert results[2].status == "migrated"  # new

    @patch.dict(os.environ, {}, clear=True)
    def test_flag_off_returns_empty_batch(self):
        """When the feature flag is off, batch returns empty (no migrate calls)."""
        from runtime.migration import batch_migrate_pending_engagements

        with (
            patch("feature_flags.is_enabled", return_value=False),
            patch("runtime.migration.ensure_tables", return_value=True),
            patch("database.connection.db_cursor") as mock_cursor,
        ):
            mock_cm = MagicMock()
            mock_cursor.return_value.__enter__.return_value = mock_cm
            mock_cm.fetchall.return_value = [("eng-1", None)]

            results = batch_migrate_pending_engagements(limit=5)
        # Individual migrate_engagement calls return "skipped" when flag is off
        assert len(results) == 1
        assert results[0].status == "skipped"

    @patch.dict(os.environ, {}, clear=True)
    def test_ensure_tables_failure_returns_empty(self):
        """If ensure_tables fails, batch returns empty."""
        from runtime.migration import batch_migrate_pending_engagements

        with patch("runtime.migration.ensure_tables", return_value=False):
            results = batch_migrate_pending_engagements(limit=5)
        assert results == []


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def setup_method(self):
        """Clear any cached rollout timestamp between tests."""
        from runtime.migration import _clear_rollout_cache

        _clear_rollout_cache()

    def test_get_rollout_timestamp_no_env(self):
        """Without environment var, returns None."""
        from runtime.migration import _get_rollout_timestamp

        with patch.dict(os.environ, {}, clear=True):
            assert _get_rollout_timestamp() is None

    def test_get_rollout_timestamp_with_env(self):
        """With environment var, returns parsed datetime."""
        from runtime.migration import _get_rollout_timestamp

        with patch.dict(
            os.environ,
            {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-06-01T00:00:00+00:00"},
        ):
            ts = _get_rollout_timestamp()
            assert ts is not None
            assert ts.year == 2026
            assert ts.month == 6

    def test_get_rollout_timestamp_invalid_env(self):
        """With invalid env var, returns None."""
        from runtime.migration import _get_rollout_timestamp

        with patch.dict(
            os.environ,
            {"ARGUS_FF_ROLLOUT_TIMESTAMP": "not-a-date"},
        ):
            assert _get_rollout_timestamp() is None

    def test_engagement_has_snapshot_no_db(self):
        """Without database, returns False."""
        from runtime.migration import _engagement_has_state_snapshot

        with patch.dict(os.environ, {}, clear=True):
            result = _engagement_has_state_snapshot("eng-nonexistent")
        assert result is False

    def test_ensure_tables_success(self):
        """ensure_tables returns True on success."""
        from runtime.migration import ensure_tables

        with patch("database.connection.db_cursor") as mock_cursor:
            mock_cm = MagicMock()
            mock_cursor.return_value.__enter__.return_value = mock_cm
            result = ensure_tables()
        assert result is True

    def test_ensure_tables_failure(self):
        """ensure_tables returns False on database error."""
        from runtime.migration import ensure_tables

        with patch(
            "database.connection.db_cursor",
            side_effect=Exception("DB connection failed"),
        ):
            result = ensure_tables()
        assert result is False


class TestGetMigrationStatus:
    """Tests for get_migration_status()."""

    def setup_method(self):
        """Clear any cached rollout timestamp between tests."""
        from runtime.migration import _clear_rollout_cache

        _clear_rollout_cache()

    def test_returns_status_dict(self):
        """get_migration_status returns expected keys."""
        from runtime.migration import get_migration_status

        with patch("database.connection.db_cursor") as mock_cursor:
            mock_cm = MagicMock()
            mock_cursor.return_value.__enter__.return_value = mock_cm
            # Simulate tables don't exist
            mock_cm.fetchone.side_effect = [(False,)]

            status = get_migration_status()

        assert "rollout_timestamp" in status
        assert "tables_created" in status
        assert status["tables_created"] is False
        assert status["total_engagements"] == 0
        assert status["migrated_engagements"] == 0

    def test_with_rollout_env_var(self):
        """Status includes rollout timestamp from env."""
        from runtime.migration import get_migration_status

        with (
            patch.dict(
                os.environ,
                {"ARGUS_FF_ROLLOUT_TIMESTAMP": "2026-05-15T00:00:00+00:00"},
            ),
            patch("database.connection.db_cursor") as mock_cursor,
        ):
            mock_cm = MagicMock()
            mock_cursor.return_value.__enter__.return_value = mock_cm
            mock_cm.fetchone.side_effect = [(False,)]

            status = get_migration_status()

        assert status["rollout_timestamp"] == "2026-05-15T00:00:00+00:00"

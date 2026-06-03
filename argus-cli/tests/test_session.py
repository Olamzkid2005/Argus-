"""
Tests for session management.

Covers:
  - Session dataclass construction and defaults
  - SessionManager CRUD (create, read, update, list, delete)
  - Message save/get edge cases
  - Lifecycle and integration scenarios
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from argus_cli.config.settings import Config
from argus_cli.session.manager import Session, SessionManager


# =========================================================================
# Helper
# =========================================================================


def _make_manager(tmpdir: Path) -> SessionManager:
    """Create a SessionManager isolated to a temp directory."""
    config = Config()
    config.sessions_db = Path(tmpdir) / "sessions.db"
    return SessionManager(config)


# =========================================================================
# Session Dataclass
# =========================================================================


class TestSessionDataclass:
    """Tests for the Session dataclass itself."""

    def test_default_values(self):
        session = Session(id="abc123")
        assert session.target == ""
        assert session.phase == "created"
        assert session.model == "gpt-4o-mini"
        assert session.provider == "openai"
        assert session.findings_count == 0
        assert session.created_at == ""
        assert session.updated_at == ""
        assert session.metadata == {}

    def test_custom_metadata(self):
        meta = {"source": "cli", "tags": ["urgent"]}
        session = Session(id="abc123", metadata=meta)
        assert session.metadata["source"] == "cli"
        assert session.metadata["tags"] == ["urgent"]

    def test_full_construction(self):
        session = Session(
            id="xyz789",
            target="example.com",
            phase="scanning",
            model="claude-opus-4",
            provider="anthropic",
            findings_count=3,
            created_at="2026-01-01 00:00:00",
            updated_at="2026-01-01 01:00:00",
            metadata={"foo": "bar"},
        )
        assert session.id == "xyz789"
        assert session.target == "example.com"
        assert session.phase == "scanning"
        assert session.model == "claude-opus-4"
        assert session.provider == "anthropic"
        assert session.findings_count == 3

    def test_session_id_8_chars(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="test.com")
            manager.close()
            assert len(session.id) == 8


# =========================================================================
# CRUD Edge Cases
# =========================================================================


class TestSessionCreateEdgeCases:
    """Additional create_session edge cases."""

    def test_create_no_target(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session()
            manager.close()
            assert session.target == ""

    def test_create_with_custom_model(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="x.com", model="claude-sonnet-4")
            manager.close()
            assert session.model == "claude-sonnet-4"

    def test_create_default_model_from_config(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"
            config.model = "gemini-2.0-flash"
            manager = SessionManager(config)
            session = manager.create_session(target="x.com")
            manager.close()
            assert session.model == "gemini-2.0-flash"

    def test_create_multiple_sessions_unique_ids(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            s1 = manager.create_session(target="a.com")
            s2 = manager.create_session(target="b.com")
            s3 = manager.create_session(target="c.com")
            manager.close()
            ids = {s1.id, s2.id, s3.id}
            assert len(ids) == 3


class TestSessionGetEdgeCases:
    """Additional get_session edge cases."""

    def test_get_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            result = manager.get_session("nonexistent-id")
            manager.close()
            assert result is None

    def test_get_after_clear_returns_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            session_id = session.id
            manager.clear_all()
            result = manager.get_session(session_id)
            manager.close()
            assert result is None

    def test_get_session_preserves_metadata(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            meta = {"env": "staging", "priority": 1}
            session = manager.create_session(target="example.com")
            manager.update_session(session.id, metadata=meta)
            fetched = manager.get_session(session.id)
            manager.close()
            assert fetched is not None
            assert fetched.metadata == meta


class TestSessionListEdgeCases:
    """Additional list_sessions edge cases."""

    def test_list_empty_when_no_sessions(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            sessions = manager.list_sessions()
            manager.close()
            assert sessions == []

    def test_list_respects_limit(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            for i in range(5):
                manager.create_session(target=f"site{i}.com")
            sessions = manager.list_sessions(limit=2)
            manager.close()
            assert len(sessions) == 2

    def test_list_returns_most_recent_first(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            s1 = manager.create_session(target="alpha.com")
            time.sleep(1)  # ensure different second for ORDER BY
            s2 = manager.create_session(target="beta.com")
            sessions = manager.list_sessions(limit=10)
            manager.close()
            assert sessions[0]["target"] == "beta.com"
            assert sessions[1]["target"] == "alpha.com"

    def test_list_returns_recently_updated_first(self):
        """Updates should move a session to the top of the list."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            s1 = manager.create_session(target="alpha.com")
            s2 = manager.create_session(target="beta.com")
            time.sleep(1)  # ensure update gets a different timestamp
            # Update the older session — it should now appear first
            manager.update_session(s1.id, phase="scanning")
            sessions = manager.list_sessions(limit=10)
            manager.close()
            assert sessions[0]["target"] == "alpha.com"
            assert sessions[1]["target"] == "beta.com"

    def test_list_keys_match_expected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            manager.create_session(target="example.com")
            sessions = manager.list_sessions()
            manager.close()
            assert len(sessions) == 1
            row = sessions[0]
            assert "id" in row
            assert "target" in row
            assert "phase" in row
            assert "model" in row
            assert "findings" in row
            assert "created_at" in row


class TestSessionUpdateEdgeCases:
    """Additional update_session edge cases."""

    def test_update_disallowed_field_ignored(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.update_session(session.id, color="blue", size=100)
            fetched = manager.get_session(session.id)
            manager.close()
            # Disallowed fields should be silently ignored; no crash
            assert fetched is not None
            assert fetched.target == "example.com"  # unchanged

    def test_update_empty_kwargs_is_noop(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.update_session(session.id)  # no kwargs
            fetched = manager.get_session(session.id)
            manager.close()
            assert fetched is not None
            assert fetched.phase == "created"

    def test_update_metadata_as_dict(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            new_meta = {"key": "value"}
            manager.update_session(session.id, metadata=new_meta)
            fetched = manager.get_session(session.id)
            manager.close()
            assert fetched is not None
            assert fetched.metadata == new_meta

    def test_update_nonexistent_session_does_not_crash(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            # Updating a session that doesn't exist should not raise
            manager.update_session("no-such-id", phase="complete")
            manager.close()

    def test_update_updates_timestamp(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            original_updated = session.updated_at
            time.sleep(1)  # ensure different second for timestamp comparison
            manager.update_session(session.id, phase="scanning")
            fetched = manager.get_session(session.id)
            manager.close()
            assert fetched is not None
            assert fetched.updated_at > original_updated


# =========================================================================
# Message Edge Cases
# =========================================================================


class TestMessageEdgeCases:
    """Tests for save_message and get_messages edge cases."""

    def test_save_message_system_role(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.save_message(session.id, "system", "system prompt here")
            messages = manager.get_messages(session.id)
            manager.close()
            assert len(messages) == 1
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "system prompt here"

    def test_save_message_tool_role(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.save_message(session.id, "tool", '{"result": "ok"}')
            messages = manager.get_messages(session.id)
            manager.close()
            assert len(messages) == 1
            assert messages[0]["role"] == "tool"

    def test_save_message_empty_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.save_message(session.id, "user", "")
            messages = manager.get_messages(session.id)
            manager.close()
            assert len(messages) == 1
            assert messages[0]["content"] == ""

    def test_save_message_unicode_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            content = "héllo wörld 🚀 äöß 你好"
            manager.save_message(session.id, "user", content)
            messages = manager.get_messages(session.id)
            manager.close()
            assert messages[0]["content"] == content

    def test_save_message_long_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            long_content = "A" * 10_000
            manager.save_message(session.id, "user", long_content)
            messages = manager.get_messages(session.id)
            manager.close()
            assert len(messages[0]["content"]) == 10_000

    def test_get_messages_empty(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            messages = manager.get_messages(session.id)
            manager.close()
            assert messages == []

    def test_get_messages_respects_limit(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            for i in range(10):
                manager.save_message(session.id, "user", f"msg {i}")
            messages = manager.get_messages(session.id, limit=3)
            manager.close()
            assert len(messages) == 3

    def test_get_messages_chronological_order(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.save_message(session.id, "user", "first")
            manager.save_message(session.id, "assistant", "second")
            manager.save_message(session.id, "user", "third")
            messages = manager.get_messages(session.id)
            manager.close()
            assert len(messages) == 3
            assert messages[0]["content"] == "first"
            assert messages[1]["content"] == "second"
            assert messages[2]["content"] == "third"


# =========================================================================
# Clear & Close
# =========================================================================


class TestSessionClearEdgeCases:
    """Tests for clear_all and close."""

    def test_clear_all_removes_messages_and_sessions(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")
            manager.save_message(session.id, "user", "hello")
            manager.save_message(session.id, "assistant", "world")
            manager.clear_all()
            assert manager.list_sessions() == []
            assert manager.get_messages(session.id) == []
            manager.close()

    def test_clear_all_empty_database(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            # No sessions or messages exist yet
            manager.clear_all()  # should not raise
            assert manager.list_sessions() == []
            manager.close()

    def test_close_does_not_crash(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            manager.create_session(target="example.com")
            manager.close()  # should not raise

    def test_close_then_reopen(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "sessions.db"
            config = Config()
            config.sessions_db = db_path

            manager = SessionManager(config)
            session = manager.create_session(target="example.com")
            manager.close()

            # Re-open with same db path
            manager2 = SessionManager(config)
            fetched = manager2.get_session(session.id)
            manager2.close()
            assert fetched is not None
            assert fetched.target == "example.com"


# =========================================================================
# Database Initialization
# =========================================================================


class TestDatabaseInit:
    """Tests for database file and directory creation."""

    def test_creates_db_dir_if_not_exists(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            nested = Path(tmpdir) / "nested" / "dir"
            db_path = nested / "sessions.db"
            assert not nested.exists()
            config = Config()
            config.sessions_db = db_path
            manager = SessionManager(config)
            manager.close()
            assert db_path.exists()

    def test_db_path_from_config_is_used(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            custom_db = Path(tmpdir) / "custom.db"
            config = Config()
            config.sessions_db = custom_db

            manager = SessionManager(config)
            assert manager.db_path == custom_db
            manager.close()
            assert custom_db.exists()


# =========================================================================
# Lifecycle & Integration
# =========================================================================


class TestSessionLifecycle:
    """End-to-end session lifecycle scenarios."""

    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))

            # Create
            session = manager.create_session(target="example.com")
            assert session.id
            assert session.phase == "created"

            # Add messages
            manager.save_message(session.id, "user", "run scan")
            manager.save_message(session.id, "assistant", "starting")
            assert len(manager.get_messages(session.id)) == 2

            # Update phase
            manager.update_session(session.id, phase="scanning", findings_count=1)
            updated = manager.get_session(session.id)
            assert updated.phase == "scanning"
            assert updated.findings_count == 1

            # List
            listings = manager.list_sessions()
            assert len(listings) == 1

            # Clear
            manager.clear_all()
            assert manager.get_session(session.id) is None
            assert manager.list_sessions() == []

            manager.close()

    def test_multiple_sessions_isolated_messages(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))

            s1 = manager.create_session(target="site1.com")
            s2 = manager.create_session(target="site2.com")

            manager.save_message(s1.id, "user", "scan site1")
            manager.save_message(s2.id, "user", "scan site2")

            msgs1 = manager.get_messages(s1.id)
            msgs2 = manager.get_messages(s2.id)

            assert len(msgs1) == 1
            assert len(msgs2) == 1
            assert msgs1[0]["content"] == "scan site1"
            assert msgs2[0]["content"] == "scan site2"
            manager.close()

    def test_update_only_affected_fields(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))

            session = manager.create_session(target="example.com")
            original_model = session.model
            original_provider = session.provider

            manager.update_session(session.id, phase="scanning")
            updated = manager.get_session(session.id)

            assert updated.phase == "scanning"
            assert updated.model == original_model  # unchanged
            assert updated.provider == original_provider  # unchanged
            manager.close()

    def test_messages_after_clear_new_session_works(self):
        """After clearing all, a new session should work normally."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))

            manager.create_session(target="old.com")
            manager.clear_all()

            session = manager.create_session(target="new.com")
            manager.save_message(session.id, "user", "fresh start")

            assert len(manager.list_sessions()) == 1
            assert len(manager.get_messages(session.id)) == 1
            manager.close()

    def test_multiple_updates_accumulate(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            manager = _make_manager(Path(tmpdir))
            session = manager.create_session(target="example.com")

            manager.update_session(session.id, phase="recon")
            manager.update_session(session.id, phase="scanning")
            manager.update_session(session.id, phase="analyzing", findings_count=3)

            updated = manager.get_session(session.id)
            assert updated.phase == "analyzing"
            assert updated.findings_count == 3
            manager.close()

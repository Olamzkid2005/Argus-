"""
Tests for session management.
"""

import tempfile
from pathlib import Path

import pytest

from argus_cli.config.settings import Config
from argus_cli.session.manager import SessionManager


class TestSessionManager:
    """Test cases for SessionManager."""

    def test_create_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"

            manager = SessionManager(config)
            session = manager.create_session(target="example.com")

            assert session.id
            assert session.target == "example.com"
            assert session.phase == "created"

    def test_get_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"

            manager = SessionManager(config)
            created = manager.create_session(target="test.com")
            fetched = manager.get_session(created.id)

            assert fetched is not None
            assert fetched.id == created.id
            assert fetched.target == "test.com"

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"

            manager = SessionManager(config)
            manager.create_session(target="a.com")
            manager.create_session(target="b.com")

            sessions = manager.list_sessions()
            assert len(sessions) == 2

    def test_update_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"

            manager = SessionManager(config)
            session = manager.create_session(target="example.com")

            manager.update_session(session.id, phase="scanning", findings_count=5)
            updated = manager.get_session(session.id)

            assert updated.phase == "scanning"
            assert updated.findings_count == 5

    def test_save_and_get_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"

            manager = SessionManager(config)
            session = manager.create_session(target="example.com")

            manager.save_message(session.id, "user", "scan target")
            manager.save_message(session.id, "assistant", "starting scan")

            messages = manager.get_messages(session.id)
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[1]["role"] == "assistant"

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.sessions_db = Path(tmpdir) / "sessions.db"

            manager = SessionManager(config)
            manager.create_session(target="example.com")
            manager.clear_all()

            sessions = manager.list_sessions()
            assert len(sessions) == 0

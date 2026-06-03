"""
Session Manager — SQLite-based session persistence.

Mirrors OpenCode's session management:
  - Save/load engagement sessions
  - Automatic context summarization
  - Resume previous sessions
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from argus_cli.config.settings import Config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    target TEXT,
    phase TEXT DEFAULT 'created',
    model TEXT,
    provider TEXT,
    findings_count INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    metadata TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    role TEXT,  -- 'user' | 'assistant' | 'system' | 'tool'
    content TEXT,
    timestamp TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_phase ON sessions(phase);
"""


@dataclass
class Session:
    """A single engagement session."""

    id: str
    target: str = ""
    phase: str = "created"
    model: str = "gpt-4o-mini"
    provider: str = "openai"
    findings_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    """
    Manages persistent sessions using SQLite.

    Provides OpenCode-style session management:
      - create_session()
      - get_session()
      - list_sessions()
      - save_message()
      - get_messages()
      - clear_all()
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.db_path = config.sessions_db
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure the sessions database exists with proper schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    def create_session(self, target: str = "", model: str = "") -> Session:
        """Create a new session."""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        session = Session(
            id=str(uuid.uuid4())[:8],
            target=target,
            model=model or self.config.model,
            provider=self.config.provider,
            created_at=now,
            updated_at=now,
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, target, phase, model, provider,
                                      findings_count, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.target,
                    session.phase,
                    session.model,
                    session.provider,
                    session.findings_count,
                    session.created_at,
                    session.updated_at,
                    json.dumps(session.metadata),
                ),
            )

        logger.info("Created session %s for target %s", session.id, target)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()

        if row is None:
            return None

        return self._row_to_session(row)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, target, phase, model, findings_count, created_at
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "id": row[0],
                "target": row[1],
                "phase": row[2],
                "model": row[3],
                "findings": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def update_session(self, session_id: str, **kwargs) -> None:
        """Update session fields."""
        allowed = {"target", "phase", "findings_count", "metadata"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}

        if not updates:
            return

        updates["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(self.db_path) as conn:
            for key, value in updates.items():
                if key == "metadata":
                    value = json.dumps(value)
                conn.execute(
                    f"UPDATE sessions SET {key} = ? WHERE id = ?",
                    (value, session_id),
                )

    def save_message(self, session_id: str, role: str, content: str) -> None:
        """Save a message to the session history."""
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, now),
            )

    def get_messages(self, session_id: str, limit: int = 100) -> list[dict[str, str]]:
        """Get messages for a session."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        return [
            {"role": row[0], "content": row[1], "timestamp": row[2]}
            for row in reversed(rows)
        ]

    def close(self) -> None:
        """Release SQLite file handles for cleanup on Windows.

        On Windows, SQLite can keep file handles open even after
        connections are closed. Call this when done to ensure the
        database file can be deleted (e.g. during temp directory cleanup).
        """
        import gc
        gc.collect()

    def clear_all(self) -> None:
        """Clear all sessions and messages."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            id=row[0],
            target=row[1],
            phase=row[2],
            model=row[3],
            provider=row[4],
            findings_count=row[5],
            created_at=row[6],
            updated_at=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )

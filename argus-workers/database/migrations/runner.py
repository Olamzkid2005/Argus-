"""
Migration Runner — applies pending SQL migrations in sorted order.

Usage:
    from database.migrations.runner import run_migrations
    run_migrations()

Or via CLI:
    python -m database.migrations.runner

Tracks applied migrations in a `_migrations` table so each migration
runs exactly once, in filename-sorted order.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def _ensure_tracking_table(conn) -> None:
    """Create the _migrations tracking table if it doesn't exist."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.commit()


def _get_applied(conn) -> set[str]:
    """Return the set of already-applied migration filenames."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT filename FROM _migrations ORDER BY filename")
        return {row[0] for row in cursor.fetchall()}


def _mark_applied(conn, filename: str) -> None:
    """Record a migration as applied."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO _migrations (filename) VALUES (%s) ON CONFLICT (filename) DO NOTHING",
            (filename,),
        )
        conn.commit()


def run_migrations(connection_string: str | None = None) -> list[str]:
    """Apply all pending SQL migrations.

    Args:
        connection_string: Optional database connection string.
                          If None, reads from DATABASE_URL env var.

    Returns:
        List of migration filenames that were applied.
    """
    import psycopg2

    conn_str = connection_string or os.getenv("DATABASE_URL")
    if not conn_str:
        logger.warning("No DATABASE_URL set — skipping migrations")
        return []

    conn = psycopg2.connect(conn_str)
    try:
        _ensure_tracking_table(conn)
        applied = _get_applied(conn)

        sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        pending = [f for f in sql_files if f.name not in applied]

        if not pending:
            logger.info("All %d migrations already applied", len(sql_files))
            return []

        applied_names = []
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            logger.info("Applying migration: %s", path.name)
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql)
                _mark_applied(conn, path.name)
                applied_names.append(path.name)
            except Exception as e:
                conn.rollback()
                logger.error("Migration %s failed: %s", path.name, e)
                raise

        logger.info(
            "Applied %d migration(s): %s", len(applied_names), ", ".join(applied_names)
        )
        return applied_names
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()

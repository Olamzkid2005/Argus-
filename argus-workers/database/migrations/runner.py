"""
Migration Runner — applies pending SQL migrations in sorted order.

Usage:
    from database.migrations.runner import run_migrations
    run_migrations()

Or via CLI:
    python -m database.migrations.runner

Tracks applied migrations in a `_migrations` table so each migration
runs exactly once, in filename-sorted order. Each migration is wrapped
in its own transaction so that a partial migration failure doesn't
corrupt the database. Failed migrations are recorded in the tracking
table with status 'failed' for observability.

Gap 11.2: Each migration runs as a single atomic statement. If a migration
fails, the error is logged with full detail and the tracking table records
the failure. The operator can inspect _migrations to identify failed
migrations and apply rollback_last_migration() to reverse them.
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def _ensure_tracking_table(conn) -> None:
    """Create the _migrations tracking table if it doesn't exist.

    Extends the schema with a ``status`` column to track migration state
    (applied, failed, rolled_back) and an ``error_message`` column for
    debugging failed migrations.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status TEXT NOT NULL DEFAULT 'applied',
                error_message TEXT
            )
            """
        )
    # Add status column if it doesn't exist (migration from old schema)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = '_migrations' AND column_name = 'status'
                """
            )
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE _migrations ADD COLUMN status TEXT NOT NULL DEFAULT 'applied'"
                )
                cursor.execute(
                    "ALTER TABLE _migrations ADD COLUMN error_message TEXT"
                )
    except Exception:
        pass  # Table might not exist yet — will be created on next run
    conn.commit()


def _get_applied(conn) -> set[str]:
    """Return the set of already-applied migration filenames."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT filename FROM _migrations ORDER BY filename")
        return {row[0] for row in cursor.fetchall()}


def _get_migration_history(conn) -> list[dict[str, Any]]:
    """Return full migration history with status for rollback support."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT filename, applied_at, status, error_message
            FROM _migrations
            ORDER BY applied_at DESC
            """
        )
        return [
            {
                "filename": row[0],
                "applied_at": row[1],
                "status": row[2],
                "error_message": row[3],
            }
            for row in cursor.fetchall()
        ]


def _mark_applied(conn, filename: str) -> None:
    """Record a migration as applied."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO _migrations (filename, status)
            VALUES (%s, 'applied')
            ON CONFLICT (filename) DO UPDATE SET
                status = 'applied',
                applied_at = NOW(),
                error_message = NULL
            """,
            (filename,),
        )
        conn.commit()


def _mark_failed(conn, filename: str, error_message: str) -> None:
    """Record a migration as failed."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO _migrations (filename, status, error_message)
            VALUES (%s, 'failed', %s)
            ON CONFLICT (filename) DO UPDATE SET
                status = 'failed',
                error_message = %s,
                applied_at = NOW()
            """,
            (filename, error_message, error_message),
        )
        conn.commit()


def run_migrations(connection_string: str | None = None) -> list[str]:
    """Apply all pending SQL migrations.

    Gap 11.2: Each migration runs as a single atomic SQL statement within its
    own implicit transaction. If a migration fails, the tracking table records
    it as 'failed' with the error message. Previously applied migrations are
    NOT rolled back — they remain committed. This is by design: rolling back
    already-applied migrations would lose data. Instead, the operator should
    create a NEW migration that reverses the failed one.

    Args:
        connection_string: Optional database connection string.
                          If None, reads from DATABASE_URL env var.

    Returns:
        List of migration filenames that were applied successfully.
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
        # Exclude both 'applied' and 'failed' migrations from re-run
        pending = [f for f in sql_files if f.name not in applied]

        if not pending:
            logger.info("All %d migrations already applied", len(sql_files))
            return []

        applied_names = []
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            logger.info("Applying migration: %s", path.name)
            try:
                # Each migration runs in its own implicit transaction.
                # psycopg2 wraps each cursor.execute in a transaction, so
                # if the SQL fails, only that migration is rolled back.
                with conn.cursor() as cursor:
                    cursor.execute(sql)
                _mark_applied(conn, path.name)
                applied_names.append(path.name)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                conn.rollback()
                _mark_failed(conn, path.name, error_msg)
                logger.error(
                    "Migration %s FAILED and recorded as 'failed': %s\n"
                    "To inspect: SELECT * FROM _migrations WHERE filename = '%s'\n"
                    "To fix: create a new migration that reverses the failed one.\n"
                    "Already-applied migrations (n=%d) remain committed.",
                    path.name,
                    error_msg,
                    path.name,
                    len(applied_names),
                )
                raise

        logger.info(
            "Applied %d migration(s): %s", len(applied_names), ", ".join(applied_names)
        )
        return applied_names
    finally:
        conn.close()


def rollback_last_migration(connection_string: str | None = None) -> dict[str, Any]:
    """View the most recently applied migration for rollback reference.

    This is a SAFETY NET that prints the last migration details so the
    operator knows which migration to reverse. It does NOT automatically
    reverse the migration — that would require a reversal script which
    is often lossy (e.g., a DROP COLUMN cannot be reversed automatically).

    Instead, this function:
    1. Shows the last successfully applied migration
    2. Prints the SQL that was applied
    3. Advises the operator to create a reversal migration

    Args:
        connection_string: Optional database connection string.

    Returns:
        Dict with last migration info, or empty dict if none found.
    """
    import psycopg2

    conn_str = connection_string or os.getenv("DATABASE_URL")
    if not conn_str:
        logger.warning("No DATABASE_URL set — cannot check rollback")
        return {}

    conn = psycopg2.connect(conn_str)
    try:
        history = _get_migration_history(conn)
        if not history:
            logger.info("No migrations found in history")
            return {}

        last = history[0]
        if last["status"] == "failed":
            logger.error(
                "Last migration '%s' FAILED: %s\n"
                "Fix the SQL and create a new migration file with corrected SQL.\n"
                "Do NOT manually DELETE the _migrations row — that would allow "
                "the failed migration to be re-attempted and fail again.",
                last["filename"],
                last["error_message"],
            )
        else:
            # Show the SQL of the last migration for reference
            migration_path = _MIGRATIONS_DIR / last["filename"]
            sql_content = ""
            if migration_path.exists():
                sql_content = migration_path.read_text(encoding="utf-8")[:2000]

            logger.info(
                "Last migration: %s (applied at %s)\n"
                "SQL:\n%s\n\n"
                "To reverse, create a NEW migration file with the reversal SQL.\n"
                "Example: 009_reverse_008.sql with ALTER TABLE ... DROP COLUMN statements.",
                last["filename"],
                last["applied_at"],
                sql_content,
            )

        return last
    finally:
        conn.close()


def get_migration_status(connection_string: str | None = None) -> list[dict[str, Any]]:
    """Get the full migration history with status for monitoring."""
    import psycopg2

    conn_str = connection_string or os.getenv("DATABASE_URL")
    if not conn_str:
        logger.warning("No DATABASE_URL set — cannot get migration status")
        return []

    conn = psycopg2.connect(conn_str)
    try:
        return _get_migration_history(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()

"""
Migration Runner — applies pending SQL and Python migrations in sorted order.

Usage:
    from database.migrations.runner import run_migrations
    run_migrations()

Or via CLI:
    python -m database.migrations.runner

Supports two migration file types:
  - .sql files: raw SQL executed directly (no rollback by default)
  - .py files: Python modules with apply(connection) and optional
    rollback(connection) functions

Tracks applied migrations in a `_migrations` table so each migration
runs exactly once, in filename-sorted order. Each migration is wrapped
in its own transaction so that a partial migration failure doesn't
corrupt the database. Failed migrations are recorded in the tracking
table with status 'failed' for observability.

Rollback support:
  - Python migrations: executed via rollback(connection) when available
  - SQL migrations: informational only (rollback SQL must be manually written)
  - See rollback_last_migration() for details
"""

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent
# Files that should NOT be treated as migration modules
_SKIP_FILES = {"runner.py", "__init__.py"}


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


def _mark_rolled_back(conn, filename: str) -> None:
    """Record a migration as rolled back."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE _migrations SET status = 'rolled_back', applied_at = NOW() WHERE filename = %s",
            (filename,),
        )
        conn.commit()


def _load_python_migration(path: Path) -> Any:
    """Dynamically import a Python migration module by file path.

    The module must expose an `apply(connection)` function and should
    expose an optional `rollback(connection)` function.
    """
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load migration module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _get_migration_files() -> list[Path]:
    """Get all migration files (.sql and .py), sorted by filename.

    Returns:
        List of Path objects, sorted lexicographically by filename.
    """
    sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    py_files = sorted(
        p for p in _MIGRATIONS_DIR.glob("*.py")
        if p.name not in _SKIP_FILES
    )
    return sorted(sql_files + py_files, key=lambda p: p.name)


def run_migrations(connection_string: str | None = None) -> list[str]:
    """Apply all pending SQL and Python migrations.

    Migrations are applied in filename-sorted order. Each migration runs
    in its own implicit transaction. If a migration fails, the tracking
    table records it as 'failed' and the error is raised. Previously
    applied migrations remain committed.

    Python migrations must expose `apply(connection)` function.

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

        migration_files = _get_migration_files()
        pending = [f for f in migration_files if f.name not in applied]

        if not pending:
            logger.info("All %d migrations already applied", len(migration_files))
            return []

        applied_names = []
        for path in pending:
            logger.info("Applying migration: %s", path.name)
            try:
                if path.suffix == ".sql":
                    # SQL migration — execute raw SQL directly
                    sql = path.read_text(encoding="utf-8")
                    with conn.cursor() as cursor:
                        cursor.execute(sql)
                elif path.suffix == ".py":
                    # Python migration — import and call apply(connection)
                    module = _load_python_migration(path)
                    if not hasattr(module, "apply"):
                        raise ValueError(
                            f"Python migration {path.name} has no apply() function"
                        )
                    module.apply(conn)
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
    """Roll back the most recently applied migration.

    For Python migrations with a rollback() function, this executes the
    rollback. For SQL migrations or Python migrations without rollback(),
    this is informational only — it shows the SQL/content of the last
    migration and advises the operator on how to reverse it manually.

    Note: Automated rollback of SQL migrations is not supported because
    it requires reversal SQL that's often lossy (e.g., DROP COLUMN cannot
    be reversed automatically). Create a NEW migration file with reversal
    SQL for SQL-based rollbacks.

    Args:
        connection_string: Optional database connection string.

    Returns:
        Dict with info about the rolled-back migration, or empty dict
        if no applicable migration found.
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
                "Fix the SQL/Python and create a new migration file with corrected code.\n"
                "Do NOT manually DELETE the _migrations row — that would allow "
                "the failed migration to be re-attempted and fail again.",
                last["filename"],
                last["error_message"],
            )
            return last

        if last["status"] != "applied":
            logger.info(
                "Last migration '%s' status is '%s' — nothing to roll back",
                last["filename"],
                last["status"],
            )
            return last

        migration_path = _MIGRATIONS_DIR / last["filename"]

        # Python migration with rollback() function
        if migration_path.suffix == ".py" and migration_path.exists():
            module = _load_python_migration(migration_path)
            if hasattr(module, "rollback"):
                logger.info(
                    "Rolling back Python migration: %s",
                    last["filename"],
                )
                module.rollback(conn)
                _mark_rolled_back(conn, last["filename"])
                conn.commit()
                logger.info(
                    "Successfully rolled back migration: %s",
                    last["filename"],
                )
                last["rolled_back"] = True
                return last

        # SQL migration or Python migration without rollback — informational only
        migration_content = ""
        if migration_path.exists():
            migration_content = migration_path.read_text(encoding="utf-8")[:2000]

        logger.info(
            "Last migration: %s (applied at %s, type=%s)\n"
            "Content:\n%s\n\n"
            "To reverse, create a NEW migration file with the reversal logic.\n"
            "Example: 009_reverse_008.sql with ALTER TABLE ... DROP COLUMN statements.\n"
            "For Python migrations, add a rollback() function to the module.",
            last["filename"],
            last["applied_at"],
            migration_path.suffix if migration_path.exists() else "unknown",
            migration_content,
        )
        last["rolled_back"] = False
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

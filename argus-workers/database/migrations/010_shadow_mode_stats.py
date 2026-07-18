"""
Migration 010: Create shadow_mode_stats table for cross-worker shadow mode convergence.

Replaces per-process threading.Lock() counters (which don't synchronize across
Celery workers) with a PostgreSQL table that uses atomic UPDATE operations.
This enables the "100 consecutive successes before flipping" requirement
to converge across all workers in a multi-worker deployment.
"""

import logging

logger = logging.getLogger(__name__)

MIGRATION_NAME = "010_shadow_mode_stats"
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS shadow_mode_stats (
    phase VARCHAR(64) NOT NULL,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    total_mismatches INTEGER NOT NULL DEFAULT 0,
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_result VARCHAR(16) NOT NULL DEFAULT 'none',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (phase)
);
"""

ROLLBACK_SQL = """
DROP TABLE IF EXISTS shadow_mode_stats;
"""


def apply(connection):
    """Apply migration 010."""
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(MIGRATION_SQL)
        connection.commit()
        logger.info("Migration %s applied successfully", MIGRATION_NAME)
        return True
    except Exception as e:
        connection.rollback()
        logger.error("Migration %s failed: %s", MIGRATION_NAME, e)
        raise
    finally:
        if cursor:
            cursor.close()


def rollback(connection):
    """Rollback migration 010."""
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(ROLLBACK_SQL)
        connection.commit()
        logger.info("Migration %s rolled back successfully", MIGRATION_NAME)
        return True
    except Exception as e:
        connection.rollback()
        logger.error("Migration %s rollback failed: %s", MIGRATION_NAME, e)
        raise
    finally:
        if cursor:
            cursor.close()

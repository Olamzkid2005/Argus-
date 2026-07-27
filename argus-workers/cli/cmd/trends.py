"""Trends command for the Argus CLI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import cli._local_mode as local_mode

logger = logging.getLogger("cli.cmd")


def cmd_trends(args: argparse.Namespace) -> int:
    """Show cross-engagement trend analysis.

    Aggregates findings across all engagements in the SQLite database
    to surface portfolio-level insights: trending vulnerabilities, most
    affected domains, CWE frequency, and risk scoring.

    Usage:
        argus trends
        argus trends --domain example.com
        argus trends --last-n-days 90
        argus trends --min-severity HIGH
        argus trends --verbose
    """
    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    try:
        from database.sqlite_trends import SQLiteTrendRepository, display_trend_summary

        repo = SQLiteTrendRepository(db_path)
        trends = repo.get_trends(
            domain=getattr(args, "domain", None),
            last_n_days=getattr(args, "last_n_days", None),
            min_severity=getattr(args, "min_severity", None),
        )

        output = display_trend_summary(
            trends,
            verbose=getattr(args, "verbose", False),
        )
        print(output)
        repo.close()
        return 0

    except ImportError as e:
        logger.error("Trend analysis module not available: %s", e)
        return 1
    except Exception as e:
        logger.error("Trend analysis failed: %s", e)
        return 1



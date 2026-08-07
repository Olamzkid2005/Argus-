"""List command for the Argus CLI."""

from __future__ import annotations

import argparse
import logging

import cli._local_mode as local_mode

logger = logging.getLogger("cli.cmd")


def cmd_list(args: argparse.Namespace) -> int:
    """List recent engagements."""
    from database.sqlite_backend import SQLiteEngagementRepo

    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))
    eng_repo = SQLiteEngagementRepo(db_path)
    engagements = eng_repo.find_by_org("local", limit=args.limit or 20)

    if not engagements:
        print("No engagements found.")
        return 0

    print(f"{'ID':<40} {'Target':<40} {'Status':<15} {'Findings':<10}")
    print("-" * 105)
    for eng in engagements:
        print(
            f"{str(eng.get('id', ''))[:36]:<40} "
            f"{str(eng.get('target', ''))[:38]:<40} "
            f"{str(eng.get('status', '')):<15} "
            f"{str(eng.get('findings_count', '-')):<10}"
        )
    return 0



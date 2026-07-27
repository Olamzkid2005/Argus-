"""Assess command for the Argus CLI."""

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


def cmd_assess(args: argparse.Namespace) -> int:
    """Run a full assessment: recon -> scan -> analyze -> report."""
    target = args.target
    engagement_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    logger.info("Starting assessment %s against %s", engagement_id[:8], target)
    logger.info("Storage: %s", "in-memory (ephemeral)" if db_path == ":memory:" else db_path)

    local_mode._run_startup_health_check()

    # Step 1: Create engagement record
    eng_repo, finding_repo = local_mode._setup_local_mode(db_path)
    engagement = eng_repo.create({
        "target_url": target,
        "org_id": "local",
        "status": "created",
        "scan_type": "url",
        "created_by": "cli",
    })
    logger.info("Created engagement %s", engagement.get("id", engagement_id)[:8])

    # Override DATABASE_URL for local execution
    if os.environ.get("ARGUS_LOCAL_MODE", "") != "1":
        os.environ["ARGUS_LOCAL_MODE"] = "1"
    old_db_url = os.environ.pop("DATABASE_URL", None)

    # Create orchestrator
    eng_id = engagement.get("id", engagement_id)
    orch = local_mode._get_orchestrator(eng_id, db_path=db_path, trace_id=trace_id)
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    # Checkpoint manager for crash recovery
    cp_mgr = None
    if db_path != ":memory:":
        try:
            from database.sqlite_checkpoint import SQLiteCheckpointManager
            cp_mgr = SQLiteCheckpointManager(db_path)
            logger.info("Checkpoints enabled for crash recovery")
        except Exception:
            logger.debug("Checkpoint manager not available", exc_info=True)

    try:
        # Run assessment phases using shared helper
        exit_code, phase_results = local_mode._run_phases(
            orch, target,
            engagement_id=eng_id,
            finding_repo=finding_repo,
            aggressiveness=args.aggressiveness or "moderate",
            output_format=args.format or "json",
            phases=("recon", "scan", "analyze", "report"),
            cp_mgr=cp_mgr,
            llm_refine=getattr(args, "llm_refine", False),
            trace_id=trace_id,
        )

        if exit_code != 0:
            return exit_code

        # Output results
        local_mode._output_results(eng_id, target, finding_repo, args.output)

        # Clean up checkpoints
        if cp_mgr is not None:
            try:
                cp_mgr.delete_checkpoints(eng_id)
            except Exception:
                logger.debug("Checkpoint cleanup failed", exc_info=True)

        # Store coverage report
        local_mode._store_coverage_report(orch, eng_repo, eng_id)

        logger.info("Assessment complete")
        return 0

    finally:
        if old_db_url is not None:
            os.environ["DATABASE_URL"] = old_db_url
        if "ARGUS_LOCAL_MODE" in os.environ:
            del os.environ["ARGUS_LOCAL_MODE"]



"""Resume command for the Argus CLI."""

from __future__ import annotations

import argparse
import logging
import os
import uuid

import cli._local_mode as local_mode

logger = logging.getLogger("cli.cmd")


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a crashed assessment from its last checkpoint.

    Loads the latest checkpoint for an engagement, determines which
    phase to resume from, and runs the remaining phases using the
    shared :func:`_run_phases` helper.

    Usage:
        argus resume <engagement_id> --local
        argus resume <engagement_id> --db assessments.db
    """
    engagement_id = args.engagement_id
    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    # Load checkpoint
    try:
        from database.sqlite_checkpoint import SQLiteCheckpointManager
        cp_mgr = SQLiteCheckpointManager(db_path)
    except ImportError as e:
        logger.error("Checkpoint manager not available: %s", e)
        return 1

    plan = cp_mgr.get_resume_plan(engagement_id)
    if plan is None:
        logger.error(
            "No checkpoint found for engagement %s. "
            "Pass --local or --db <path> to locate the database.",
            engagement_id[:8],
        )
        cp_mgr.close()
        return 1

    if not plan.can_resume:
        logger.info("Engagement %s is already complete — nothing to resume", engagement_id[:8])
        cp_mgr.close()
        return 0

    # Load repositories and engagement details
    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    eng_repo = SQLiteEngagementRepo(db_path)
    finding_repo = SQLiteFindingRepo(db_path)

    eng = eng_repo.find_by_id(engagement_id)
    if eng is None:
        logger.error("Engagement %s not found", engagement_id[:8])
        cp_mgr.close()
        return 1

    target = eng.get("target_url") or plan.partial_results.get("target", "")
    trace_id = plan.partial_results.get("trace_id", str(uuid.uuid4()))
    aggressiveness = plan.partial_results.get("aggressiveness", "moderate")
    output_format = plan.partial_results.get("format", "json")
    phase_results: list[dict] = plan.partial_results.get("phase_results", [])

    logger.info("Resuming engagement %s from phase '%s'", engagement_id[:8], plan.next_phase)
    logger.info("Remaining phases: %s", ", ".join(plan.remaining_phases))
    logger.info("Last checkpoint: %s", plan.checkpoint_timestamp)

    # Restore ARGUS_LOCAL_MODE
    os.environ["ARGUS_LOCAL_MODE"] = "1"
    old_db_url = os.environ.pop("DATABASE_URL", None)

    # Create orchestrator
    orch = local_mode._get_orchestrator(engagement_id, db_path=db_path, trace_id=trace_id)
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    try:
        # Run remaining phases using shared helper
        exit_code, phase_results = local_mode._run_phases(
            orch, target,
            engagement_id=engagement_id,
            finding_repo=finding_repo,
            aggressiveness=aggressiveness,
            output_format=output_format,
            phases=plan.remaining_phases,
            phase_results=phase_results,
            cp_mgr=cp_mgr,
            llm_refine=getattr(args, "llm_refine", False),
            trace_id=trace_id,
        )

        if exit_code != 0:
            return exit_code

        # Output results
        local_mode._output_results(engagement_id, target, finding_repo, args.output)

        # Clean up checkpoints
        try:
            cp_mgr.delete_checkpoints(engagement_id)
        except Exception:
            pass

        # Store coverage report
        local_mode._store_coverage_report(orch, eng_repo, engagement_id)

        logger.info("Resume complete")
        return 0

    finally:
        cp_mgr.close()
        if old_db_url is not None:
            os.environ["DATABASE_URL"] = old_db_url
        if "ARGUS_LOCAL_MODE" in os.environ:
            del os.environ["ARGUS_LOCAL_MODE"]



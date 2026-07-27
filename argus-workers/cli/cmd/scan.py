"""Scan command for the Argus CLI."""

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


def cmd_scan(args: argparse.Namespace) -> int:
    """Run scan phase only."""
    from orchestrator_pkg.orchestrator import Orchestrator

    target = args.target
    engagement_id = str(uuid.uuid4())
    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    eng_repo, finding_repo = local_mode._setup_local_mode(db_path)
    engagement = eng_repo.create({
        "target_url": target,
        "org_id": "local",
        "status": "scanning",
        "scan_type": "url",
    })

    orch = Orchestrator(engagement_id=engagement.get("id", engagement_id))
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    job: dict[str, Any] = {
        "type": "scan",
        "targets": [target],
        "target": target,
        "engagement_id": engagement.get("id", engagement_id),
        "scope": {"mode": "allowlist", "allowed_targets": [target]},
        "aggressiveness": args.aggressiveness or "moderate",
        "agent_mode": False,
    }

    try:
        result = orch.run(job)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as e:
        logger.error("Scan failed: %s", e)
        return 1



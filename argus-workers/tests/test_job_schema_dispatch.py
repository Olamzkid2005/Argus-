"""Contract tests for job_schema.build_task_args / JobMessage.to_celery_args."""

from __future__ import annotations

import uuid

from job_schema import JobMessage, build_task_args


def test_build_task_args_recon_includes_trace_agent_scan_flags():
    eid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    args = build_task_args(
        "recon",
        eid,
        "https://example.com",
        {"max_cycles": 3, "max_depth": 2},
        tid,
        agent_mode=False,
        scan_mode="swarm",
        aggressiveness="high",
        bug_bounty_mode=True,
    )
    assert args == [
        eid,
        "https://example.com",
        {"max_cycles": 3, "max_depth": 2},
        tid,
        False,
        "swarm",
        "high",
        True,
    ]


def test_job_message_to_celery_args_round_trip_recon():
    j = JobMessage(
        type="recon",
        engagement_id="123e4567-e89b-12d3-a456-426614174000",
        target="https://example.com",
        budget={"max_cycles": 5, "max_depth": 3},
        trace_id="123e4567-e89b-12d3-a456-426614174001",
        agent_mode=False,
        scan_mode="swarm",
        aggressiveness="extreme",
        bug_bounty_mode=False,
        created_at="2026-01-01T00:00:00Z",
    )
    args = j.to_celery_args()
    assert args[3] == j.trace_id
    assert args[4] is False
    assert args[5] == "swarm"
    assert args[6] == "extreme"
    assert args[7] is False


def test_build_task_args_analyze_includes_budget_and_trace():
    eid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    b = {"max_cycles": 2, "max_depth": 1}
    args = build_task_args("analyze", eid, "", b, tid)
    assert args == [eid, b, tid]


def test_build_task_args_repo_scan_uses_repo_url_and_trace():
    eid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    b = {"max_cycles": 1, "max_depth": 1}
    args = build_task_args(
        "repo_scan",
        eid,
        "ignored-target",
        b,
        tid,
        repo_url="https://github.com/org/repo.git",
    )
    assert args[0] == eid
    assert args[1] == "https://github.com/org/repo.git"
    assert args[2] == b
    assert args[3] == tid

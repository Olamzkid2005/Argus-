"""Reporter: one task-level report built only from persisted results and evidence.

The Reporter performs no research and generates no findings. It aggregates the
subtask results and action records the delegation service already persisted, so
the report cannot introduce new claims or completed-work fiction (P-15).
"""

from __future__ import annotations

from typing import Any

from agent.delegation.models import ACTIVE_SUBTASK_STATUSES, DelegationError


class Reporter:
    """Assembles a task report once, from durable state only."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def report(self, task_id: str) -> dict[str, Any]:
        existing = self._store.find_report(task_id)
        if existing is not None:
            return {
                "report_id": str(existing["task_id"]),
                "body": existing["body"],
                "created": False,
            }

        task = self._store.find_task(task_id)
        if task is None:
            raise DelegationError(f"task {task_id} does not exist")
        subtasks = self._store.find_subtasks(task_id)
        active = [
            row for row in subtasks if row["status"] in ACTIVE_SUBTASK_STATUSES
        ]
        if active:
            raise DelegationError(
                "reporter needs every subtask terminal; still active: "
                + ", ".join(row["title"] for row in active)
            )

        findings: list[dict[str, Any]] = []
        evidence_refs: set[str] = set()
        actions: list[dict[str, Any]] = []
        subtask_summaries: list[dict[str, Any]] = []
        for row in subtasks:
            result = row.get("result") or {}
            for finding in result.get("findings") or []:
                findings.append({**dict(finding), "subtask_id": str(row["id"])})
            for ref in result.get("evidence_refs") or []:
                evidence_refs.add(str(ref))
            for action in self._store.find_actions(row["id"]):
                actions.append(action)
                for ref in action.get("evidence_refs") or []:
                    evidence_refs.add(str(ref))
                for finding in (action.get("result") or {}).get("findings") or []:
                    findings.append(
                        {
                            **dict(finding),
                            "subtask_id": str(row["id"]),
                            "action_id": action["action_id"],
                        }
                    )
            subtask_summaries.append(
                {
                    "id": str(row["id"]),
                    "ordinal": row["ordinal"],
                    "title": row["title"],
                    "status": row["status"],
                    "summary": result.get("summary"),
                    "resolution": row.get("resolution"),
                }
            )

        body = {
            "task_id": str(task["id"]),
            "engagement_id": str(task["engagement_id"]),
            "objective": task["objective"],
            "status": task["status"],
            "summary": "; ".join(
                entry["summary"]
                for entry in subtask_summaries
                if entry.get("summary")
            ),
            "subtasks": subtask_summaries,
            "findings": findings,
            "finding_count": len(findings),
            "evidence_refs": sorted(evidence_refs),
            "actions_recorded": len(actions),
            "resolutions": [
                {"subtask_id": entry["id"], "resolution": entry["resolution"]}
                for entry in subtask_summaries
                if entry.get("resolution")
            ],
        }
        row, created = self._store.save_report(task_id, body)
        return {
            "report_id": str(row["task_id"]),
            "body": row["body"],
            "created": created,
        }

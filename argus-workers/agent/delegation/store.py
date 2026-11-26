"""Durable persistence for the Flow/Task/Subtask/Action hierarchy (plan §4.3/§4.4).

The delegation service owns these writes. Agents (Primary, Generator, Refiner,
specialists, Reflector, Reporter, Memorist) receive bounded payloads or return
structured results and never hold this repository, so they cannot mutate task
state or the graph directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from agent.delegation.generator import normalize_title
from agent.delegation.models import (
    ACTIVE_SUBTASK_STATUSES,
    MAX_ACTIVE_SUBTASKS,
    TERMINAL_SUBTASK_STATUSES,
    UNRESOLVED_SUBTASK_STATUSES,
    DelegationError,
    InvalidTransition,
    PatchValidationError,
    SubtaskDraft,
    SubtaskStatus,
    TaskCompletionError,
    TaskStatus,
    validate_subtask_transition,
    validate_task_transition,
)
from database.repositories.base import BaseRepository


def _dependency_satisfied(row: dict[str, Any] | None) -> bool:
    """A dependency is satisfied by finished work or an accepted skip/cancel."""
    if row is None:
        return False
    if row["status"] == SubtaskStatus.FINISHED:
        return True
    return row["status"] in UNRESOLVED_SUBTASK_STATUSES and bool(
        row.get("resolution")
    )


class PostgresDelegationStore(BaseRepository):
    """PostgreSQL storage for delegation tasks, subtasks, actions and evidence."""

    table_name = "delegation_tasks"
    id_column = "id"

    # ----- tasks -----

    def create_task(
        self,
        engagement_id: str,
        objective: str,
        *,
        intent_id: str | None = None,
        generator_version: int = 1,
        task_context_ref: str | None = None,
    ) -> dict[str, Any]:
        """Create one Task under an engagement, verifying intent ownership."""
        if not engagement_id or not objective or not str(objective).strip():
            raise DelegationError("engagement_id and a non-empty objective are required")
        objective = str(objective).strip()
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            if intent_id is not None:
                cursor.execute(
                    "SELECT engagement_id FROM graph_nodes WHERE id = %s",
                    (intent_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise DelegationError(f"intent {intent_id} does not exist")
                if str(row["engagement_id"]) != str(engagement_id):
                    raise DelegationError(
                        f"intent {intent_id} belongs to engagement "
                        f"{row['engagement_id']}, not {engagement_id}"
                    )
            cursor.execute(
                """
                INSERT INTO delegation_tasks
                    (engagement_id, intent_id, objective, generator_version,
                     task_context_ref)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    engagement_id,
                    intent_id,
                    objective,
                    generator_version,
                    task_context_ref,
                ),
            )
            return dict(cursor.fetchone())

    def find_task(self, task_id: str) -> dict[str, Any] | None:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute("SELECT * FROM delegation_tasks WHERE id = %s", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_tasks_for_engagement(self, engagement_id: str) -> list[dict[str, Any]]:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                """
                SELECT * FROM delegation_tasks
                WHERE engagement_id = %s
                ORDER BY created_at, id
                """,
                (engagement_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def set_task_status(self, task_id: str, status: str) -> dict[str, Any]:
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT status FROM delegation_tasks WHERE id = %s FOR UPDATE",
                (task_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise DelegationError(f"task {task_id} does not exist")
            validate_task_transition(row["status"], status)
            cursor.execute(
                """
                UPDATE delegation_tasks
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (status, task_id),
            )
            return dict(cursor.fetchone())

    # ----- generated plan -----

    def insert_plan(
        self,
        task_id: str,
        drafts: Iterable[SubtaskDraft],
        *,
        max_active: int = MAX_ACTIVE_SUBTASKS,
    ) -> list[dict[str, Any]]:
        """Persist a validated generated plan as this task's ordered subtasks."""
        draft_list = list(drafts)
        if not 1 <= len(draft_list) <= max_active:
            raise PatchValidationError(
                f"a task plan must have 1..{max_active} subtasks, got {len(draft_list)}"
            )
        normalized_titles = [normalize_title(draft.title) for draft in draft_list]
        if len(set(normalized_titles)) != len(normalized_titles):
            raise PatchValidationError(
                "a generated plan cannot contain duplicate subtask titles"
            )
        for draft in draft_list:
            if not draft.title.strip() or not draft.description.strip():
                raise PatchValidationError(
                    "every generated subtask needs a title and a description"
                )
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT * FROM delegation_tasks WHERE id = %s FOR UPDATE",
                (task_id,),
            )
            task = cursor.fetchone()
            if task is None:
                raise DelegationError(f"task {task_id} does not exist")
            if task["status"] in (TaskStatus.FINISHED, TaskStatus.FAILED):
                raise PatchValidationError(
                    f"task {task_id} is {task['status']!r}; it cannot receive a new plan"
                )
            cursor.execute(
                "SELECT COUNT(*) AS n FROM delegation_subtasks WHERE task_id = %s",
                (task_id,),
            )
            if cursor.fetchone()["n"]:
                raise PatchValidationError(
                    "task already has a persisted plan; refine it instead of replacing it"
                )
            for ordinal, draft in enumerate(draft_list, start=1):
                cursor.execute(
                    """
                    INSERT INTO delegation_subtasks
                        (task_id, ordinal, title, description, depends_on, status,
                         completion_condition, tool, arguments)
                    VALUES (%s, %s, %s, %s, %s, 'created', %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        task_id,
                        ordinal,
                        draft.title,
                        draft.description,
                        Json([normalize_title(dep) for dep in draft.depends_on]),
                        draft.completion_condition,
                        draft.tool,
                        Json(dict(draft.arguments or {})),
                    ),
                )
                cursor.fetchone()
            return self._resolve_dependencies(cursor, task_id)

    def _resolve_dependencies(
        self, cursor: Any, task_id: str
    ) -> list[dict[str, Any]]:
        """Rewrite title-based dependency references to persisted subtask IDs."""
        cursor.execute(
            """
            SELECT * FROM delegation_subtasks
            WHERE task_id = %s ORDER BY ordinal
            """,
            (task_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        by_title = {normalize_title(row["title"]): str(row["id"]) for row in rows}
        for row in rows:
            deps: list[str] = []
            for title_key in row.get("depends_on") or []:
                target = by_title.get(normalize_title(str(title_key)))
                if target is None:
                    raise PatchValidationError(
                        f"subtask {row['title']!r} depends on unknown draft {title_key!r}"
                    )
                if target == str(row["id"]):
                    raise PatchValidationError(
                        f"subtask {row['title']!r} cannot depend on itself"
                    )
                deps.append(target)
            if deps:
                cursor.execute(
                    "UPDATE delegation_subtasks SET depends_on = %s WHERE id = %s",
                    (Json(deps), row["id"]),
                )
        cursor.execute(
            """
            SELECT * FROM delegation_subtasks
            WHERE task_id = %s ORDER BY ordinal
            """,
            (task_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def find_subtasks(self, task_id: str) -> list[dict[str, Any]]:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                """
                SELECT * FROM delegation_subtasks
                WHERE task_id = %s ORDER BY ordinal
                """,
                (task_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def find_subtask(self, subtask_id: str) -> dict[str, Any] | None:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                "SELECT * FROM delegation_subtasks WHERE id = %s", (subtask_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # ----- sequential execution -----

    def claim_next_subtask(
        self, task_id: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Start the next subtask if and only if the task order allows it.

        Returns ``(subtask, reason)``. ``reason`` explains why nothing started so
        callers never have to guess (for example ``waiting`` or
        ``dependency_blocked``).
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT status FROM delegation_tasks WHERE id = %s FOR UPDATE",
                (task_id,),
            )
            task_row = cursor.fetchone()
            if task_row is None:
                raise DelegationError(f"task {task_id} does not exist")
            if task_row["status"] == TaskStatus.CREATED:
                validate_task_transition(TaskStatus.CREATED, TaskStatus.RUNNING)
                cursor.execute(
                    "UPDATE delegation_tasks SET status = 'running', updated_at = NOW() "
                    "WHERE id = %s",
                    (task_id,),
                )
            cursor.execute(
                """
                SELECT * FROM delegation_subtasks
                WHERE task_id = %s ORDER BY ordinal
                """,
                (task_id,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            if not rows:
                return None, "empty_plan"
            rows_by_id = {str(row["id"]): row for row in rows}
            for row in rows:
                if row["status"] in ACTIVE_SUBTASK_STATUSES:
                    if row["status"] != SubtaskStatus.CREATED:
                        return None, f"{row['status']}_in_progress"
                    blocked = [
                        dep
                        for dep in row.get("depends_on") or []
                        if not _dependency_satisfied(rows_by_id.get(str(dep)))
                    ]
                    if blocked:
                        return None, "dependency_blocked"
                    cursor.execute(
                        """
                        UPDATE delegation_subtasks
                        SET status = 'running', started_at = NOW(), updated_at = NOW()
                        WHERE id = %s AND status = 'created'
                        RETURNING *
                        """,
                        (row["id"],),
                    )
                    started = cursor.fetchone()
                    if started is None:
                        return None, "already_started"
                    return dict(started), "started"
            return None, "all_terminal"

    def transition_subtask(
        self,
        subtask_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        result_ref: str | None = None,
        message_chain_ref: str | None = None,
        last_error: str | None = None,
        increment_retry: bool = False,
    ) -> dict[str, Any]:
        """Move one subtask through the state machine and persist its outcome."""
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT * FROM delegation_subtasks WHERE id = %s FOR UPDATE",
                (subtask_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise DelegationError(f"subtask {subtask_id} does not exist")
            validate_subtask_transition(row["status"], status)
            if result is not None and not isinstance(result, dict):
                raise DelegationError("a subtask result must be an object")
            if status == SubtaskStatus.FINISHED and result is None:
                raise DelegationError(
                    "finishing a subtask requires a persisted structured result"
                )
            if status in (
                SubtaskStatus.FAILED,
                SubtaskStatus.SKIPPED,
                SubtaskStatus.CANCELLED,
            ) and not (last_error and str(last_error).strip()):
                raise DelegationError(
                    f"moving a subtask to {status} requires an explicit reason"
                )
            finished = status in (
                SubtaskStatus.FINISHED,
                SubtaskStatus.FAILED,
                SubtaskStatus.SKIPPED,
                SubtaskStatus.CANCELLED,
            )
            cursor.execute(
                """
                UPDATE delegation_subtasks SET
                    status = %s,
                    result = result || COALESCE(%s, '{}'::jsonb),
                    result_ref = COALESCE(%s, result_ref),
                    message_chain_ref = COALESCE(%s, message_chain_ref),
                    last_error = %s,
                    retry_count = retry_count + %s,
                    finished_at = CASE WHEN %s THEN NOW() ELSE finished_at END,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (
                    status,
                    Json(result) if result is not None else None,
                    result_ref,
                    message_chain_ref,
                    last_error,
                    1 if increment_retry else 0,
                    finished,
                    subtask_id,
                ),
            )
            return dict(cursor.fetchone())

    def resolve_subtask(self, subtask_id: str, reason: str) -> dict[str, Any]:
        """Record the explicit accepted-skip/failure resolution P-17 requires."""
        if not isinstance(reason, str) or not reason.strip():
            raise DelegationError("a resolution reason is required")
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT * FROM delegation_subtasks WHERE id = %s FOR UPDATE",
                (subtask_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise DelegationError(f"subtask {subtask_id} does not exist")
            if row["status"] not in UNRESOLVED_SUBTASK_STATUSES:
                raise InvalidTransition(
                    f"subtask {subtask_id} is {row['status']!r}; only failed, skipped "
                    "or cancelled subtasks need a resolution"
                )
            cursor.execute(
                """
                UPDATE delegation_subtasks
                SET resolution = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (reason.strip(), subtask_id),
            )
            return dict(cursor.fetchone())

    def reconcile_stale_subtasks(self, task_id: str) -> list[dict[str, Any]]:
        """Make interrupted RUNNING subtasks resumable without losing evidence.

        PentAGI reloads a still-running subtask as created and reuses its agent
        chain. Argus reproduces that: status returns to ``created``, the message
        chain and any persisted result/evidence stay, and the interruption is
        recorded so a blind replay is visible.
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                """
                UPDATE delegation_subtasks
                SET status = 'created',
                    last_error = 'interrupted: reconciled to resumable',
                    updated_at = NOW()
                WHERE task_id = %s AND status = 'running'
                RETURNING *
                """,
                (task_id,),
            )
            reconciled = [dict(row) for row in cursor.fetchall()]
            if reconciled:
                cursor.execute(
                    "UPDATE delegation_tasks SET status = 'running', updated_at = NOW() "
                    "WHERE id = %s AND status IN ('created', 'waiting')",
                    (task_id,),
                )
            return reconciled

    def finalize_task(self, task_id: str) -> dict[str, Any]:
        """Finish a task only when every required subtask is resolved."""
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT * FROM delegation_tasks WHERE id = %s FOR UPDATE", (task_id,)
            )
            task = cursor.fetchone()
            if task is None:
                raise DelegationError(f"task {task_id} does not exist")
            if task["status"] == TaskStatus.FINISHED:
                return dict(task)
            cursor.execute(
                "SELECT * FROM delegation_subtasks WHERE task_id = %s ORDER BY ordinal",
                (task_id,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            active = [row for row in rows if row["status"] in ACTIVE_SUBTASK_STATUSES]
            if active:
                raise TaskCompletionError(
                    "task cannot finish while subtasks are still active: "
                    + ", ".join(f"{row['title']} ({row['status']})" for row in active)
                )
            unresolved = [
                row
                for row in rows
                if row["required"]
                and row["status"] in UNRESOLVED_SUBTASK_STATUSES
                and not row.get("resolution")
            ]
            if unresolved:
                raise TaskCompletionError(
                    "task cannot be marked successful without an explicit resolution: "
                    + ", ".join(f"{row['title']} ({row['status']})" for row in unresolved)
                )
            status = task["status"]
            if status in (TaskStatus.CREATED, TaskStatus.WAITING):
                status = TaskStatus.RUNNING
            validate_task_transition(status, TaskStatus.FINISHED)
            cursor.execute(
                """
                UPDATE delegation_tasks
                SET status = 'finished', updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (task_id,),
            )
            return dict(cursor.fetchone())

    # ----- actions + evidence -----

    def record_action(
        self,
        subtask_id: str,
        action_id: str,
        *,
        tool: str | None = None,
        canonical_arguments: dict[str, Any] | None = None,
        source_agent: str | None = None,
        reasoning_ref: str | None = None,
        outcome: str = "completed",
        result: dict[str, Any] | None = None,
        evidence_refs: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Record one action idempotently; a replay returns the original row."""
        if not subtask_id or not action_id:
            raise DelegationError("subtask_id and action_id are required")
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO delegation_actions
                    (subtask_id, action_id, tool, canonical_arguments, source_agent,
                     reasoning_ref, outcome, result, evidence_refs, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (subtask_id, action_id) DO NOTHING
                RETURNING *
                """,
                (
                    subtask_id,
                    action_id,
                    tool,
                    Json(canonical_arguments or {}),
                    source_agent,
                    reasoning_ref,
                    outcome,
                    Json(result or {}),
                    Json(list(evidence_refs)),
                ),
            )
            row = cursor.fetchone()
            if row is not None:
                return dict(row)
            cursor.execute(
                """
                SELECT * FROM delegation_actions
                WHERE subtask_id = %s AND action_id = %s
                """,
                (subtask_id, action_id),
            )
            return dict(cursor.fetchone())

    def find_action(self, subtask_id: str, action_id: str) -> dict[str, Any] | None:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                """
                SELECT * FROM delegation_actions
                WHERE subtask_id = %s AND action_id = %s
                """,
                (subtask_id, action_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_actions(self, subtask_id: str) -> list[dict[str, Any]]:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                """
                SELECT * FROM delegation_actions
                WHERE subtask_id = %s ORDER BY started_at, id
                """,
                (subtask_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ----- refiner patches -----

    def apply_plan(
        self,
        task_id: str,
        items: Iterable[Any],
        *,
        trigger_subtask_id: str | None,
        rationale: str,
        operations: Iterable[dict[str, Any]],
        expected_statuses: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Persist a validated refiner patch atomically.

        The guard rails here are deliberately independent of :mod:`patch`, so a
        direct caller cannot bypass them:

        * only non-terminal ("active") subtasks count against the 15 item cap;
          completed history may exceed 15 as a long task accumulates results;
        * every existing item must already belong to this task;
        * completed subtask content and dependencies are immutable;
        * a finished or failed task's plan cannot be edited.

        ``expected_statuses`` guards against a concurrent task-writer changing a
        subtask between validation and persistence; a mismatch rejects the whole
        patch rather than writing a plan that no longer matches the decision.
        """
        item_list = list(items)
        # A new row is always inserted as ``created`` regardless of the status
        # carried by the in-memory item, so new items always count as active.
        active = [
            item
            for item in item_list
            if item.is_new
            or getattr(item, "status", SubtaskStatus.CREATED)
            not in TERMINAL_SUBTASK_STATUSES
        ]
        if len(active) > MAX_ACTIVE_SUBTASKS:
            raise PatchValidationError(
                f"plan would leave {len(active)} active subtasks; the limit is "
                f"{MAX_ACTIVE_SUBTASKS}"
            )
        item_ids: list[str] = []
        for item in item_list:
            if not getattr(item, "id", None):
                raise PatchValidationError("every plan item needs a stable id")
            if str(item.id) in item_ids:
                raise PatchValidationError(f"duplicate plan item id {item.id!r}")
            item_ids.append(str(item.id))
        titles = [normalize_title(item.title) for item in item_list]
        if len(set(titles)) != len(titles):
            raise PatchValidationError("plan items must have unique titles")
        operation_list = [dict(operation) for operation in operations]

        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT * FROM delegation_tasks WHERE id = %s FOR UPDATE", (task_id,)
            )
            task = cursor.fetchone()
            if task is None:
                raise DelegationError(f"task {task_id} does not exist")
            if task["status"] in (TaskStatus.FINISHED, TaskStatus.FAILED):
                raise PatchValidationError(
                    f"task {task_id} is {task['status']!r}; its plan is immutable"
                )
            cursor.execute(
                "SELECT * FROM delegation_subtasks WHERE task_id = %s FOR UPDATE",
                (task_id,),
            )
            current = {str(row["id"]): dict(row) for row in cursor.fetchall()}
            if trigger_subtask_id is not None and str(trigger_subtask_id) not in current:
                raise PatchValidationError(
                    f"trigger subtask {trigger_subtask_id} does not belong to task "
                    f"{task_id}"
                )
            for subtask_id, status in (expected_statuses or {}).items():
                row = current.get(str(subtask_id))
                if row is None:
                    raise PatchValidationError(
                        f"subtask {subtask_id} disappeared during refinement"
                    )
                if row["status"] != status:
                    raise PatchValidationError(
                        f"subtask {subtask_id} changed from {status!r} to "
                        f"{row['status']!r} during refinement"
                    )

            for item in item_list:
                if item.is_new:
                    continue
                row = current.get(str(item.id))
                if row is None:
                    raise PatchValidationError(
                        f"subtask {item.id} does not belong to task {task_id}"
                    )
                if row["status"] != SubtaskStatus.CREATED:
                    persisted_deps = [str(dep) for dep in row.get("depends_on") or []]
                    if (
                        item.title != row["title"]
                        or item.description != row["description"]
                        or item.status != row["status"]
                        or item.completion_condition != row.get("completion_condition")
                        or list(item.depends_on) != persisted_deps
                    ):
                        raise PatchValidationError(
                            f"started subtask {item.id} is immutable; a patch cannot "
                            "rewrite its title, description, status, completion "
                            "condition or dependencies"
                        )

            keep_ids = {str(item.id) for item in item_list if not item.is_new}
            for subtask_id, row in current.items():
                if subtask_id in keep_ids:
                    continue
                if row["status"] != SubtaskStatus.CREATED:
                    raise PatchValidationError(
                        f"cannot drop subtask {subtask_id} in status {row['status']!r}"
                    )
                cursor.execute(
                    "DELETE FROM delegation_subtasks WHERE id = %s AND task_id = %s",
                    (subtask_id, task_id),
                )

            # Move surviving rows out of the unique ordinal range before inserts.
            cursor.execute(
                "UPDATE delegation_subtasks SET ordinal = -ordinal WHERE task_id = %s",
                (task_id,),
            )
            real_ids: dict[str, str] = {}
            for item in item_list:
                if item.is_new or not item.id:
                    continue
                real_ids[str(item.id)] = str(item.id)
                cursor.execute(
                    """
                    UPDATE delegation_subtasks
                    SET title = %s, description = %s,
                        completion_condition = %s, depends_on = '[]'::jsonb,
                        updated_at = NOW()
                    WHERE id = %s AND task_id = %s
                    """,
                    (
                        item.title,
                        item.description,
                        item.completion_condition,
                        item.id,
                        task_id,
                    ),
                )

            new_ids: dict[str, str] = {}
            for item in item_list:
                if not item.is_new:
                    continue
                cursor.execute(
                    """
                    INSERT INTO delegation_subtasks
                        (task_id, ordinal, title, description, status, depends_on,
                         completion_condition)
                    VALUES (%s, %s, %s, %s, 'created', '[]'::jsonb, %s)
                    RETURNING id
                    """,
                    (
                        task_id,
                        -1000 - len(new_ids),
                        item.title,
                        item.description,
                        item.completion_condition,
                    ),
                )
                new_ids[str(item.id)] = str(cursor.fetchone()["id"])

            all_ids = {**real_ids, **new_ids}
            by_title = {
                normalize_title(item.title): all_ids[str(item.id)]
                for item in item_list
            }
            for ordinal, item in enumerate(item_list, start=1):
                resolved: list[str] = []
                for dep in item.depends_on:
                    if str(dep) in all_ids:
                        resolved.append(all_ids[str(dep)])
                        continue
                    title_target = by_title.get(normalize_title(str(dep)))
                    if title_target is None:
                        raise PatchValidationError(
                            f"subtask {item.title!r} depends on unknown subtask {dep!r}"
                        )
                    resolved.append(title_target)
                cursor.execute(
                    """
                    UPDATE delegation_subtasks
                    SET ordinal = %s, depends_on = %s, updated_at = NOW()
                    WHERE id = %s AND task_id = %s
                    """,
                    (ordinal, Json(resolved), all_ids[str(item.id)], task_id),
                )

            cursor.execute(
                """
                INSERT INTO delegation_patches
                    (task_id, trigger_subtask_id, rationale, operations)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (
                    task_id,
                    trigger_subtask_id,
                    rationale,
                    Json(operation_list),
                ),
            )
            patch_row = dict(cursor.fetchone())
            cursor.execute(
                "SELECT * FROM delegation_subtasks WHERE task_id = %s ORDER BY ordinal",
                (task_id,),
            )
            return {
                "patch": patch_row,
                "subtasks": [dict(row) for row in cursor.fetchall()],
            }

    def find_patches(self, task_id: str) -> list[dict[str, Any]]:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                """
                SELECT * FROM delegation_patches
                WHERE task_id = %s ORDER BY created_at, id
                """,
                (task_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ----- reports -----

    def save_report(self, task_id: str, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert the one report for a task; a replay returns the first report."""
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO delegation_reports (task_id, body)
                VALUES (%s, %s)
                ON CONFLICT (task_id) DO NOTHING
                RETURNING *
                """,
                (task_id, Json(body)),
            )
            row = cursor.fetchone()
            if row is not None:
                return dict(row), True
            cursor.execute(
                "SELECT * FROM delegation_reports WHERE task_id = %s", (task_id,)
            )
            return dict(cursor.fetchone()), False

    def find_report(self, task_id: str) -> dict[str, Any] | None:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                "SELECT * FROM delegation_reports WHERE task_id = %s", (task_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # ----- memory -----

    def engagement_tenant(self, engagement_id: str) -> str | None:
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            cursor.execute(
                "SELECT org_id FROM engagements WHERE id = %s", (engagement_id,)
            )
            row = cursor.fetchone()
            return str(row["org_id"]) if row and row["org_id"] else None

    def add_memory(
        self,
        engagement_id: str,
        summary: str,
        *,
        tenant_id: str | None,
        kind: str = "fact",
    ) -> dict[str, Any]:
        """Store redacted memory only under the engagement's own tenant."""
        if not summary or not summary.strip():
            raise DelegationError("memory summary is required")
        with self.db_operation(cursor_factory=RealDictCursor) as (_conn, cursor):
            cursor.execute(
                "SELECT org_id FROM engagements WHERE id = %s", (engagement_id,)
            )
            engagement = cursor.fetchone()
            if engagement is None:
                raise DelegationError(f"engagement {engagement_id} does not exist")
            owner = str(engagement["org_id"]) if engagement["org_id"] else None
            if owner is None:
                raise DelegationError(
                    f"engagement {engagement_id} has no tenant; unscoped memory "
                    "could never be returned"
                )
            if tenant_id is not None and str(tenant_id) != owner:
                raise DelegationError(
                    f"engagement {engagement_id} belongs to tenant {owner}, not "
                    f"{tenant_id}"
                )
            cursor.execute(
                """
                INSERT INTO delegation_memory
                    (engagement_id, tenant_id, kind, summary, redacted)
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING *
                """,
                (engagement_id, owner, kind, summary.strip()),
            )
            return dict(cursor.fetchone())

    def search_memory(
        self,
        tenant_id: str,
        *,
        query: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return redacted knowledge for one tenant only (P-16)."""
        if not tenant_id:
            return []
        with self.db_operation(commit=False, cursor_factory=RealDictCursor) as (
            _conn,
            cursor,
        ):
            params: list[Any] = [tenant_id]
            sql = """
                SELECT * FROM delegation_memory
                WHERE tenant_id = %s AND redacted = TRUE
            """
            if query:
                sql += " AND summary ILIKE %s"
                params.append(f"%{query}%")
            sql += " ORDER BY created_at DESC, id LIMIT %s"
            params.append(max(1, int(limit)))
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

__all__ = ["PostgresDelegationStore"]

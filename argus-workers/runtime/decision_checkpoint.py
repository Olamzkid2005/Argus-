"""
DecisionCheckpoint — Replay-safe decision persistence.

Every agent decision is persisted as a DecisionCheckpoint so that Celery
retries replay the original LLM decision rather than re-prompting the model.

Retry Rules:
1. Retries MUST replay the original decision — never re-prompt the LLM.
2. Only failed execution is replayed; reasoning state remains frozen.
3. Agent re-planning only occurs AFTER execution completion, timeout,
   or fatal failure.
"""

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DecisionCheckpoint:
    """Persistent record of a single agent decision."""

    action_id: str
    observation_hash: str
    reasoning_hash: str
    selected_tool: str
    arguments: dict
    timestamp: float
    state_version: int
    tool_cost_usd: float = 0.0
    engagement_id: str = ""
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_success: bool | None = None
    execution_error: str = ""

    @staticmethod
    def compute_hash(data: str) -> str:
        """Compute a stable hash of string data."""
        return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_action(
        cls,
        action: Any,
        observation_context: str,
        reasoning: str,
        state_version: int,
        engagement_id: str = "",
    ) -> "DecisionCheckpoint":
        """Create a checkpoint from an AgentAction and current context."""
        return cls(
            action_id=getattr(action, "action_id", str(uuid.uuid4())),
            observation_hash=cls.compute_hash(observation_context),
            reasoning_hash=cls.compute_hash(reasoning),
            selected_tool=action.tool if hasattr(action, "tool") else str(action),
            arguments=action.arguments if hasattr(action, "arguments") else {},
            timestamp=time.time(),
            state_version=state_version,
            tool_cost_usd=getattr(action, "cost_usd", 0.0),
            engagement_id=engagement_id,
        )

    def to_dict(self) -> dict:
        """Serialize to dict for DB storage."""
        d = asdict(self)
        d["arguments"] = json.dumps(d["arguments"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionCheckpoint":
        """Deserialize from a DB row dict."""
        data = dict(d)
        if isinstance(data.get("arguments"), str):
            try:
                data["arguments"] = json.loads(data["arguments"])
            except (json.JSONDecodeError, TypeError):
                data["arguments"] = {}
        return cls(**data)


class DecisionCheckpointRepository:
    """Persists and retrieves DecisionCheckpoints from the database."""

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string

    def save(self, checkpoint: DecisionCheckpoint) -> bool:
        """Persist a checkpoint to the decision_snapshots table."""
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_decision_log
                        (id, engagement_id, action_id, observation_hash,
                         reasoning_hash, selected_tool, arguments,
                         tool_cost_usd, state_version, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        execution_success = EXCLUDED.execution_success,
                        execution_error = EXCLUDED.execution_error
                    """,
                    (
                        checkpoint.checkpoint_id,
                        checkpoint.engagement_id,
                        checkpoint.action_id,
                        checkpoint.observation_hash,
                        checkpoint.reasoning_hash,
                        checkpoint.selected_tool,
                        json.dumps(checkpoint.arguments),
                        checkpoint.tool_cost_usd,
                        checkpoint.state_version,
                    ),
                )
            return True
        except Exception as e:
            logger.warning("Failed to save DecisionCheckpoint: %s", e)
            return False

    def get_by_action_id(self, action_id: str) -> DecisionCheckpoint | None:
        """Retrieve a checkpoint by action_id."""
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT checkpoint_id, engagement_id, action_id,
                           observation_hash, reasoning_hash, selected_tool,
                           arguments, tool_cost_usd, state_version,
                           created_at, execution_success, execution_error
                    FROM agent_decision_log
                    WHERE action_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (action_id,),
                )
                row = cursor.fetchone()
                if row:
                    cols = [
                        "checkpoint_id", "engagement_id", "action_id",
                        "observation_hash", "reasoning_hash", "selected_tool",
                        "arguments", "tool_cost_usd", "state_version",
                        "created_at", "execution_success", "execution_error",
                    ]
                    return DecisionCheckpoint.from_dict(dict(zip(cols, row, strict=False)))
        except Exception as e:
            logger.warning("Failed to load DecisionCheckpoint: %s", e)
        return None

    def get_latest_for_engagement(
        self, engagement_id: str, limit: int = 20
    ) -> list[DecisionCheckpoint]:
        """Get the most recent checkpoints for an engagement."""
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT checkpoint_id, engagement_id, action_id,
                           observation_hash, reasoning_hash, selected_tool,
                           arguments, tool_cost_usd, state_version,
                           created_at, execution_success, execution_error
                    FROM agent_decision_log
                    WHERE engagement_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (engagement_id, limit),
                )
                cols = [
                    "checkpoint_id", "engagement_id", "action_id",
                    "observation_hash", "reasoning_hash", "selected_tool",
                    "arguments", "tool_cost_usd", "state_version",
                    "created_at", "execution_success", "execution_error",
                ]
                return [
                    DecisionCheckpoint.from_dict(dict(zip(cols, row, strict=False)))
                    for row in cursor.fetchall()
                ]
        except Exception as e:
            logger.warning("Failed to load checkpoints for engagement: %s", e)
        return []

    def mark_execution_result(
        self, checkpoint_id: str, success: bool, error: str = ""
    ) -> bool:
        """Mark a checkpoint's execution as success or failure."""
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_decision_log
                    SET execution_success = %s, execution_error = %s
                    WHERE checkpoint_id = %s
                    """,
                    (success, error[:500], checkpoint_id),
                )
            return True
        except Exception as e:
            logger.warning("Failed to mark checkpoint result: %s", e)
            return False

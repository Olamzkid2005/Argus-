"""Hierarchical task delegation (plan §4, P-01…P-17).

Modules:

* :mod:`models` — Flow/Task/Subtask/Action contracts and status transitions
* :mod:`generator` — ordered plan validation, dedupe and the 15-subtask cap
* :mod:`store` — durable hierarchy persistence owned by the delegation service
* :mod:`patch` — deterministic ADD/REMOVE/MODIFY/REORDER semantics
* :mod:`refiner` — post-subtask refinement request and persistence
* :mod:`reflector` — bounded repair of unstructured output (max 3)
* :mod:`primary` — Primary Agent and bounded specialist delegation
* :mod:`registry` — specialist roles and capabilities
* :mod:`reporter` — one task report from persisted results/evidence
* :mod:`memorist` — redacted, tenant-scoped knowledge
* :mod:`tool_executor` — production executor on the real tool/scope/budget/approval layer
* :mod:`worker` — sequential TaskWorker, waiting and restart reconciliation
"""

from agent.delegation.generator import (
    GeneratedPlan,
    is_duplicate,
    normalize_title,
    validate_generated_plan,
)
from agent.delegation.memorist import Memorist, redact_secrets
from agent.delegation.models import (
    MAX_ACTIVE_SUBTASKS,
    Action,
    DelegationError,
    InvalidTransition,
    PatchValidationError,
    PlanValidationError,
    ReflectionExhausted,
    Subtask,
    SubtaskDraft,
    SubtaskStatus,
    Task,
    TaskCompletionError,
    TaskStatus,
)
from agent.delegation.patch import PlanItem, apply_patch, plan_items
from agent.delegation.primary import PrimaryAgent, SpecialistRequest, SpecialistResult
from agent.delegation.refiner import RefinerService
from agent.delegation.reflector import Reflector
from agent.delegation.registry import Specialist, SpecialistRegistry
from agent.delegation.reporter import Reporter
from agent.delegation.store import PostgresDelegationStore
from agent.delegation.tool_executor import (
    HIGH_IMPACT_TOOLS,
    RealToolExecutor,
    ToolCallSpecialistRunner,
    default_specialist_registry,
    extract_tool_findings,
    parse_eslint_json,
    parse_semgrep_json,
    tool_runner_factory,
    validate_approval,
)
from agent.delegation.worker import TaskWorker

__all__ = [
    "MAX_ACTIVE_SUBTASKS",
    "Action",
    "DelegationError",
    "GeneratedPlan",
    "HIGH_IMPACT_TOOLS",
    "InvalidTransition",
    "Memorist",
    "PatchValidationError",
    "PlanItem",
    "PlanValidationError",
    "PostgresDelegationStore",
    "PrimaryAgent",
    "RefinerService",
    "ReflectionExhausted",
    "Reflector",
    "Reporter",
    "RealToolExecutor",
    "Specialist",
    "SpecialistRegistry",
    "SpecialistRequest",
    "SpecialistResult",
    "Subtask",
    "SubtaskDraft",
    "SubtaskStatus",
    "Task",
    "TaskCompletionError",
    "TaskStatus",
    "TaskWorker",
    "ToolCallSpecialistRunner",
    "apply_patch",
    "default_specialist_registry",
    "extract_tool_findings",
    "is_duplicate",
    "normalize_title",
    "parse_eslint_json",
    "parse_semgrep_json",
    "plan_items",
    "redact_secrets",
    "tool_runner_factory",
    "validate_approval",
    "validate_generated_plan",
]

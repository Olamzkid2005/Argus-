"""Ordered subtask generation: validation, deduplication and deterministic order.

The Generator Agent itself only proposes text. This module is the dispatcher-side
contract that decides what may be persisted (plan §4.5):

* 1–15 subtasks per task, with an explicit over-limit policy;
* dependency references validated and topologically ordered, so a plan that
  arrives unordered is stored in one deterministic valid order;
* rephrased duplicates of existing subtasks suppressed by stable task-local
  identity plus token similarity, not title equality alone.
"""

from __future__ import annotations

import heapq
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from agent.delegation.models import (
    MAX_ACTIVE_SUBTASKS,
    PlanValidationError,
    SubtaskDraft,
)

#: Over-limit policy: ``reject`` fails the generation, ``clamp`` keeps the first
#: ``max_subtasks`` items. Both guarantee no more than 15 are persisted.
OVER_LIMIT_POLICIES = ("reject", "clamp")

_WORD_RE = re.compile(r"[a-z0-9]+")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")

#: Jaccard similarity at or above which two subtask titles are the same work.
DUPLICATE_SIMILARITY = 0.85


@dataclass(frozen=True)
class GeneratedPlan:
    """A validated plan, ordered for execution."""

    drafts: tuple[SubtaskDraft, ...]
    dropped_duplicates: tuple[str, ...] = ()
    clamped: bool = False

    def __len__(self) -> int:
        return len(self.drafts)


def normalize_title(title: str) -> str:
    """Normalise a title into a stable comparison key."""
    return " ".join(_PUNCT_RE.sub(" ", str(title or "").lower()).split())


def _tokens(title: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(normalize_title(title)))


def _similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def is_duplicate(title: str, existing_titles: Iterable[str]) -> bool:
    """True when *title* names work that already exists (title or near-title)."""
    normalized = normalize_title(title)
    if not normalized:
        return False
    for existing in existing_titles:
        if normalize_title(existing) == normalized:
            return True
        if _similarity(title, existing) >= DUPLICATE_SIMILARITY:
            return True
    return False


def _raw_items(raw: Any) -> list[Any]:
    if isinstance(raw, dict):
        for key in ("subtasks", "plan", "steps"):
            if key in raw:
                return list(raw[key] or [])
        raise PlanValidationError("generator output object has no subtasks list")
    if isinstance(raw, (list, tuple)):
        return list(raw)
    raise PlanValidationError("generator output must be a list or an object with 'subtasks'")


def _coerce_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"subtask {key!r} must be a non-empty string")
    return value.strip()


def _coerce_dependencies(item: dict[str, Any], index: int) -> list[str | int]:
    raw = item.get("depends_on", item.get("dependencies", []))
    if raw is None:
        return []
    if isinstance(raw, (str, int)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise PlanValidationError(
            f"subtask {index} dependencies must be a list, got {type(raw).__name__}"
        )
    dependencies: list[str | int] = []
    for ref in raw:
        if isinstance(ref, bool) or not isinstance(ref, (str, int)):
            raise PlanValidationError(
                f"subtask {index} dependency {ref!r} must be a title or an index"
            )
        dependencies.append(ref)
    return dependencies


def _topological_order(dependencies: list[set[int]], original_index: list[int]) -> list[int]:
    """Stable topological sort over dependencies.

    Dependencies may point at later drafts, which is exactly the unordered case
    P-03 requires the dispatcher to repair. Ties are broken by the generator's
    original position so the stored order is deterministic.
    """
    size = len(dependencies)
    children: list[list[int]] = [[] for _ in range(size)]
    indegree = [0] * size
    for node, deps in enumerate(dependencies):
        indegree[node] = len(deps)
        for dep in deps:
            children[dep].append(node)

    ready = [(original_index[node], node) for node in range(size) if indegree[node] == 0]
    heapq.heapify(ready)
    ordered: list[int] = []
    while ready:
        _, node = heapq.heappop(ready)
        ordered.append(node)
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, (original_index[child], child))
    if len(ordered) != size:
        raise PlanValidationError("subtask dependencies contain a cycle")
    return ordered


def _resolve_reference(
    ref: str | int,
    title_positions: dict[str, int],
    titles: list[str],
    size: int,
) -> int:
    """Resolve a dependency reference to a kept draft position.

    Integers are 1-based positions in the generator's output; strings are
    subtask titles. A reference to a draft that deduplication removed resolves
    to the surviving duplicate with the same title. A reference to a draft that
    the over-limit policy removed is an error: silently dropping a prerequisite
    would let its dependent run without it.
    """
    if isinstance(ref, int) and not isinstance(ref, bool):
        if not 1 <= ref <= size:
            raise PlanValidationError(f"dependency index {ref!r} is outside the plan")
        original = ref - 1
        position = title_positions.get(f"#index:{original}")
        if position is not None:
            return position
        position = title_positions.get(normalize_title(titles[original]))
        if position is not None:
            return position
        raise PlanValidationError(
            f"dependency index {ref!r} points at a subtask removed by the "
            "over-limit policy; raise the limit or drop the dependency"
        )
    key = normalize_title(str(ref))
    if key in title_positions:
        return title_positions[key]
    raise PlanValidationError(f"dependency {ref!r} does not name a subtask in the plan")


def validate_generated_plan(
    raw: Any,
    *,
    existing_titles: Iterable[str] = (),
    max_subtasks: int = MAX_ACTIVE_SUBTASKS,
    over_limit: str = "reject",
) -> GeneratedPlan:
    """Validate one Generator response into an execution-ordered plan.

    Raises :class:`PlanValidationError` for malformed output, a cycle, an
    unknown dependency, an empty plan, or an over-limit plan under the
    ``reject`` policy. Anything that survives is safe to persist as-is.
    """
    if over_limit not in OVER_LIMIT_POLICIES:
        raise PlanValidationError(
            f"over_limit must be one of {OVER_LIMIT_POLICIES}, got {over_limit!r}"
        )
    items = _raw_items(raw)
    if not items:
        raise PlanValidationError(
            "generator returned an empty plan; that is a generation failure unless "
            "the task is already proven complete"
        )

    # 1. Parse every draft first so dependency indices always refer to the
    #    generator's original output, not to the deduplicated list.
    parsed: list[tuple[str, str, str | None, list[str | int]]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanValidationError(f"subtask {index} must be an object")
        parsed.append(
            (
                _coerce_text(item, "title"),
                _coerce_text(item, "description"),
                item.get("completion_condition"),
                _coerce_dependencies(item, index),
            )
        )

    # 2. Deduplicate against existing work and within the plan.
    dropped: list[str] = []
    seen_titles = list(existing_titles)
    kept_original_indices: list[int] = []
    for index, (title, _description, _condition, _refs) in enumerate(parsed):
        if is_duplicate(title, seen_titles):
            dropped.append(title)
            continue
        kept_original_indices.append(index)
        seen_titles.append(title)

    if not kept_original_indices:
        raise PlanValidationError(
            "generator returned only duplicates of existing subtasks; no new work to persist"
        )

    clamped = False
    if len(kept_original_indices) > max_subtasks:
        if over_limit == "reject":
            raise PlanValidationError(
                f"generator returned {len(kept_original_indices)} subtasks; "
                f"the limit is {max_subtasks}"
            )
        clamped = True
        kept_original_indices = kept_original_indices[:max_subtasks]

    # 3. Map every kept draft to its final position and resolve references.
    title_positions: dict[str, int] = {}
    for position, original in enumerate(kept_original_indices):
        title = parsed[original][0]
        title_positions[normalize_title(title)] = position
        title_positions[f"#index:{original}"] = position

    dependencies: list[set[int]] = []
    for position, original in enumerate(kept_original_indices):
        deps: set[int] = set()
        for ref in parsed[original][3]:
            resolved = _resolve_reference(
                ref, title_positions, [item[0] for item in parsed], len(parsed)
            )
            if resolved == position:
                raise PlanValidationError("a subtask cannot depend on itself")
            deps.add(resolved)
        dependencies.append(deps)

    # 4. Deterministic topological order: dependencies first, ties keep the
    #    generator's original position.
    ordered_positions = _topological_order(dependencies, list(range(len(kept_original_indices))))

    ordered_drafts = tuple(
        SubtaskDraft(
            title=parsed[kept_original_indices[position]][0],
            description=parsed[kept_original_indices[position]][1],
            depends_on=tuple(
                sorted(
                    normalize_title(parsed[kept_original_indices[dep]][0])
                    for dep in dependencies[position]
                )
            ),
            completion_condition=parsed[kept_original_indices[position]][2],
        )
        for position in ordered_positions
    )
    return GeneratedPlan(
        drafts=ordered_drafts,
        dropped_duplicates=tuple(dropped),
        clamped=clamped,
    )


@dataclass
class RecordingGenerator:
    """Test/support adapter: a Generator Agent backed by a fixed response."""

    response: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, request: dict[str, Any]) -> Any:
        self.calls.append(request)
        return self.response

"""Deterministic worker-capacity selection for the control plane.

Selection order is the reference dispatcher's: task-type support, capacity, health, temporary
rejection, then priority, running count, an already-warm engagement environment,
and a deterministic tie-break (an injected RNG stands in for the reference
dispatcher's randomized exact ties).
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class WorkerView:
    worker_id: str
    task_types: frozenset[str]
    max_running: int = 1
    running: int = 0
    priority: int = 0
    healthy: bool = True
    unavailable_until: datetime | None = None
    warm: bool = False


def _eligible(
    worker: WorkerView,
    task_type: str,
    now: datetime,
    excluded: set[str],
) -> bool:
    if worker.worker_id in excluded:
        return False
    if task_type not in worker.task_types:
        return False
    if worker.running >= worker.max_running:
        return False
    if not worker.healthy:
        return False
    return not (
        worker.unavailable_until is not None and worker.unavailable_until > now
    )


def choose_worker(
    candidates: Iterable[WorkerView],
    task_type: str,
    *,
    now: datetime | None = None,
    excluded: Iterable[str] = (),
    rng: random.Random | None = None,
) -> WorkerView | None:
    """Return the best eligible worker, or None when the scheduler must wait."""
    current = now or datetime.now(UTC)
    exclusions = set(excluded)
    available = [
        worker
        for worker in candidates
        if _eligible(worker, task_type, current, exclusions)
    ]
    if not available:
        return None
    random_source = rng or random.Random(0)
    tie = {worker.worker_id: random_source.random() for worker in available}
    available.sort(
        key=lambda worker: (
            worker.priority,
            worker.running,
            0 if worker.warm else 1,
            tie[worker.worker_id],
        )
    )
    return available[0]


def global_capacity_available(
    candidates: Iterable[WorkerView], *, max_global_running: int | None
) -> bool:
    """Whether the fleet has any free slot under the global worker limit."""
    if max_global_running is None:
        return True
    return sum(worker.running for worker in candidates) < max_global_running

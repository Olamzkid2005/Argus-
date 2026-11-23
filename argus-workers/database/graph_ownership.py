"""
C-18 dispatcher graph ownership.

Two guarantees, both enforced in code rather than by convention:

1. Runtime gate: every mutating ``ExplorationGraphRepository`` method calls
   :func:`require_graph_write_owner`, which only succeeds inside
   :func:`dispatcher_write_scope`. ``DispatcherGraph`` opens that scope around
   its own mutations, so worker/agent code cannot commit graph state even if it
   somehow obtains a repository instance.
2. Static boundary: :func:`find_import_boundary_violations` reports modules that
   import the graph write surface outside the dispatcher-owned allowlist. CI runs
   ``scripts/check_graph_import_boundary.py`` so a new direct import fails the
   build instead of quietly bypassing the dispatcher.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from pathlib import Path

OWNERSHIP_VIOLATION_MESSAGE = (
    "graph mutations are dispatcher-owned (C-18): call them through DispatcherGraph; "
    "workers/agents must return structured output instead of writing graph state"
)


class GraphOwnershipError(RuntimeError):
    """A graph mutation was attempted outside the dispatcher-owned surface."""


_ACTIVE_WRITE_OWNER: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "argus_graph_write_owner", default=None
)


@contextmanager
def dispatcher_write_scope(owner: str = "dispatcher"):
    """Mark the current context as a dispatcher-owned graph write."""
    token = _ACTIVE_WRITE_OWNER.set(owner)
    try:
        yield owner
    finally:
        _ACTIVE_WRITE_OWNER.reset(token)


def require_graph_write_owner(operation: str) -> str:
    """
    Return the active write owner or raise :class:`GraphOwnershipError`.

    Called by every repository mutation so the ownership boundary is a runtime
    property, not a naming convention.
    """
    owner = _ACTIVE_WRITE_OWNER.get()
    if owner is None:
        raise GraphOwnershipError(f"{operation}: {OWNERSHIP_VIOLATION_MESSAGE}")
    return owner


# ---------------------------------------------------------------------------
# Static import boundary
# ---------------------------------------------------------------------------

_GRAPH_WRITE_MODULES = ("graph_repository", "dispatcher_graph", "graph_ingest")

_IMPORT_PATTERNS = tuple(
    re.compile(pattern, re.MULTILINE)
    for pattern in (
        rf"^\s*from\s+database\.(?:{'|'.join(_GRAPH_WRITE_MODULES)})\b",
        rf"^\s*import\s+database\.(?:{'|'.join(_GRAPH_WRITE_MODULES)})\b",
        rf"^\s*from\s+database\s+import\s+[^\n]*\b(?:{'|'.join(_GRAPH_WRITE_MODULES)})\b",
    )
)

# Modules allowed to reference the write surface: the surface itself, its
# ingestion/identity helpers, and the tests that prove the dispatcher path.
_ALLOWED_REFERENCES = frozenset(
    {
        "database/dispatcher_graph.py",
        "database/graph_ingest.py",
        "database/graph_identity.py",
        "database/graph_ownership.py",
        "database/graph_repository.py",
        # Trusted recon bridge: delegates every write to DispatcherGraph rather
        # than committing graph state itself.
        "tasks/graph_ingestion.py",
    }
)

_SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", "tests"}
)


def find_import_boundary_violations(root: str | Path) -> list[str]:
    """
    Return relative paths of modules that import the graph write surface.

    Test modules are excluded: the dispatcher path is what they prove. Every
    other module in the workers tree has to go through ``DispatcherGraph``.
    """
    root_path = Path(root)
    violations: list[str] = []
    for path in sorted(root_path.rglob("*.py")):
        relative = path.relative_to(root_path)
        if relative.as_posix() in _ALLOWED_REFERENCES:
            continue
        if any(part in _SKIP_DIRECTORIES for part in relative.parts[:-1]):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(pattern.search(text) for pattern in _IMPORT_PATTERNS):
            violations.append(relative.as_posix())
    return violations

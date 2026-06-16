"""
tool_core/validators/scope.py — Scope validation facade.

Re-exports from ``tools/scope_validator`` — the canonical implementation.
During migration, implementations move into ``tool_core`` as old code is removed.
"""

from tools.scope_validator import (  # noqa: F401 — re-export for migration
    ScopeValidator,
    ScopeViolationError,
    validate_target_scope,
)

__all__ = ["ScopeValidator", "ScopeViolationError", "validate_target_scope"]

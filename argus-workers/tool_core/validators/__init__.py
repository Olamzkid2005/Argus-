"""tool_core.validators — Scope and argument validation facades."""

from tool_core.validators.args import is_dangerous
from tool_core.validators.scope import ScopeValidator, validate_target_scope

__all__ = ["ScopeValidator", "validate_target_scope", "is_dangerous"]

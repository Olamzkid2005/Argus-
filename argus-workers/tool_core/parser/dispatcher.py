"""
tool_core/parser/dispatcher.py — Parser dispatcher facade.

Re-exports ``Parser`` from ``parsers/parser`` — the canonical implementation.
"""

from parsers.parser import Parser  # noqa: F401 — re-export for migration

__all__ = ["Parser"]

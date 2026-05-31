"""
tool_core/parser/normalizer.py — Finding normalizer facade.

Re-exports ``FindingNormalizer`` from ``parsers/normalizer`` — the canonical implementation.
"""

from parsers.normalizer import FindingNormalizer  # noqa: F401 — re-export for migration

__all__ = ["FindingNormalizer"]

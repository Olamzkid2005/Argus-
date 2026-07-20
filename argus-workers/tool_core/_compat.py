"""
Python version compatibility shims.

The project targets Python 3.11 (see pyproject.toml), but the development
environment may run Python 3.10. This module provides backports for features
added in Python 3.11:

- ``StrEnum`` (PEP 663, Python 3.11+): String enum base class.
- ``datetime.UTC`` (PEP 615, Python 3.11+): UTC timezone singleton.

Usage:
    from tool_core._compat import StrEnum, utc
    from datetime import datetime

    class MyEnum(StrEnum):
        FOO = "foo"

    now = datetime.now(utc)
"""


# ── datetime.UTC compat (Python 3.11+) ──────────────────────────────────────
# `datetime.UTC` was added in Python 3.11 as a convenience alias for
# `datetime.timezone.utc`. Provide it when running on 3.10.
from datetime import UTC as utc  # type: ignore[assignment]

# Re-export as UTC for compatibility with ``from datetime import UTC`` pattern.
# Files that used ``from datetime import UTC`` can use:
#   from tool_core._compat import UTC as utc
# or update their import to use ``utc`` directly.
UTC = utc  # noqa: F811

# ── StrEnum compat (Python 3.11+) ───────────────────────────────────────────
# `enum.StrEnum` was added in Python 3.11 (PEP 663). On 3.10, create a
# drop-in replacement by combining ``str`` and ``enum.Enum``.


# ── StrEnum compat (Python 3.11+) ───────────────────────────────────────────
# `enum.StrEnum` was added in Python 3.11 (PEP 663). On 3.10, create a
# drop-in replacement by combining ``str`` and ``enum.Enum``.
try:
    from enum import StrEnum  # type: ignore[no-redef]
except ImportError:
    import enum

    class StrEnum(str, enum.Enum):  # type: ignore[no-redef]
        """Backport of Python 3.11's ``enum.StrEnum``."""

        def __new__(cls, value: str) -> "StrEnum":
            member = str.__new__(cls, value)
            member._value_ = value
            return member


# ── NotRequired compat (Python 3.11+) ───────────────────────────────────────
# ``typing.NotRequired`` was added in Python 3.11 (PEP 655). On 3.10 it is
# available from the ``typing_extensions`` third-party package.
try:
    from typing import NotRequired  # type: ignore[no-redef]
except ImportError:
    pass  # type: ignore[no-redef,assignment]

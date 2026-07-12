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

import sys
from datetime import timezone

# ── datetime.UTC compat (Python 3.11+) ──────────────────────────────────────
# `datetime.UTC` was added in Python 3.11 as a convenience alias for
# `datetime.timezone.utc`. Provide it when running on 3.10.
if sys.version_info >= (3, 11):
    from datetime import UTC as utc  # noqa: F811
else:
    utc = timezone.utc  # type: ignore[assignment]


# Re-export as UTC for compatibility with ``from datetime import UTC`` pattern.
# Files that used ``from datetime import UTC`` can use:
#   from tool_core._compat import UTC as utc
# or update their import to use ``utc`` directly.
UTC = utc  # noqa: F811

# ── StrEnum compat (Python 3.11+) ───────────────────────────────────────────
# `enum.StrEnum` was added in Python 3.11 (PEP 663). On 3.10, create a
# drop-in replacement by combining ``str`` and ``enum.Enum``.
if sys.version_info >= (3, 11):
    from enum import StrEnum  # noqa: F811
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of Python 3.11's ``enum.StrEnum``.

        A string enum that serializes values as their string value.
        All standard ``Enum`` features (auto(), aliases, members, etc.)
        work as expected.

        Example::

            class Status(StrEnum):
                OK = "ok"
                ERROR = "error"

            assert Status.OK == "ok"
            assert str(Status.OK) == "ok"
        """

        def __str__(self) -> str:
            return self.value

        @staticmethod
        def _generate_next_value_(
            name: str, start: int, count: int, last_values: list[str]
        ) -> str:
            """Default to lowercase name when using ``auto()``."""
            return name.lower()

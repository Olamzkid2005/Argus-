# Python Version Compatibility

## Overview

The `argus-workers` project **targets Python 3.11** for production (see `pyproject.toml`), but the development environment may run **Python 3.10**. This document describes the compatibility strategy, the available shims, and how to add new ones.

## Version Gaps

| Feature | Python 3.11 | Python 3.10 | Backport? |
|---------|-------------|-------------|-----------|
| `enum.StrEnum` (PEP 663) | Built-in | Missing | `tool_core._compat.StrEnum` |
| `datetime.UTC` (PEP 615) | Built-in | Missing | `tool_core._compat.utc` / `UTC` |
| `typing.NotRequired` (PEP 655) | Built-in | `typing_extensions.NotRequired` | `tool_core._compat.NotRequired` |
| `ExceptionGroup` / `except*` (PEP 654) | Built-in | Missing | Not yet shimmed |
| `Self` (PEP 673) | Built-in | `typing_extensions.Self` | Not yet shimmed |

## Compat Module

All compatibility shims live in **`argus-workers/tool_core/_compat.py`**. Usage:

```python
from tool_core._compat import StrEnum, NotRequired, utc
```

### StrEnum (PEP 663)

Python 3.11 added `enum.StrEnum` — a string enum whose values serialise as their string value. On 3.10 we build it from `str` + `enum.Enum`.

```python
from tool_core._compat import StrEnum

class Status(StrEnum):
    OK = "ok"
    ERROR = "error"

assert Status.OK == "ok"
assert str(Status.OK) == "ok"
```

### datetime.UTC (PEP 615)

Python 3.11 added `datetime.UTC` as a convenience alias for `datetime.timezone.utc`.

```python
from tool_core._compat import utc, UTC
from datetime import datetime

now = datetime.now(utc)
# or
from tool_core._compat import UTC as utc
```

### NotRequired (PEP 655)

Python 3.11 added `typing.NotRequired` for `TypedDict` total=False fields. On 3.10 it falls back to `typing_extensions.NotRequired`.

```python
from tool_core._compat import NotRequired
from typing import TypedDict

class MyDict(TypedDict):
    required_field: str
    optional_field: NotRequired[str | None]
```

## Adding a New Compat Shim

1. Check if the feature exists in Python 3.11 but not 3.10
2. Open `tool_core/_compat.py`
3. Add a new section following the existing pattern:
   - `try/except ImportError` if a backport package exists (like `typing_extensions`)
   - `if/else sys.version_info` check if a custom implementation is needed (like `StrEnum`)
4. Add the import to the module docstring
5. Update this document

## Dependency Requirements

| File | Contents | Purpose |
|------|----------|---------|
| `requirements.txt` | Production runtime deps | Celery, Redis, HTTP clients, DB driver, LLM SDKs, security tools |
| `requirements-dev.txt` | Test-only deps | pytest, flask (test fixtures) |

### Notes

- `typing-extensions` is required for `NotRequired` on Python 3.10. It is installed automatically by `playwright` or can be installed explicitly.
- `playwright` (~400MB with browser binaries) is intentionally excluded from production images. See `requirements.txt` comment.
- `opentelemetry-*` packages are required for tracing but can be stubbed out in minimal environments.

## Production vs Development

| Concern | Production (3.11) | Development (3.10) |
|---------|------------------|--------------------|
| `tool_core._compat` feature check | All use builtins | Falls back to compat shims |
| `pyproject.toml` target | `py311` | Same file; lints/type-checks against 3.11 |
| Full test suite | 4,061 tests | Same (with `compat` shims) |
| Skipped tests | 0 | 0 (after all deps installed) |

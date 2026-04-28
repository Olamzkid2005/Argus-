"""
Result type for explicit error propagation.

A discriminated union pattern that makes error handling explicit.
Instead of raising exceptions deep in the call stack, functions return
Result objects that callers must unpack, making error paths visible.

Stolen from: Shannon's apps/worker/src/types/result.ts
Adapted to Python with full type safety via generics.
"""

from __future__ import annotations

import dataclasses
from typing import (
    Generic,
    TypeVar,
    Union,
    final,
)
from types import TracebackType

T = TypeVar("T", covariant=True)
E = TypeVar("E", covariant=True)


@final
@dataclasses.dataclass(frozen=True)
class Ok(Generic[T]):
    """Success variant of Result."""

    value: T


@final
@dataclasses.dataclass(frozen=True)
class Err(Generic[E]):
    """Error variant of Result."""

    error: E


Result = Union[Ok[T], Err[E]]
"""
Result type — either Ok[T] with a value or Err[E] with an error.

Usage:
    def divide(a: int, b: int) -> Result[float, str]:
        if b == 0:
            return Err("division by zero")
        return Ok(a / b)

    result = divide(10, 2)
    if is_ok(result):
        print(result.value)
    else:
        print(result.error)
"""


def ok(value: T) -> Ok[T]:
    """Create a success Result."""
    return Ok(value)


def err(error: E) -> Err[E]:
    """Create an error Result."""
    return Err(error)


def is_ok(result: Result[T, E]) -> bool:
    """Check if a Result is the Ok variant."""
    return isinstance(result, Ok)


def is_err(result: Result[T, E]) -> bool:
    """Check if a Result is the Err variant."""
    return isinstance(result, Err)


def unwrap(result: Result[T, E]) -> T:
    """Unwrap a Result, raising the error if it's an Err variant.

    Args:
        result: A Result to unwrap.

    Returns:
        The inner value if Ok.

    Raises:
        The inner error if Err.
    """
    if is_ok(result):
        return result.value
    raise result.error  # type: ignore[misc]


def unwrap_or(result: Result[T, E], default: T) -> T:
    """Unwrap a Result, returning a default value on Err.

    Args:
        result: A Result to unwrap.
        default: Value to return if Err.

    Returns:
        The inner value if Ok, otherwise the default.
    """
    if is_ok(result):
        return result.value
    return default

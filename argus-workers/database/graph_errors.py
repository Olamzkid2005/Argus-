"""Graph error types shared by the repository, dispatcher and claim protocol.

They live here so the claim primitives can raise them without importing the
repository (which imports the claim primitives).
"""

from __future__ import annotations


class GraphMutationError(Exception):
    """Dispatched graph mutation was invalid or rejected."""


class GraphTenantViolation(GraphMutationError):
    """A graph write named a tenant that does not own the scope/asset (A-03)."""


class GraphClaimLostError(GraphMutationError):
    """A write presented a stale or expired claim token (A-11/A-12)."""

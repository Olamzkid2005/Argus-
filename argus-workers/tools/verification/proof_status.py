"""The proof vocabulary shared by every verification path (Stage 4.1).

A verification produces a claim, and the claim has exactly five possible values:
a finding was reproduced, it was not, it is merely suspected, the verification
could not complete, or no real verification exists for that issue type. Keeping
one enum (and one mapping from a verifier's outcome to a value) means the TS
verifier results and the Python findings describe the same thing.

The mapping is deliberately conservative: nothing becomes ``REPRODUCED``
without an explicit reproduction, and a run that did not complete is
``INCONCLUSIVE`` rather than a negative — "we could not check" and "we checked
and it is not there" are not the same statement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProofStatus(StrEnum):
    """What a verification actually established."""

    SUSPECTED = "suspected"
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ProofResult:
    """A verification outcome with everything needed to audit the claim."""

    status: ProofStatus
    evidence_refs: tuple[str, ...] = ()
    control_refs: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None


def proof_status_for(
    *,
    reproduced: bool | None,
    completed: bool = True,
    supported: bool = True,
) -> ProofStatus:
    """Map a verifier outcome onto the proof vocabulary.

    Args:
        reproduced: True only when the verifier itself observed the exploit,
            False for a completed negative, None when the verifier produced no
            reproduction signal at all.
        completed: False when a step failed or timed out.
        supported: False when the issue type has no real verification yet.
    """
    if not supported:
        return ProofStatus.UNSUPPORTED
    if not completed:
        return ProofStatus.INCONCLUSIVE
    if reproduced is True:
        return ProofStatus.REPRODUCED
    if reproduced is False:
        return ProofStatus.NOT_REPRODUCED
    return ProofStatus.SUSPECTED

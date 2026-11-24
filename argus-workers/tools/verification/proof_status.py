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


#: Keys ``promote_finding`` writes on a finding to describe its proof. They have
#: to survive into ``findings.evidence``: the graph only accepts a goal proof it
#: can see in the row (``database.graph_repository.verifier_provenance_error``),
#: so a proof that lives only in the in-memory dict cannot conclude anything.
PROOF_EVIDENCE_KEYS = (
    "proof_status",
    "proof_evidence_refs",
    "proof_control_refs",
    "proof_error",
)


def evidence_with_proof(
    finding: dict, *, base: dict | None = None
) -> dict:
    """Return the evidence dict to persist for *finding*, proof included.

    The proof vocabulary is how a downstream reader tells "a verifier saw this"
    from "something called it CONFIRMED", so it is written next to the rest of
    the evidence rather than dropped when the finding leaves memory.

    Args:
        finding: A finding dict, usually the output of ``promote_finding``.
        base: Evidence to start from when the caller has already assembled some
            (for example the original evidence plus this run's verification).

    Returns:
        A new dict. ``finding`` and *base* are not mutated.
    """
    evidence: dict = dict(base if base is not None else (finding.get("evidence") or {}))
    for key in PROOF_EVIDENCE_KEYS:
        if key in finding and finding[key] is not None:
            evidence[key] = finding[key]
    # The verifier's own result travels too: it is what ``verifier_provenance_error``
    # reads as ``evidence.verification.verified``.
    verification = finding.get("verification")
    if isinstance(verification, dict) and "verification" not in evidence:
        evidence["verification"] = verification
    return evidence

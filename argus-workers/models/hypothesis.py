"""Hypothesis data model — TypedDict with runtime validation at trust boundaries."""

from __future__ import annotations

from typing import TypedDict

from tool_core._compat import NotRequired, StrEnum


class HypothesisStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    # PARTIALLY_VERIFIED — reserved for future verification step granularity


class VerificationStep(TypedDict):
    """A single verification action with a machine-executable contract."""
    description: str        # Human-readable: "Run sqlmap against /api/search?q=id"
    tool: str               # Tool name: "sqlmap"
    arguments: dict         # Default arguments: {"target": "/api/search", "parameter": "id"}
    expected: str           # Success criterion: "findings_count > 0" or "status.is_ok"


class Hypothesis(TypedDict):
    """A testable conjecture that explains a cluster of findings and proposes
    verification steps.

    This is a TypedDict for zero-runtime-overhead type checking.
    Validate external input via validate_hypothesis() before accepting it.
    """
    id: str
    engagement_id: str
    description: str
    root_cause_key: NotRequired[str | None]
    source_finding_id: NotRequired[str | None]
    confidence: float
    status: str  # HypothesisStatus value
    verification_steps: list[VerificationStep]
    finding_ids: list[str]
    supporting_finding_ids: list[str]
    refuting_finding_ids: list[str]
    suggested_tools: list[str]
    created_at: str  # ISO-8601
    updated_at: str  # ISO-8601


def validate_hypothesis(h: dict, *, source: str = "unknown") -> dict:
    """Runtime validation at trust boundaries (LLM output, Postgres load).

    Raises ValueError with a descriptive message on invalid input.
    Returns the dict unchanged (no copy) on success.
    """
    errors: list[str] = []

    if not isinstance(h.get("id"), str) or not h["id"]:
        errors.append("id must be a non-empty string")
    if not isinstance(h.get("description"), str) or not h["description"].strip():
        errors.append("description must be a non-empty string")
    if not isinstance(h.get("engagement_id"), str) or not h["engagement_id"]:
        errors.append("engagement_id must be a non-empty string")
    confidence = h.get("confidence", -1)
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        errors.append("confidence must be a float in [0.0, 1.0]")
    if h.get("status") not in ("UNVERIFIED", "CONFIRMED", "REJECTED"):
        errors.append(f"invalid status: {h.get('status')!r}")
    for list_field in ("finding_ids", "supporting_finding_ids",
                       "refuting_finding_ids", "suggested_tools"):
        val = h.get(list_field)
        if val is None:
            h[list_field] = []
        elif isinstance(val, str):
            errors.append(f"{list_field} must be a list, got string")
        elif not isinstance(val, list):
            errors.append(f"{list_field} must be a list, got {type(val).__name__}")
    # verification_steps is a list of dicts
    vs = h.get("verification_steps")
    if vs is None:
        h["verification_steps"] = []
    elif isinstance(vs, list):
        for i, step in enumerate(vs):
            if not isinstance(step, dict):
                errors.append(f"verification_steps[{i}] must be a dict")
            elif not isinstance(step.get("description"), str):
                errors.append(f"verification_steps[{i}].description must be a string")
    else:
        errors.append("verification_steps must be a list")

    if errors:
        raise ValueError(f"Hypothesis validation failed ({source}): {'; '.join(errors)}")
    return h


def validate_hypothesis_update(u: dict, *, source: str = "unknown") -> dict:
    """Validate a hypothesis update dict (from LLM update_hypotheses response).

    Each update must have:
      - hypothesis_id: non-empty string
      - status: one of UNVERIFIED/CONFIRMED/REJECTED (optional, defaults to UNVERIFIED)
      - confidence: float in [0.0, 1.0] (optional)
      - reasoning: string (optional)

    Raises ValueError on invalid input.
    Returns the dict unchanged on success.
    """
    errors: list[str] = []

    if not isinstance(u.get("hypothesis_id"), str) or not u["hypothesis_id"]:
        errors.append("hypothesis_id must be a non-empty string")
    status = u.get("status", "UNVERIFIED")
    if status not in ("UNVERIFIED", "CONFIRMED", "REJECTED"):
        errors.append(f"invalid status: {status!r}")
    confidence = u.get("confidence", -1)
    if confidence != -1 and (not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0)):
            errors.append("confidence must be a float in [0.0, 1.0]")

    if errors:
        raise ValueError(f"Hypothesis update validation failed ({source}): {'; '.join(errors)}")
    return u

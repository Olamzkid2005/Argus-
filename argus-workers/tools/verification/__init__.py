"""Finding verification — reproduction, confidence scoring, evidence collection, and promotion."""

from tools.verification.submission_gate import (
    GATE_QUESTIONS,
    GateAnswer,
    GateDecision,
    GateResult,
    GateVerdict,
    annotate_finding,
    evaluate_submission,
    gate_report_section,
)

__all__ = [
    "GATE_QUESTIONS",
    "GateAnswer",
    "GateDecision",
    "GateResult",
    "GateVerdict",
    "annotate_finding",
    "evaluate_submission",
    "gate_report_section",
]

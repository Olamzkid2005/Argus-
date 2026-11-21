"""The seven questions a finding must answer before it is submitted.

Adapted from the "7-Question Gate" discipline in Claude-BugHunter's
``triage-validation`` skill. Argus already knows whether a finding was
*reproduced* (``proof_status``) and how strongly it is believed
(``confidence``), but a confirmed finding is still not necessarily worth
reporting: it can be self-inflicted, out of scope, already known, unreviewable
without a request/response pair, or carry raw cookies and victim PII in its own
evidence. Those are the ways good findings get closed as N/A or flagged for
leaking data, and each one is a question with a machine-checkable answer.

The gate is deliberately conservative in one direction only: it never promotes
a finding. It answers:

* ``SUBMIT`` — every question passes, the report can be written.
* ``HOLD`` — something must be fixed first (redact evidence, capture proof,
  raise confidence); the finding is not discarded.
* ``DROP`` — the finding must not be submitted at all (reproduction says it is
  not there, it is self-inflicted, already known, or out of scope).

Findings that carry no signal for a question answer ``UNKNOWN`` rather than
``FAIL``, so a finding produced before this gate existed is still reportable —
"we did not record it" is not the same statement as "it is bad".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# The questions, in the order they are asked. The ids are stable so a report or
# a log line can cite the exact question that blocked a submission.
Q_REPRODUCIBLE = "q1-reproducible"
Q_EVIDENCE = "q2-evidence"
Q_IMPACT = "q3-impact"
Q_NOT_SELF_INFLICTED = "q4-not-self-inflicted"
Q_NOT_KNOWN = "q5-not-known-or-oos"
Q_HYGIENE = "q6-evidence-hygiene"
Q_IN_SCOPE = "q7-in-scope"

GATE_QUESTIONS: tuple[tuple[str, str], ...] = (
    (Q_REPRODUCIBLE, "Is the vulnerability actually reproduced, with proof?"),
    (Q_EVIDENCE, "Is there evidence a triager can audit (request/response, screenshot)?"),
    (Q_IMPACT, "Does it have real user impact, not just a scanner banner?"),
    (Q_NOT_SELF_INFLICTED, "Is it not self-inflicted (self-XSS, own session, own account)?"),
    (Q_NOT_KNOWN, "Is it not already known, duplicate, or on the program's OOS list?"),
    (Q_HYGIENE, "Is the evidence free of secrets and victim PII?"),
    (Q_IN_SCOPE, "Is the asset in the program's stated scope?"),
)

# Proof values that end the conversation: the verifier completed and said no,
# or no verification exists for this issue type at all.
_DROP_PROOF = frozenset({"not_reproduced", "unsupported"})
# Proof values that mean "not yet": worth holding, never worth dropping.
_REPRODUCED = "reproduced"

# A finding that answers ``no`` to these must not be submitted, whatever its
# confidence or proof status says.
_BLOCKING_ON_FAIL = frozenset(
    {Q_REPRODUCIBLE, Q_NOT_SELF_INFLICTED, Q_NOT_KNOWN, Q_IN_SCOPE}
)
# A question whose *unknown* answer still blocks the submission: a triager can
# only look at evidence, so "steps recorded, no artifact" is a hold, not a pass.
_HOLD_ON_UNKNOWN = frozenset({Q_EVIDENCE})

# Same secrets/PII classes Claude-BugHunter's ``evidence-hygiene`` skill lists:
# what a screenshot or a raw request must never carry into a submission.
_HYGIENE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bearer token", re.compile(r"authorization\s*:\s*bearer\s+\S+", re.I)),
    ("session cookie", re.compile(r"\b(?:session|sessionid|sid|phpsessid|jsessionid)\s*[=:]\s*\S+", re.I)),
    ("password field", re.compile(r"\b(?:password|passwd|pwd)\s*[=:]\s*[^\s&\"']+", re.I)),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
    # Only an address that is the *value* of a mail field is account data. A
    # bare address in a page body is the target's public contact, not PII, and
    # flagging it would make every marketing page hold.
    (
        "email field",
        re.compile(
            r"[\"']?\b(?:e-?mail|user_?email|email_?address|mail)\b[\"']?\s*[:=]\s*[\"']?"
            r"[\w.+-]+@[\w-]+\.[\w.-]{2,}",
            re.I,
        ),
    ),
)

# ``payload`` is deliberately absent: an attack string legitimately contains
# "password=' OR 1=1" and must not be mistaken for a captured credential.
_EVIDENCE_STRING_FIELDS = (
    "poc",
    "request",
    "response",
    "evidence",
    "screenshot",
    "raw_request",
    "raw_response",
    "http_request",
    "http_response",
)
_EVIDENCE_LIST_FIELDS = ("proof_evidence_refs", "evidence_refs", "artifacts")

_PLACEHOLDER_IMPACT = frozenset(
    {"", "n/a", "na", "none", "unknown", "tbd", "todo", "[not provided]"}
)

_SUBMITTABLE_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM"})


class GateVerdict(StrEnum):
    """The answer to one question."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class GateDecision(StrEnum):
    """What the gate says to do with the finding."""

    SUBMIT = "submit"
    HOLD = "hold"
    DROP = "drop"


@dataclass(frozen=True)
class GateAnswer:
    """One question, its answer, and the reason for that answer."""

    question_id: str
    question: str
    verdict: GateVerdict
    reason: str

    @property
    def passed(self) -> bool:
        return self.verdict is GateVerdict.PASS


@dataclass(frozen=True)
class GateResult:
    """The full gate outcome, including everything needed to explain it."""

    decision: GateDecision
    answers: tuple[GateAnswer, ...]
    blocking: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_submittable(self) -> bool:
        return self.decision is GateDecision.SUBMIT

    @property
    def failures(self) -> tuple[GateAnswer, ...]:
        return tuple(a for a in self.answers if a.verdict is GateVerdict.FAIL)

    def answer_for(self, question_id: str) -> GateAnswer:
        for answer in self.answers:
            if answer.question_id == question_id:
                return answer
        raise KeyError(question_id)

    def summary(self) -> str:
        """One line, suitable for a log line or a report header."""
        passed = sum(1 for a in self.answers if a.verdict is GateVerdict.PASS)
        total = len(self.answers)
        head = f"{self.decision.value.upper()} ({passed}/{total} questions passed)"
        if self.blocking:
            return f"{head}; blocked by {', '.join(self.blocking)}"
        return head

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "blocking": list(self.blocking),
            "summary": self.summary(),
            "answers": [
                {
                    "question_id": a.question_id,
                    "question": a.question,
                    "verdict": a.verdict.value,
                    "reason": a.reason,
                }
                for a in self.answers
            ],
        }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(v) for v in value)
    return str(value)


def _evidence_dict(finding: dict) -> dict:
    """The finding's structured ``evidence`` block, when it has one.

    Real findings from the database carry ``evidence`` as a dict (the model
    coerces strings and lists into one), with the captured traffic inside it.
    Reading only the top-level keys would answer question 2 with FAIL for every
    finding Argus actually produces.
    """
    evidence = finding.get("evidence")
    return evidence if isinstance(evidence, dict) else {}


def _evidence_blob(finding: dict) -> str:
    parts = [_text(finding.get(name)) for name in _EVIDENCE_STRING_FIELDS]
    for name in _EVIDENCE_LIST_FIELDS:
        value = finding.get(name)
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    parts.extend(_text(finding.get("evidence")))
    return "\n".join(p for p in parts if p)


def _severity_text(finding: dict) -> str:
    """Severity as an upper-case string, whether it is an enum or a string."""
    severity = finding.get("severity")
    value = getattr(severity, "value", severity)
    return _text(value).strip().upper()


def _answer(question_id: str, verdict: GateVerdict, reason: str) -> GateAnswer:
    question = dict(GATE_QUESTIONS)[question_id]
    return GateAnswer(question_id, question, verdict, reason)


def _ask_reproducible(finding: dict) -> GateAnswer:
    proof = str(finding.get("proof_status") or "").strip().lower()
    verification = str(finding.get("verification") or "").strip().lower()
    if proof == _REPRODUCED or verification == "reproduced":
        return _answer(Q_REPRODUCIBLE, GateVerdict.PASS, "verification reproduced the issue")
    if proof in _DROP_PROOF:
        return _answer(
            Q_REPRODUCIBLE,
            GateVerdict.FAIL,
            f"proof_status is '{proof}' — the verifier did not reproduce it",
        )
    if proof or verification:
        return _answer(
            Q_REPRODUCIBLE,
            GateVerdict.UNKNOWN,
            f"proof_status is '{proof or 'unset'}' — no reproduction recorded",
        )
    return _answer(
        Q_REPRODUCIBLE, GateVerdict.UNKNOWN, "no proof_status on the finding"
    )


def _ask_evidence(finding: dict) -> GateAnswer:
    refs: list[Any] = []
    for name in _EVIDENCE_LIST_FIELDS:
        value = finding.get(name)
        if isinstance(value, (list, tuple, set)):
            refs.extend(v for v in value if v)
        elif value:
            refs.append(value)

    evidence = _evidence_dict(finding)
    traffic_keys = ("request", "response", "poc", "raw_request", "raw_response")
    has_body = any(
        _text(finding.get(name)).strip() or _text(evidence.get(name)).strip()
        for name in traffic_keys
    )
    has_screenshot = bool(
        _text(finding.get("screenshot")).strip()
        or _text(evidence.get("screenshot") or evidence.get("screenshots")).strip()
    )
    if refs or has_body or has_screenshot:
        return _answer(
            Q_EVIDENCE, GateVerdict.PASS, "evidence reference or raw traffic present"
        )

    steps = _text(
        finding.get("repro_steps")
        or finding.get("reproduction_steps")
        or finding.get("steps")
        or evidence.get("steps")
        or evidence.get("repro_steps")
    ).strip()
    if steps:
        return _answer(
            Q_EVIDENCE,
            GateVerdict.UNKNOWN,
            "reproduction steps recorded but no evidence artifact",
        )
    return _answer(Q_EVIDENCE, GateVerdict.FAIL, "no evidence artifact to audit")


def _ask_impact(finding: dict) -> GateAnswer:
    severity = _severity_text(finding)
    impact = _text(finding.get("impact") or finding.get("description")).strip()
    if severity and severity not in _SUBMITTABLE_SEVERITIES:
        return _answer(
            Q_IMPACT,
            GateVerdict.FAIL,
            f"severity '{severity}' is below the submission floor",
        )
    if impact.lower() in _PLACEHOLDER_IMPACT:
        return _answer(Q_IMPACT, GateVerdict.UNKNOWN, "impact not described")
    if not severity:
        return _answer(Q_IMPACT, GateVerdict.UNKNOWN, "severity not recorded")
    return _answer(Q_IMPACT, GateVerdict.PASS, f"{severity} with a described impact")


def _ask_not_self_inflicted(finding: dict) -> GateAnswer:
    if finding.get("self_inflicted"):
        return _answer(
            Q_NOT_SELF_INFLICTED,
            GateVerdict.FAIL,
            "finding is flagged self-inflicted",
        )
    haystack = " ".join(
        [
            _text(finding.get("type")),
            _text(finding.get("tags")),
            _text(finding.get("title")),
        ]
    ).lower()
    for marker in ("self-xss", "self_xss", "self inflicted", "self-inflicted"):
        if marker in haystack:
            return _answer(
                Q_NOT_SELF_INFLICTED,
                GateVerdict.FAIL,
                f"description matches self-inflicted marker '{marker}'",
            )
    return _answer(
        Q_NOT_SELF_INFLICTED, GateVerdict.PASS, "no self-inflicted marker"
    )


def _ask_not_known(finding: dict) -> GateAnswer:
    if finding.get("duplicate") or finding.get("is_duplicate"):
        return _answer(
            Q_NOT_KNOWN, GateVerdict.FAIL, "finding is marked as a known duplicate"
        )
    if (
        finding.get("out_of_scope")
        or finding.get("out_of_scope_impact")
        or finding.get("known_issue")
    ):
        return _answer(
            Q_NOT_KNOWN,
            GateVerdict.FAIL,
            "finding is marked out-of-scope-impact or already known",
        )
    return _answer(Q_NOT_KNOWN, GateVerdict.PASS, "not flagged as duplicate or known")


def _ask_hygiene(finding: dict) -> GateAnswer:
    blob = _evidence_blob(finding)
    if not blob:
        return _answer(Q_HYGIENE, GateVerdict.PASS, "no evidence text to leak")
    found = [label for label, pattern in _HYGIENE_PATTERNS if pattern.search(blob)]
    if found:
        return _answer(
            Q_HYGIENE,
            GateVerdict.FAIL,
            "evidence carries " + ", ".join(sorted(set(found))),
        )
    return _answer(Q_HYGIENE, GateVerdict.PASS, "no secrets or PII found in evidence")


def _ask_in_scope(finding: dict) -> GateAnswer:
    declared = finding.get("in_scope")
    if declared is False:
        return _answer(Q_IN_SCOPE, GateVerdict.FAIL, "finding is marked out of scope")
    if declared is True:
        return _answer(Q_IN_SCOPE, GateVerdict.PASS, "finding is marked in scope")
    scope = finding.get("scope") if isinstance(finding.get("scope"), dict) else {}
    allowed = scope.get("allowed", True) if isinstance(scope, dict) else True
    if allowed is False:
        return _answer(Q_IN_SCOPE, GateVerdict.FAIL, "scope record disallows this target")
    return _answer(
        Q_IN_SCOPE, GateVerdict.UNKNOWN, "scope not recorded on the finding"
    )


def evaluate_submission(
    finding: dict,
    *,
    min_confidence: float = 0.65,
    require_reproduction: bool = False,
) -> GateResult:
    """Run the seven questions against one finding.

    Args:
        finding: An Argus finding dict (``VulnerabilityFinding`` shape).
        min_confidence: The floor the program's triage expects; a finding below
            it is held rather than dropped — more evidence can still lift it.
        require_reproduction: When True, a finding with no reproduction record
            at all is held rather than passed. Defaults to False: not every
            finding in Argus went through a verifier, and "we never recorded a
            proof" must not block a report that is otherwise sound. An explicit
            negative (``not_reproduced``/``unsupported``) always drops.

    Returns:
        A :class:`GateResult` with every answer, the blocking question ids and
        the resulting decision.
    """
    answers = (
        _ask_reproducible(finding),
        _ask_evidence(finding),
        _ask_impact(finding),
        _ask_not_self_inflicted(finding),
        _ask_not_known(finding),
        _ask_hygiene(finding),
        _ask_in_scope(finding),
    )

    blocking: list[str] = []
    decision = GateDecision.SUBMIT

    for answer in answers:
        if answer.verdict is not GateVerdict.FAIL:
            continue
        if answer.question_id in _BLOCKING_ON_FAIL:
            decision = GateDecision.DROP
            blocking.append(answer.question_id)
        elif decision is not GateDecision.DROP:
            decision = GateDecision.HOLD
            blocking.append(answer.question_id)

    confidence = finding.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None
    if confidence_value is not None and confidence_value < min_confidence:
        if decision is not GateDecision.DROP:
            decision = GateDecision.HOLD
        blocking.append("confidence-below-threshold")

    by_question = {a.question_id: a for a in answers}

    for question_id in _HOLD_ON_UNKNOWN:
        if (
            by_question[question_id].verdict is GateVerdict.UNKNOWN
            and decision is not GateDecision.DROP
            and question_id not in blocking
        ):
            decision = GateDecision.HOLD
            blocking.append(question_id)

    if (
        require_reproduction
        and by_question[Q_REPRODUCIBLE].verdict is GateVerdict.UNKNOWN
        and decision is not GateDecision.DROP
        and Q_REPRODUCIBLE not in blocking
    ):
        decision = GateDecision.HOLD
        blocking.append(Q_REPRODUCIBLE)

    return GateResult(decision=decision, answers=answers, blocking=tuple(blocking))


def annotate_finding(
    finding: dict,
    *,
    min_confidence: float = 0.65,
    require_reproduction: bool = False,
) -> dict:
    """Return a copy of the finding carrying the gate's verdict.

    The report text is not the only consumer: anything downstream (MCP tools,
    the UI, a triage queue) needs the decision itself, not a markdown table. The
    original finding is not mutated.
    """
    result = evaluate_submission(
        finding,
        min_confidence=min_confidence,
        require_reproduction=require_reproduction,
    )
    annotated = dict(finding)
    annotated["submission_gate"] = result.to_dict()
    annotated["submission_decision"] = result.decision.value
    annotated["submission_ready"] = result.is_submittable
    return annotated


def gate_report_section(result: GateResult) -> str:
    """Render the gate as a markdown block for a report appendix."""
    lines = [
        "## Submission gate",
        "",
        f"**Decision:** {result.summary()}",
        "",
        "| # | Question | Verdict | Why |",
        "| - | -------- | ------- | --- |",
    ]
    for index, answer in enumerate(result.answers, start=1):
        lines.append(
            f"| {index} | {answer.question} | {answer.verdict.value} | {answer.reason} |"
        )
    return "\n".join(lines) + "\n"

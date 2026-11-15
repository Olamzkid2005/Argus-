"""Structured, engagement-keyed observations from tool executions.

Stage 5.1. Before this module an agent session kept observations as free text
(`AgentSession.observations`), so the next decision could not tell a discovered
endpoint from a finding title, and nothing survived the phase that produced it:
recon found ``/api/users/1`` in one phase and the next phase started from prose.
Each observation here is a typed record — endpoint, parameter, auth, finding or
failure — keyed by ``engagement_id`` so later phases and later decisions see the
same facts, and deduplicated by ``(kind, value)`` so repeated scans do not
inflate the prompt.

Secrets are never recorded: extraction reads endpoint/parameter/finding data and
deliberately ignores credential-looking values.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

OBSERVATION_KINDS = ("endpoint", "parameter", "auth", "finding", "failure")

#: Keys whose values must never become an observation.
_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "authorization",
    "cookie",
    "secret",
    "api_key",
    "apikey",
    "csrf",
    "credential",
)

#: Argument/result keys that name the engagement target rather than a finding.
_TARGET_KEYS = ("target", "url", "endpoint", "host", "hostname", "domain", "base_url")

_URL_RE = re.compile(r"https?://[^\s\"'<>),\]]+")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _clean_url(value: str) -> str:
    return value.rstrip(".,;:)]}>")


@dataclass(frozen=True)
class Observation:
    """One structured fact observed during an engagement."""

    engagement_id: str
    kind: str
    value: str
    source_tool: str = ""
    action_id: str = ""
    detail: str = ""
    observed_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EngagementObservationStore:
    """Thread-safe observation store keyed by engagement and observation kind."""

    def __init__(self) -> None:
        self._by_engagement: dict[str, dict[str, list[Observation]]] = {}
        self._lock = threading.Lock()

    def record(self, observation: Observation) -> bool:
        """Store one observation; returns False for a duplicate or invalid one."""
        if not observation.engagement_id or not observation.value:
            return False
        if observation.kind not in OBSERVATION_KINDS:
            raise ValueError(f"Unknown observation kind: {observation.kind}")
        with self._lock:
            kinds = self._by_engagement.setdefault(observation.engagement_id, {})
            bucket = kinds.setdefault(observation.kind, [])
            if any(existing.value == observation.value for existing in bucket):
                return False
            bucket.append(observation)
            return True

    def record_many(self, observations: Iterable[Observation]) -> int:
        return sum(1 for observation in observations if self.record(observation))

    def records(
        self,
        engagement_id: str,
        kinds: Iterable[str] | None = None,
    ) -> list[Observation]:
        with self._lock:
            kinds_map = self._by_engagement.get(engagement_id, {})
            wanted = list(kinds) if kinds is not None else list(OBSERVATION_KINDS)
            collected: list[Observation] = []
            for kind in wanted:
                collected.extend(kinds_map.get(kind, []))
            return list(collected)

    def values(self, engagement_id: str, kind: str) -> list[str]:
        return [observation.value for observation in self.records(engagement_id, [kind])]

    def prompt_section(self, engagement_id: str, limit: int = 40) -> str:
        """Render the engagement's observations for a selection prompt."""
        records = self.records(engagement_id)
        if not records:
            return "No structured observations have been recorded for this engagement yet."
        lines: list[str] = []
        for kind in OBSERVATION_KINDS:
            of_kind = [r for r in records if r.kind == kind]
            if not of_kind:
                continue
            lines.append(f"{kind.upper()} ({len(of_kind)}):")
            for observation in of_kind[-limit:]:
                source = f" [{observation.source_tool}]" if observation.source_tool else ""
                lines.append(f"- {observation.value}{source}")
        return "\n".join(lines)

    def clear(self, engagement_id: str) -> None:
        with self._lock:
            self._by_engagement.pop(engagement_id, None)


def _iter_strings(value: Any, depth: int = 0) -> Iterable[str]:
    """Yield endpoint-looking strings and named parameters from nested data."""
    if depth > 4:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and not _is_secret_key(key):
                yield key
            yield from _iter_strings(nested, depth + 1)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _iter_strings(nested, depth + 1)


def _extract_endpoints(argument_targets: list[str], result: Any, summary: str) -> list[str]:
    endpoints: list[str] = []
    for target in argument_targets:
        if target.startswith(("http://", "https://")):
            endpoints.append(_clean_url(target))
    seen: set[str] = set(endpoints)

    def add(url: str) -> None:
        cleaned = _clean_url(url)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            endpoints.append(cleaned)

    for text in list(_iter_strings(result)) + [summary or ""]:
        for match in _URL_RE.findall(text):
            add(match)
    return endpoints


def _extract_parameters(endpoints: list[str], result: Any, arguments: dict) -> list[str]:
    parameters: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        candidate = str(name).strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            parameters.append(candidate)

    # Query parameters of discovered endpoints are discovered parameters.
    for endpoint in endpoints:
        try:
            for key, _value in parse_qsl(urlsplit(endpoint).query, keep_blank_values=True):
                add(key)
        except Exception:  # pragma: no cover - malformed URL
            continue

    for key in ("parameter", "parameters", "injectable_parameters", "params"):
        nested = arguments.get(key) if isinstance(arguments, dict) else None
        if isinstance(nested, str):
            add(nested)
        elif isinstance(nested, (list, tuple, set)):
            for item in nested:
                add(item)
    if isinstance(result, dict):
        for key in ("parameter", "parameters", "injectable_parameters"):
            nested = result.get(key)
            if isinstance(nested, str):
                add(nested)
            elif isinstance(nested, (list, tuple, set)):
                for item in nested:
                    add(item)
    return parameters


def public_identity_label(value: Any) -> str:
    """Normalize an explicit identity label without inspecting its contents."""
    return value.strip() if isinstance(value, str) else ""


def _identity_from(arguments: dict) -> str:
    for key in ("email", "username", "user", "identity", "role"):
        value = arguments.get(key) if isinstance(arguments, dict) else None
        if isinstance(value, str) and value.strip() and not _is_secret_key(key):
            return value.strip()
    return ""


def identity_from(arguments: dict) -> str:
    """Public provenance helper: return a non-secret identity label, if any."""
    return _identity_from(arguments)


def _auth_tool(tool: str) -> bool:
    lowered = tool.lower()
    return any(marker in lowered for marker in ("login", "register", "signup", "auth"))


def _findings_from(result: Any) -> list[str]:
    titles: list[str] = []
    if isinstance(result, dict):
        findings = result.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if isinstance(finding, dict):
                    title = finding.get("title") or finding.get("name") or finding.get("type")
                    if isinstance(title, str) and title:
                        titles.append(title)
                elif isinstance(finding, str):
                    titles.append(finding)
    return titles


def extract_observations(
    engagement_id: str,
    tool: str,
    arguments: dict | None = None,
    *,
    success: bool = True,
    summary: str = "",
    result: Any = None,
    action_id: str = "",
) -> list[Observation]:
    """Turn one tool execution into structured observations.

    Endpoints come from what the tool was pointed at and what it returned;
    parameters come from the discovered endpoints' query strings and from
    explicitly reported parameter fields; auth comes from a successful
    login/register tool (identity only, never credentials); findings from the
    result's ``findings`` list; a failed tool produces a failure observation.
    """
    arguments = arguments if isinstance(arguments, dict) else {}
    observations: list[Observation] = []

    targets = [
        value
        for key, value in arguments.items()
        if key in _TARGET_KEYS and isinstance(value, str) and value
    ]
    endpoints = _extract_endpoints(targets, result, summary)
    for endpoint in endpoints:
        observations.append(
            Observation(
                engagement_id=engagement_id,
                kind="endpoint",
                value=endpoint,
                source_tool=tool,
                action_id=action_id,
                detail="observed endpoint",
            )
        )
    for parameter in _extract_parameters(endpoints, result, arguments):
        observations.append(
            Observation(
                engagement_id=engagement_id,
                kind="parameter",
                value=parameter,
                source_tool=tool,
                action_id=action_id,
                detail="observed parameter",
            )
        )

    if success and _auth_tool(tool):
        identity = _identity_from(arguments)
        observations.append(
            Observation(
                engagement_id=engagement_id,
                kind="auth",
                value=identity or "session established",
                source_tool=tool,
                action_id=action_id,
                detail="authentication established",
            )
        )

    for title in _findings_from(result):
        observations.append(
            Observation(
                engagement_id=engagement_id,
                kind="finding",
                value=title,
                source_tool=tool,
                action_id=action_id,
                detail="finding reported",
            )
        )

    if not success:
        failure = (summary or getattr(result, "get", lambda *_: "")("error", "") or tool).strip()
        observations.append(
            Observation(
                engagement_id=engagement_id,
                kind="failure",
                value=f"{tool}: {failure[:200]}" if failure and failure != tool else f"{tool} failed",
                source_tool=tool,
                action_id=action_id,
                detail="tool failure",
            )
        )
    return observations


#: Process-wide store used by the MCP server; tests pass their own instance.
_default_store = EngagementObservationStore()


def get_observation_store() -> EngagementObservationStore:
    return _default_store

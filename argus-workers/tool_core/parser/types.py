from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedFinding:
    title: str
    severity: int
    confidence: int
    description: str = ""
    tool: str = ""
    phase: str = ""
    cve: str | None = None
    cwe: str | None = None
    owasp: str | None = None
    remediation: str | None = None
    evidence: list[dict] = field(default_factory=list)
    subtype: str | None = None

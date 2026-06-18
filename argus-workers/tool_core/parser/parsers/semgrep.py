import json

from ..normalizer import SEVERITY_MAP
from ..types import NormalizedFinding


def parse(output: str) -> list[NormalizedFinding]:
    findings = []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return findings

    for result in data.get("results", []):
        extra = result.get("extra", {})
        metadata = extra.get("metadata", {})

        cwe_raw = metadata.get("cwe", "")
        if isinstance(cwe_raw, list):
            cwe_str = ",".join(str(c) for c in cwe_raw)
        else:
            cwe_str = str(cwe_raw) if cwe_raw else ""

        confidence_raw = metadata.get("confidence", "medium")
        confidence = 4 if str(confidence_raw).lower() in ("high", "5") else 3

        findings.append(
            NormalizedFinding(
                title=result.get("check_id", "Semgrep finding"),
                severity=SEVERITY_MAP.get(extra.get("severity", "medium"), 2),
                confidence=confidence,
                description=extra.get("message", ""),
                tool="semgrep",
                cwe=cwe_str,
                owasp=metadata.get("owasp", ""),
                evidence=[
                    {
                        "type": "code",
                        "file": result.get("path", ""),
                        "line": result.get("start", {}).get("line", 0),
                        "content": extra.get("lines", ""),
                    }
                ],
                subtype="code_vulnerability",
            )
        )
    return findings

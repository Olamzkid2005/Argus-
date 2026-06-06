import json

from ..types import NormalizedFinding
from ..normalizer import SEVERITY_MAP, CONFIDENCE_MAP


def parse(output: str) -> list[NormalizedFinding]:
    findings = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        info = data.get("info", {})
        cwe_list = info.get("classification", {}).get("cwe", [])
        cve_list = info.get("classification", {}).get("cve", [])
        findings.append(NormalizedFinding(
            title=info.get("name", "Unknown finding"),
            severity=SEVERITY_MAP.get(info.get("severity", ""), 2),
            confidence=CONFIDENCE_MAP.get(data.get("signal_quality", "PROBABLE"), 3),
            cwe=",".join(cwe_list) if isinstance(cwe_list, list) else str(cwe_list or ""),
            cve=",".join(cve_list) if isinstance(cve_list, list) else str(cve_list or ""),
            description=info.get("description", ""),
            tool="nuclei",
            evidence=[{"type": "http", "content": data.get("matched-at", "")}],
        ))
    return findings

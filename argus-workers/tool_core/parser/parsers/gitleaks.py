import hashlib
import json

from ..types import NormalizedFinding
from ..normalizer import SEVERITY_MAP


def parse(output: str) -> list[NormalizedFinding]:
    findings = []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return findings

    if isinstance(data, dict):
        items = data.get("findings", [data])
    elif isinstance(data, list):
        items = data
    else:
        return findings

    for item in items:
        secret = item.get("Secret", "") or ""
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()[:16] if secret else ""

        findings.append(NormalizedFinding(
            title=item.get("RuleID", item.get("rule", "Secret leak")),
            severity=SEVERITY_MAP.get(item.get("Severity", item.get("severity", "medium")), 2),
            confidence=5,
            description=f"Secret type: {item.get('Description', item.get('description', ''))} in file {item.get('File', item.get('file', 'unknown'))}",
            tool="gitleaks",
            evidence=[{
                "type": "code",
                "file": item.get("File", item.get("file", "")),
                "line": item.get("StartLine", item.get("start_line", 0)),
                "commit": item.get("Commit", item.get("commit", "")),
                "author": item.get("Author", item.get("author", "")),
                "secret_hash": secret_hash,
                "match": item.get("Match", item.get("match", "")),
            }],
            subtype="secret_leak",
        ))
    return findings

import json

from ..types import NormalizedFinding
from ..normalizer import SEVERITY_MAP


def parse(output: str) -> list[NormalizedFinding]:
    findings = []

    items = None
    try:
        items = json.loads(output)
    except json.JSONDecodeError:
        pass

    entries = []
    if isinstance(items, list):
        entries = items
    elif isinstance(items, dict):
        entries = [items]
    else:
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url", "") or entry.get("target", "")
        plugins = {k: v for k, v in entry.items() if k not in ("url", "target")}

        if not plugins:
            continue

        plugin_names = ", ".join(sorted(plugins.keys()))
        findings.append(NormalizedFinding(
            title=f"Technology detected: {plugin_names}",
            severity=SEVERITY_MAP.get("info", 0),
            confidence=3,
            description=f"Detected {len(plugins)} technologies on {url}",
            tool="whatweb",
            evidence=[{
                "type": "technology",
                "url": url,
                "plugins": plugins,
            }],
            subtype="technology_detection",
        ))

    return findings

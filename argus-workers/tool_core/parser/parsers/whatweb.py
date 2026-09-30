import json
import re

from ..normalizer import SEVERITY_MAP
from ..types import NormalizedFinding

#: ANSI color sequences Ruby WhatWeb emits without --color=never.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: One target per line, e.g.
#:     http://127.0.0.1:55693/ [404 Not Found] HTTPServer[Werkzeug/3.1.9]
#:     http://example.com [200 OK] Apache[2.4.41], Title[Example]
_TEXT_LINE_RE = re.compile(
    r"^(?P<url>\S+)\s+\[(?P<status>[^\]]*)\]\s*(?P<plugins>.*)$"
)

#: Plugin tokens inside the remainder: Name[value], comma or space separated.
_TEXT_PLUGIN_RE = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9_-]*)\[(?P<value>[^\]]*)\]")


def _parse_text_lines(output: str) -> list[NormalizedFinding]:
    """Parse the text line format WhatWeb prints by default.

    The installed whatweb accepts only a positional target and prints
    ``URL [status] Plugin[value] ...``; Ruby WhatWeb prints the same shape
    (comma separated, optionally colored). The JSON branch below only matches
    ``--log-json`` output, which neither of those builds supports here.
    """
    findings = []
    for raw_line in output.splitlines():
        line = _ANSI_RE.sub("", raw_line).strip()
        if not line:
            continue
        match = _TEXT_LINE_RE.match(line)
        if not match:
            continue
        plugins = {
            plugin.group("name"): plugin.group("value")
            for plugin in _TEXT_PLUGIN_RE.finditer(match.group("plugins"))
        }
        if not plugins:
            continue
        url = match.group("url")
        plugin_names = ", ".join(sorted(plugins))
        findings.append(
            NormalizedFinding(
                title=f"Technology detected: {plugin_names}",
                severity=SEVERITY_MAP.get("info", 0),
                confidence=3,
                description=f"Detected {len(plugins)} technologies on {url}",
                tool="whatweb",
                evidence=[
                    {
                        "type": "technology",
                        "url": url,
                        "status": match.group("status"),
                        "plugins": plugins,
                    }
                ],
                subtype="technology_detection",
            )
        )
    return findings


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

    if not entries:
        return _parse_text_lines(output)

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url", "") or entry.get("target", "")
        plugins = {k: v for k, v in entry.items() if k not in ("url", "target")}

        if not plugins:
            continue

        plugin_names = ", ".join(sorted(plugins.keys()))
        findings.append(
            NormalizedFinding(
                title=f"Technology detected: {plugin_names}",
                severity=SEVERITY_MAP.get("info", 0),
                confidence=3,
                description=f"Detected {len(plugins)} technologies on {url}",
                tool="whatweb",
                evidence=[
                    {
                        "type": "technology",
                        "url": url,
                        "plugins": plugins,
                    }
                ],
                subtype="technology_detection",
            )
        )

    return findings

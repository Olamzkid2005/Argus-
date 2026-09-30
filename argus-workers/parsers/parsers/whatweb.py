import contextlib
import json
import re

from parsers.parsers.base import BaseParser

#: ANSI color sequences Ruby WhatWeb emits without --color=never.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: One target per line: URL [status] Plugin[value] ...
_TEXT_LINE_RE = re.compile(
    r"^(?P<url>\S+)\s+\[(?P<status>[^\]]*)\]\s*(?P<plugins>.*)$"
)
_TEXT_PLUGIN_RE = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9_-]*)\[(?P<value>[^\]]*)\]")


class WhatwebParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        items = None
        with contextlib.suppress(json.JSONDecodeError):
            items = json.loads(raw_output)
        if isinstance(items, list):
            entries = items
        elif isinstance(items, dict):
            entries = [items]
        else:
            entries = []
            for line in raw_output.splitlines():
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if not entries:
            return self._parse_text_lines(raw_output)
        for entry in entries:
            url = entry.get("url", "") or entry.get("target", "")
            plugins = {k: v for k, v in entry.items() if k not in ("url", "target")}
            finding = {
                "type": "TECHNOLOGY_DETECTED",
                "severity": "INFO",
                "endpoint": url,
                "evidence": {
                    "plugins": plugins,
                },
                "confidence": 0.85,
                "tool": "whatweb",
            }
            findings.append(finding)
        return findings

    def _parse_text_lines(self, raw_output: str) -> list[dict]:
        """Parse the text line format WhatWeb prints by default.

        The installed whatweb accepts only a positional target and prints
        ``URL [status] Plugin[value] ...``; Ruby WhatWeb prints the same shape
        (comma separated, optionally colored). The JSON branch above only
        matches ``--log-json`` output, which neither build supports here.
        """
        findings = []
        for raw_line in raw_output.splitlines():
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
            findings.append(
                {
                    "type": "TECHNOLOGY_DETECTED",
                    "severity": "INFO",
                    "endpoint": match.group("url"),
                    "evidence": {
                        "status": match.group("status"),
                        "plugins": plugins,
                    },
                    "confidence": 0.85,
                    "tool": "whatweb",
                }
            )
        return findings

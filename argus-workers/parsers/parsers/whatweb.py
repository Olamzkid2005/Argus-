import contextlib
import json

from parsers.parsers.base import BaseParser


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
            for line in raw_output.split("\n"):
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
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

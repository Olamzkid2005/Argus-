import json

from parsers.parsers.base import BaseParser


class WhatwebParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                url = data.get("url", "")
                plugins = {k: v for k, v in data.items() if k != "url"}
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
            except json.JSONDecodeError:
                continue
        return findings

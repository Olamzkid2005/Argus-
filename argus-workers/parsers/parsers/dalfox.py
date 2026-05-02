import json

from parsers.parsers.base import BaseParser


class DalfoxParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                finding = {
                    "type": "XSS",
                    "severity": "HIGH",
                    "endpoint": data.get("endpoint") or data.get("url", ""),
                    "evidence": {
                        "param": data.get("param", ""),
                        "payload": data.get("payload", ""),
                        "type": data.get("type", ""),
                        "severity": data.get("severity", "HIGH"),
                    },
                    "confidence": 0.85,
                    "tool": "dalfox",
                }
                findings.append(finding)
            except json.JSONDecodeError:
                continue
        return findings

import json

from parsers.parsers.base import BaseParser


class AmassParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                name = data.get("name", "").strip().rstrip(".")
                finding = {
                    "type": "SUBDOMAIN_DISCOVERY",
                    "severity": "INFO",
                    "endpoint": name,
                    "evidence": {
                        "addresses": data.get("addresses", []),
                        "tag": data.get("tag", ""),
                    },
                    "confidence": 0.85,
                    "tool": "amass",
                }
                findings.append(finding)
            except json.JSONDecodeError:
                continue
        return findings

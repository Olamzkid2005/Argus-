import json

from parsers.parsers.base import BaseParser


class TestsslParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                finding = {
                    "type": "TLS_VULNERABILITY",
                    "severity": (
                        "HIGH" if data.get("severity", "").upper() in ("HIGH", "CRITICAL")
                        else "MEDIUM" if data.get("severity", "").upper() == "MEDIUM"
                        else "INFO"
                    ),
                    "endpoint": data.get("host", "") + (f":{data['port']}" if "port" in data else ""),
                    "evidence": {
                        "id": data.get("id", ""),
                        "finding": data.get("finding", ""),
                    },
                    "confidence": 0.90,
                    "tool": "testssl",
                }
                findings.append(finding)
            except json.JSONDecodeError:
                continue
        return findings

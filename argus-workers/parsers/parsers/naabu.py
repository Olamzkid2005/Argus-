import json

from parsers.parsers.base import BaseParser


class NaabuParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                finding = {
                    "type": "OPEN_PORT",
                    "severity": "MEDIUM",
                    "endpoint": f"{data.get('host', '')}:{data.get('port', '')}",
                    "evidence": {
                        "host": data.get("host"),
                        "port": data.get("port"),
                        "protocol": data.get("protocol", "tcp"),
                    },
                    "confidence": 1.0,
                    "tool": "naabu",
                }
                findings.append(finding)
            except json.JSONDecodeError:
                continue
        return findings

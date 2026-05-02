import re

from parsers.parsers.base import BaseParser


class JwtToolParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            severity = "MEDIUM"
            if any(kw in line.lower() for kw in ["vulnerable", "critical", "high", "exploit"]):
                severity = "HIGH"
            elif any(kw in line.lower() for kw in ["info", "note"]):
                severity = "INFO"

            finding = {
                "type": "JWT_VULNERABILITY",
                "severity": severity,
                "endpoint": "",
                "evidence": {
                    "line": line.strip(),
                },
                "confidence": 0.65,
                "tool": "jwt_tool",
            }
            findings.append(finding)
        return findings

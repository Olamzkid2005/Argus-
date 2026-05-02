import re

from parsers.parsers.base import BaseParser


class CommixParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        if "commix identified" in raw_output.lower() or "injection" in raw_output.lower():
            finding = {
                "type": "COMMAND_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "",
                "evidence": {
                    "raw_output": raw_output[:1000],
                },
                "confidence": 0.85,
                "tool": "commix",
            }
            findings.append(finding)
        return findings

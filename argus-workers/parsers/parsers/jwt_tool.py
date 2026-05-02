from parsers.parsers.base import BaseParser


class JwtToolParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("[+]"):
                finding = {
                    "type": "JWT_VULNERABILITY",
                    "severity": "HIGH",
                    "endpoint": "",
                    "evidence": {
                        "finding": stripped,
                    },
                    "confidence": 0.80,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
            elif stripped.startswith("[!]") or stripped.startswith("[WARNING]"):
                finding = {
                    "type": "JWT_VULNERABILITY",
                    "severity": "MEDIUM",
                    "endpoint": "",
                    "evidence": {
                        "finding": stripped,
                    },
                    "confidence": 0.60,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
        return findings

from parsers.parsers.base import BaseParser


class SubfinderParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            if "." in line and not line.startswith("http"):
                finding = {
                    "type": "SUBDOMAIN_DISCOVERY",
                    "severity": "INFO",
                    "endpoint": line,
                    "evidence": {},
                    "confidence": 0.80,
                    "tool": "subfinder",
                }
                findings.append(finding)
        return findings

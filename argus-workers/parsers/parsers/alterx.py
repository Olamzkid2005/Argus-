from parsers.parsers.base import BaseParser, structured_findings


class AlterxParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        structured = structured_findings(raw_output)
        if structured:
            return structured
        findings = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            if "." in line and not line.startswith("http"):
                finding = {
                    "type": "SUBDOMAIN_DISCOVERY",
                    "severity": "INFO",
                    "endpoint": line,
                    "evidence": {},
                    "confidence": 0.70,
                    "tool": "alterx",
                }
                findings.append(finding)
        return findings

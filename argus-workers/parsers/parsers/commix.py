from parsers.parsers.base import BaseParser


class CommixParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        confirmed = False
        for line in raw_output.split("\n"):
            if "[*] Setting the OS shell" in line or "[*] Setting the pseudo" in line:
                confirmed = True
                break
        if not confirmed:
            return findings
        finding = {
            "type": "COMMAND_INJECTION",
            "severity": "CRITICAL",
            "endpoint": "",
            "evidence": {
                "raw_output": raw_output[:1000],
            },
            "confidence": 0.90,
            "tool": "commix",
        }
        findings.append(finding)
        return findings

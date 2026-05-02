import json

from parsers.parsers.base import BaseParser


class ArjunParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings

        if isinstance(data, dict):
            for endpoint, params in data.items():
                if isinstance(params, list):
                    finding = {
                        "type": "PARAMETER_DISCOVERY",
                        "severity": "INFO",
                        "endpoint": endpoint,
                        "evidence": {
                            "parameters": params,
                        },
                        "confidence": 0.75,
                        "tool": "arjun",
                    }
                    findings.append(finding)
                elif isinstance(params, dict):
                    param_list = list(params.keys())
                    finding = {
                        "type": "PARAMETER_DISCOVERY",
                        "severity": "INFO",
                        "endpoint": endpoint,
                        "evidence": {
                            "parameters": param_list,
                        },
                        "confidence": 0.75,
                        "tool": "arjun",
                    }
                    findings.append(finding)
        return findings

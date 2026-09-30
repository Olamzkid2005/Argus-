import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class DalfoxParser(BaseParser):
    """Parser for dalfox XSS output.

    Reads JSON Lines (``dalfox url --format jsonl``). dalfox v2 emits the
    target URL as a *string* in ``data`` with ``param``/``payload``/``cwe``/
    ``severity`` at the top level; older builds nested those under a ``data``
    object. Both shapes are handled, and the banner/progress lines dalfox
    writes to stdout are skipped.
    """

    #: dalfox ``type`` codes: V=verified, R=reflected, G=grep-only.
    _CONFIDENCE = {"V": 0.95, "R": 0.70, "G": 0.40}
    _QUALIFIER = {"V": "Verified", "R": "Reflected", "G": "Potential"}

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped or not stripped.startswith("{"):
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning(
                    "Non-JSON line encountered in Dalfox output, skipping: %s",
                    stripped[:200],
                )
                continue
            if not isinstance(obj, dict):
                continue

            nested = obj.get("data")
            if isinstance(nested, dict):
                endpoint = nested.get("url", "")
                param = nested.get("param", "")
                payload = nested.get("payload", "")
            else:
                # v2: `data` is the URL itself.
                endpoint = nested if isinstance(nested, str) else obj.get("url", "")
                param = obj.get("param", "")
                payload = obj.get("payload", "")

            vuln_type = str(obj.get("type", "")).upper()
            title = f"{self._QUALIFIER.get(vuln_type, 'Potential')} XSS"
            if param:
                title += f" in parameter '{param}'"
            findings.append(
                {
                    "type": "XSS",
                    "title": title,
                    "severity": str(obj.get("severity") or "High").upper(),
                    "endpoint": endpoint,
                    "description": str(obj.get("message_str") or ""),
                    "cwe": obj.get("cwe") or None,
                    "evidence": {
                        "param": param,
                        "payload": payload,
                        "vuln_type": vuln_type,
                        "cwe": obj.get("cwe", ""),
                        "message": obj.get("message_str", ""),
                    },
                    "confidence": self._CONFIDENCE.get(vuln_type, 0.50),
                    "tool": "dalfox",
                }
            )
        return findings

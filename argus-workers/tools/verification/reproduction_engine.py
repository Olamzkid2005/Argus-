"""Reproduction engine for attempting to reproduce findings."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ReproductionEngine:
    """Attempts to reproduce a finding by replaying the attack."""

    def __init__(self, http_client=None):
        self._http_client = http_client

    def reproduce(self, finding: dict, target: str) -> dict:
        """Attempt to reproduce a finding.

        Returns dict with 'reproduced' bool, 'evidence' dict, and 'error' if any.
        """
        ftype = (finding.get("type") or "").upper().replace(" ", "_").replace("-", "_")
        endpoint = finding.get("endpoint", target)

        try:
            if ftype in ("SQL_INJECTION", "SQLI"):
                return self._reproduce_sqli(endpoint, finding)
            elif ftype in ("XSS", "STORED_XSS", "REFLECTED_XSS"):
                return self._reproduce_xss(endpoint, finding)
            elif ftype == "CSRF":
                return self._reproduce_csrf(endpoint, finding)
            elif ftype in ("COMMAND_INJECTION", "RCE"):
                return self._reproduce_cmdi(endpoint, finding)
            elif ftype in ("SSRF",):
                return self._reproduce_ssrf(endpoint, finding)
            else:
                return self._reproduce_generic(endpoint, finding)
        except Exception as e:
            logger.debug("Reproduction failed for %s: %s", ftype, e)
            return {"reproduced": False, "error": str(e), "evidence": {}}

    def _reproduce_sqli(self, endpoint: str, finding: dict) -> dict:
        test_payloads = ["'", "1' OR '1'='1", "1 UNION SELECT NULL--"]
        evidence = {"endpoint": endpoint, "payloads_tested": test_payloads, "type": "sqli"}
        return {"reproduced": False, "evidence": evidence, "error": "Requires live HTTP client"}

    def _reproduce_xss(self, endpoint: str, finding: dict) -> dict:
        test_payloads = ["<script>alert(1)</script>", "\"><img src=x onerror=alert(1)>"]
        evidence = {"endpoint": endpoint, "payloads_tested": test_payloads, "type": "xss"}
        return {"reproduced": False, "evidence": evidence, "error": "Requires live HTTP client"}

    def _reproduce_csrf(self, endpoint: str, finding: dict) -> dict:
        evidence = {"endpoint": endpoint, "type": "csrf", "checks": ["token_absent", "origin_not_validated"]}
        return {"reproduced": False, "evidence": evidence, "error": "Requires live HTTP client"}

    def _reproduce_cmdi(self, endpoint: str, finding: dict) -> dict:
        evidence = {"endpoint": endpoint, "type": "cmdi", "severity": "CRITICAL"}
        return {"reproduced": False, "evidence": evidence, "error": "Requires live HTTP client"}

    def _reproduce_ssrf(self, endpoint: str, finding: dict) -> dict:
        evidence = {"endpoint": endpoint, "type": "ssrf", "test_url": "http://169.254.169.254/latest/meta-data/"}
        return {"reproduced": False, "evidence": evidence, "error": "Requires live HTTP client"}

    def _reproduce_generic(self, endpoint: str, finding: dict) -> dict:
        evidence = {"endpoint": endpoint, "type": finding.get("type", "unknown")}
        return {"reproduced": False, "evidence": evidence, "error": "No specific reproduction for this finding type"}

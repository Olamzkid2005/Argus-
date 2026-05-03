"""
WPScan parser.

WPScan outputs JSON via --format json flag.
Covers: plugin/theme CVEs, weak passwords, user enumeration,
        xmlrpc abuse, backup file exposure.
"""
import json
import logging

from .base import BaseParser

logger = logging.getLogger(__name__)


class WpscanParser(BaseParser):

    SEVERITY_MAP = {
        "critical": "CRITICAL",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
        "informational": "INFO",
        "info": "INFO",
        "": "MEDIUM",
    }

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        if not raw_output or not raw_output.strip():
            return findings

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            logger.debug("wpscan: output is not valid JSON")
            return findings

        target = data.get("target_url", "")

        # Interesting findings (exposed files, version info, user enumeration)
        for item in data.get("interesting_findings", []):
            f = self._make_finding(
                finding_type=item.get("type", "WORDPRESS_MISCONFIGURATION").upper(),
                severity="MEDIUM",
                endpoint=item.get("url") or target,
                evidence={
                    "description": item.get("to_s", ""),
                    "references": item.get("references", {}),
                    "found_by": item.get("found_by", ""),
                },
            )
            findings.append(f)

        # Plugin vulnerabilities
        for plugin_name, plugin_data in data.get("plugins", {}).items():
            for vuln in plugin_data.get("vulnerabilities", []):
                findings.append(self._vuln_finding(vuln, target, f"plugin:{plugin_name}"))

        # Theme vulnerabilities
        for theme_name, theme_data in data.get("themes", {}).items():
            for vuln in theme_data.get("vulnerabilities", []):
                findings.append(self._vuln_finding(vuln, target, f"theme:{theme_name}"))

        # WordPress core vulnerabilities
        wp_version = data.get("version", {})
        for vuln in wp_version.get("vulnerabilities", []):
            findings.append(self._vuln_finding(vuln, target, "wordpress_core"))

        # Users (enumeration finding)
        users = data.get("users", {})
        if users:
            findings.append(self._make_finding(
                finding_type="USER_ENUMERATION",
                severity="MEDIUM",
                endpoint=target,
                evidence={"users_found": list(users.keys())[:20]},
            ))

        return findings

    def _vuln_finding(self, vuln: dict, target: str, source: str) -> dict:
        title = vuln.get("title", "WordPress Vulnerability")
        refs = vuln.get("references", {})
        cve_ids = refs.get("cve", [])
        cvss = None
        if cve_ids:
            # Try to extract CVSS from title or leave for NVD enrichment
            pass
        return self._make_finding(
            finding_type="WORDPRESS_VULNERABILITY",
            severity=self.SEVERITY_MAP.get(
                str(vuln.get("cvss", {}).get("severity", "")).lower(), "HIGH"
            ),
            endpoint=target,
            evidence={
                "title": title,
                "source": source,
                "cve_ids": cve_ids,
                "fixed_in": vuln.get("fixed_in"),
                "references": refs,
            },
        )

    def _make_finding(self, finding_type, severity, endpoint, evidence):
        return {
            "type": finding_type,
            "severity": severity,
            "endpoint": endpoint,
            "evidence": evidence,
            "confidence": 0.85,
            "tool": "wpscan",
        }

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
        for item in data.get("interesting_findings") or []:
            raw_type = item.get("type")
            finding_type_str = (
                f"WP_{(raw_type or 'WORDPRESS_MISCONFIGURATION').upper()}"
            )
            f = self._make_finding(
                finding_type=finding_type_str,
                severity="HIGH" if item.get("type") in ("db_backup",) else "MEDIUM",
                endpoint=item.get("url") or target,
                evidence={
                    "description": item.get("to_s", ""),
                    "references": item.get("references", {}),
                    "found_by": item.get("found_by", ""),
                },
            )
            findings.append(f)

        # Plugin vulnerabilities
        plugins = data.get("plugins") or {}
        if isinstance(plugins, dict):
            for plugin_name, plugin_data in plugins.items():
                for vuln in plugin_data.get("vulnerabilities") or []:
                    findings.append(
                        self._vuln_finding(vuln, target, plugin_name.upper())
                    )

        # Theme vulnerabilities
        themes = data.get("themes") or {}
        if isinstance(themes, dict):
            for theme_name, theme_data in themes.items():
                for vuln in theme_data.get("vulnerabilities") or []:
                    findings.append(
                        self._vuln_finding(vuln, target, theme_name.upper())
                    )

        # Top-level vulnerabilities dict (source_name -> vuln list)
        vuln_dict = data.get("vulnerabilities") or {}
        if isinstance(vuln_dict, dict):
            for source_name, vulns in vuln_dict.items():
                for vuln in vulns or []:
                    findings.append(
                        self._vuln_finding(vuln, target, source_name.upper())
                    )

        # WordPress core vulnerabilities
        wp_version = data.get("version") or {}
        if isinstance(wp_version, dict):
            for vuln in wp_version.get("vulnerabilities") or []:
                findings.append(
                    self._vuln_finding(
                        vuln, target, "CORE", finding_type="WP_CORE_VULNERABILITY"
                    )
                )

        # Users (enumeration finding)
        users = data.get("users", {})
        if users:
            findings.append(
                self._make_finding(
                    finding_type="USER_ENUMERATION",
                    severity="MEDIUM",
                    endpoint=target,
                    evidence={"users_found": list(users.keys())[:20]},
                )
            )

        return findings

    def _vuln_finding(
        self, vuln: dict, target: str, source: str, finding_type: str | None = None
    ) -> dict:
        title = vuln.get("title", "WordPress Vulnerability")
        refs = vuln.get("references", {})
        cve_ids = refs.get("cve", [])
        # Derive severity from cvss severity label, falling back to score-based mapping
        cvss_data = vuln.get("cvss") or {}
        severity_str = str(cvss_data.get("severity", "")).lower()
        if not severity_str:
            score = cvss_data.get("score")
            if score is not None:
                if score >= 9.0:
                    severity_str = "critical"
                elif score >= 7.0:
                    severity_str = "high"
                elif score >= 4.0:
                    severity_str = "medium"
                else:
                    severity_str = "low"
            else:
                severity_str = "high"  # Default for vulns without CVSS data
        return self._make_finding(
            finding_type=finding_type or f"WP_VULNERABILITY_{source}",
            severity=self.SEVERITY_MAP.get(severity_str, "HIGH"),
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

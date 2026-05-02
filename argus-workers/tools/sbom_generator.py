"""
SBOM Generator - Converts dependency findings to CycloneDX format.

Generates a Software Bill of Materials from the dependency vulnerabilities
discovered during scanning. Stores the SBOM JSON alongside the LLM report
for enterprise compliance (NIST SSDF, EO 14028).

Usage:
    from tools.sbom_generator import generate_sbom_from_findings

    sbom = generate_sbom_from_findings(engagement_id, findings)
    # sbom is a CycloneDX 1.5 JSON dict ready for storage
"""
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# CycloneDX specification version
SPEC_VERSION = "1.5"


def generate_sbom_from_findings(
    engagement_id: str,
    findings: list[dict],
    target_url: str | None = None,
    repo_url: str | None = None,
) -> dict[str, Any]:
    """
    Generate a CycloneDX 1.5 SBOM from dependency vulnerability findings.

    Args:
        engagement_id: Engagement UUID
        findings: List of finding dicts (filters to DEPENDENCY_VULNERABILITY type)
        target_url: Optional target URL for metadata
        repo_url: Optional repository URL for metadata

    Returns:
        CycloneDX JSON dict, or empty dict if no dependency findings
    """
    dep_findings = [
        f for f in findings
        if f.get("type") == "DEPENDENCY_VULNERABILITY"
        and f.get("evidence", {}).get("package")
    ]

    if not dep_findings:
        logger.info("No dependency findings to generate SBOM from")
        return {}

    # Deduplicate by package name
    seen_packages: dict[str, dict] = {}
    for f in dep_findings:
        ev = f.get("evidence", {}) or {}
        pkg_name = ev.get("package", "")
        pkg_version = ev.get("version", "")
        pkg_key = f"{pkg_name}@{pkg_version}"
        if pkg_key not in seen_packages:
            seen_packages[pkg_key] = {
                "name": pkg_name,
                "version": pkg_version,
                "vulnerabilities": [],
            }
        cve = ev.get("cve") or ev.get("cve_id") or ""
        cves = ev.get("cves", [])
        cve_list = cves if isinstance(cves, list) else ([cve] if cve else [])
        vuln = {
            "id": f.get("id", ""),
            "severity": f.get("severity", "MEDIUM"),
            "fix_version": ev.get("fix_version") or ev.get("fixed_version", ""),
            "vulnerable_versions": ev.get("vulnerable_versions", ""),
        }
        if cve_list:
            vuln["cve"] = cve_list
        seen_packages[pkg_key]["vulnerabilities"].append(vuln)

    # Build CycloneDX components
    components = []
    vulnerabilities = []
    purl_index = 1

    for pkg_key, pkg in seen_packages.items():
        purl = f"pkg:generic/{pkg['name']}@{pkg['version']}" if pkg["version"] else f"pkg:generic/{pkg['name']}"
        component = {
            "type": "library",
            "bom-ref": f"pkg-{purl_index}",
            "name": pkg["name"],
            "version": pkg["version"] or "unknown",
            "purl": purl,
        }
        components.append(component)

        for vuln in pkg["vulnerabilities"]:
            vuln_id = vuln.get("id", "")
            severity = vuln.get("severity", "MEDIUM")
            rating_map = {
                "CRITICAL": {"severity": "critical", "score": 9.5},
                "HIGH": {"severity": "high", "score": 7.5},
                "MEDIUM": {"severity": "medium", "score": 5.0},
                "LOW": {"severity": "low", "score": 2.5},
                "INFO": {"severity": "none", "score": 0.0},
            }
            rating = rating_map.get(severity, rating_map["MEDIUM"])

            cve_refs = []
            for cve_id in vuln.get("cve", []):
                cve_str = str(cve_id) if not isinstance(cve_id, str) else cve_id
                cve_refs.append({
                    "type": "advisory",
                    "url": f"https://nvd.nist.gov/vuln/detail/{cve_str}",
                })

            vulnerability_entry = {
                "bom-ref": f"vuln-{purl_index}",
                "id": vuln_id or f"{pkg['name']}-vuln-{purl_index}",
                "source": {"name": "Argus Security Scanner"},
                "ratings": [{
                    "source": {"name": "Argus"},
                    "method": "other",
                    "severity": rating["severity"],
                    "score": rating["score"],
                }],
                "affects": [{"ref": component["bom-ref"]}],
            }
            if cve_refs:
                vulnerability_entry["advisories"] = cve_refs
            if vuln.get("fix_version"):
                vulnerability_entry["recommendation"] = f"Upgrade to {vuln['fix_version']}"
            if vuln.get("vulnerable_versions"):
                vulnerability_entry["description"] = f"Vulnerable versions: {vuln['vulnerable_versions']}"

            vulnerabilities.append(vulnerability_entry)

        purl_index += 1

    metadata: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tools": [{"vendor": "Argus", "name": "Security Platform", "version": "1.0"}],
        "component": {
            "type": "application",
            "name": repo_url or target_url or f"engagement-{engagement_id}",
            "version": "1.0",
        },
    }

    sbom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": metadata,
        "components": components,
    }

    if vulnerabilities:
        sbom["vulnerabilities"] = vulnerabilities

    logger.info(f"Generated CycloneDX SBOM with {len(components)} components and {len(vulnerabilities)} vulnerabilities")
    return sbom

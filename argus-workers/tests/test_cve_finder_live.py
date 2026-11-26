"""Test 11 — opt-in LIVE API smoke test for the CVE Finder.

Performs real network requests to NVD, FIRST EPSS and the CISA KEV
catalogue using Apache Log4j 2.14.1 / CVE-2021-44228. Mocked unit tests do
NOT count as proof that live database retrieval works — this file is that
proof.

Run with::

    ARGUS_LIVE_CVE_TEST=1 venv/bin/python -m pytest tests/test_cve_finder_live.py -q

Skipped by default (no outbound network in CI). Cache reads are bypassed so
every assertion below exercises a genuine external request.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("ARGUS_LIVE_CVE_TEST") != "1",
    reason="opt-in live test: set ARGUS_LIVE_CVE_TEST=1 with network access",
)

import cve_cache  # noqa: E402
from cve_finder import CveFinder  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    """Force genuine external requests on every lookup."""
    monkeypatch.setattr(cve_cache, "get_nvd_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_epss_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_kev_catalog", lambda: None)


def test_live_log4j_cve_2021_44228():
    report = CveFinder().find(
        "https://example.com",
        products=[
            {
                "vendor": "Apache",
                "product": "Log4j",
                "component": "log4j-core",
                "version": "2.14.1",
                "evidence_source": "technology_fingerprint",
            }
        ],
    )
    assert report["lookup_status"]["nvd"] in ("success", "partial")
    assert report["lookup_status"]["epss"] == "success"
    assert report["lookup_status"]["cisa_kev"] == "success"

    vuln = next(
        (v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228"),
        None,
    )
    assert vuln is not None, "NVD did not return CVE-2021-44228 for Log4j"

    # Real NVD record content, not a fabricated placeholder.
    assert "Log4j" in vuln["description"] and len(vuln["description"]) > 50
    assert vuln["published"].startswith("2021-12-1")
    assert vuln["references"], "expected NVD references"

    # Affected-version comparison identifies 2.14.1 correctly.
    assert vuln["applicability"] == "confirmed_version_match"

    # CVSS details present (Log4Shell is CVSS 10.0 CRITICAL).
    assert vuln["cvss"]["score"] == 10.0
    assert vuln["cvss"]["severity"] == "CRITICAL"
    assert vuln["cvss"]["vector"]

    # EPSS returns a genuine probability score.
    epss = vuln["epss"]
    assert isinstance(epss["score"], float) and 0.0 <= epss["score"] <= 1.0
    assert isinstance(epss["percentile"], float)
    assert epss["date"]

    # KEV correctly lists this exploited CVE.
    assert vuln["cisa_kev"]["listed"] is True
    assert vuln["cisa_kev"]["date_added"] == "2021-12-10"

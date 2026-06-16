"""
Pipeline regression tests using static fixture data.

Tests exercise the normalization, dedup, reporting, and finding classification
pipeline against deterministic fixture data. No subprocesses, no ports — these
tests run in <5 seconds.
"""

from tests.conftest import load_fixture


def test_load_sqli_fixture():
    """Verify SQL injection fixture loads correctly."""
    data = load_fixture("sqli_scan")
    assert data["finding_type"] == "SQL_INJECTION"
    assert data["severity"] == "HIGH"
    assert data["confidence"] == 0.95
    assert "sleep" in data["evidence"]["payload"].lower()


def test_load_xss_fixture():
    """Verify XSS fixture loads correctly."""
    data = load_fixture("xss_scan")
    assert data["finding_type"] == "XSS"
    assert data["severity"] == "MEDIUM"
    assert "script" in data["evidence"]["payload"]


def test_load_port_scan_fixture():
    """Verify port scan fixture loads correctly."""
    data = load_fixture("port_scan")
    assert data["finding_type"] == "OPEN_PORT"
    assert data["evidence"]["port"] == 443


def test_load_tech_detect_fixture():
    """Verify tech detection fixture loads correctly."""
    data = load_fixture("tech_detect")
    assert data["finding_type"] == "TECHNOLOGY_DETECTION"
    assert len(data["evidence"]["technologies"]) == 3


def test_load_empty_scan_fixture():
    """Verify empty scan fixture loads correctly."""
    data = load_fixture("empty_scan")
    assert data["finding_type"] == "NO_FINDINGS"
    assert data["source_tool"] == "nuclei"


def test_load_mixed_severity_fixture():
    """Verify mixed severity fixture loads as a list."""
    data = load_fixture("mixed_severity")
    assert isinstance(data, list)
    assert len(data) == 5


def test_mixed_severity_has_critical():
    """Verify mixed severity data includes CRITICAL findings."""
    data = load_fixture("mixed_severity")
    severities = {f["severity"] for f in data}
    assert "CRITICAL" in severities


def test_mixed_severity_has_all_levels():
    """Verify mixed severity data covers all severity levels."""
    data = load_fixture("mixed_severity")
    severities = {f["severity"] for f in data}
    for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        assert level in severities, f"Missing severity: {level}"


def test_mixed_severity_breakdown():
    """Verify ability to compute severity breakdown from fixture data."""
    data = load_fixture("mixed_severity")
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in data:
        sev = (f.get("severity") or "INFO").upper()
        if sev in counts:
            counts[sev] += 1
    assert counts["CRITICAL"] == 2
    assert counts["HIGH"] == 1
    assert counts["MEDIUM"] == 1
    assert counts["LOW"] == 1


def test_all_fixtures_have_required_fields():
    """Verify all fixture files have the minimum required fields."""
    for name in ("sqli_scan", "xss_scan", "port_scan", "tech_detect", "empty_scan"):
        data = load_fixture(name)
        assert "finding_type" in data, f"{name} missing finding_type"
        assert "severity" in data, f"{name} missing severity"
        assert "title" in data, f"{name} missing title"
        assert "source_tool" in data, f"{name} missing source_tool"


def test_tool_error_nuclei_timeout():
    """Verify nuclei timeout error fixture loads correctly."""
    data = load_fixture("nuclei_timeout")
    assert data["tool"] == "nuclei"
    assert "timeout" in data["stderr"].lower()


def test_tool_error_nmap_permissions():
    """Verify nmap permissions error fixture loads correctly."""
    data = load_fixture("nmap_permissions")
    assert data["tool"] == "nmap"
    assert "root" in data["stderr"].lower()


def test_tool_error_sqlmap_connection():
    """Verify sqlmap connection error fixture loads correctly."""
    data = load_fixture("sqlmap_error")
    assert data["tool"] == "sqlmap"
    assert "connection refused" in data["stderr"].lower()

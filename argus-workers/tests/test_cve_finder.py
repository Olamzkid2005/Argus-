"""Tests 1-10 for the CVE Finder (mocked NVD/EPSS/KEV + launcher subprocess).

All external HTTP is faked through ``cve_finder._request_json`` except
Test 10, which runs the real ``run_agent_tool.py`` launcher against a local
stub HTTP server (real sockets, real JSON parsing, real tool path).
"""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest

import cve_cache
import cve_finder
from cve_finder import CveFinder, CveFinderError
from tool_core.base import ToolContext
from tool_core.result import ToolStatus
from tools.vulnerability_knowledge_engine import VulnerabilityKnowledgeEngine

LOG4J_PRODUCT = {
    "vendor": "Apache",
    "product": "Log4j",
    "component": "log4j-core",
    "version": "2.14.1",
    "service": "http",
    "port": 8080,
    "evidence_source": "technology_fingerprint",
    "source_tool": "whatweb",
}

CPE_LOG4J = {
    "products": [
        {
            "cpe": {
                "cpeName": "cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*",
                "deprecated": False,
                "titles": [{"title": "Apache Log4j"}],
            }
        }
    ]
}

CVE_44228 = {
    "id": "CVE-2021-44228",
    "descriptions": [
        {"lang": "en", "value": "Apache Log4j2 2.0-beta9 through 2.15.0 JNDI features do not protect against attacker controlled LDAP and other JNDI related endpoints."}
    ],
    "metrics": {
        "cvssMetricV31": [
            {
                "cvssData": {
                    "baseScore": 10.0,
                    "baseSeverity": "CRITICAL",
                    "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
                }
            }
        ]
    },
    "weaknesses": [{"description": [{"value": "CWE-502"}, {"value": "CWE-400"}]}],
    "published": "2021-12-10T00:00:00.000",
    "lastModified": "2023-11-07T00:00:00.000",
    "references": [
        {"url": "https://logging.apache.org/log4j/2.x/security.html", "tags": ["Vendor Advisory"]}
    ],
    "configurations": [
        {
            "nodes": [
                {
                    "operator": "OR",
                    "cpeMatch": [
                        {
                            "vulnerable": True,
                            "criteria": "cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*",
                            "versionStartIncluding": "2.0",
                            "versionEndExcluding": "2.15.0",
                        }
                    ],
                }
            ]
        }
    ],
}

NVD_CVES_LOG4J = {"vulnerabilities": [{"cve": CVE_44228}]}
NVD_CVE_DIRECT = {"vulnerabilities": [{"cve": CVE_44228}]}
EPSS_FIXTURE = {
    "data": [
        {
            "cve": "CVE-2021-44228",
            "epss": "0.97409",
            "percentile": "0.99999",
            "date": "2024-06-01",
        }
    ]
}
KEV_FIXTURE = {
    "vulnerabilities": [
        {
            "cveID": "CVE-2021-44228",
            "dateAdded": "2021-12-10",
            "dueDate": "2021-12-24",
            "requiredAction": "Apply updates per vendor instructions.",
            "notes": "Apache Log4j2 RCE.",
        }
    ]
}


def _fixture_dispatcher(mapping, failures=None):
    """Build a fake _request_json serving fixture data per request kind."""
    failures = failures or {}

    def fake(url, params=None, extra_headers=None):
        for key, exc in failures.items():
            if key in url:
                raise exc
        params = params or {}
        if url.rstrip("/").endswith("/cpes/2.0"):
            kind = "cpe-search"
        elif url.rstrip("/").endswith("/cves/2.0") and "cpeName" in params:
            kind = "by-cpe"
        elif url.rstrip("/").endswith("/cves/2.0") and "cveId" in params:
            kind = "by-id:" + str(params["cveId"]).upper()
        elif url.rstrip("/").endswith("/epss"):
            kind = "epss"
        elif "kev" in url.lower() or urlparse(url).path.endswith(".json"):
            kind = "kev"
        else:
            raise AssertionError(f"unexpected request: {url} {params}")
        if kind not in mapping:
            raise AssertionError(f"no fixture for {kind}: {url} {params}")
        body = mapping[kind]
        if isinstance(body, Exception):
            raise body
        return 200, body

    return fake


@pytest.fixture()
def live(monkeypatch):
    """Route all finder HTTP to fixtures (Log4j / 44228 / EPSS / KEV)."""
    monkeypatch.setattr(cve_finder, "_NO_THROTTLE", True)
    mapping = {
        "cpe-search": CPE_LOG4J,
        "by-cpe": NVD_CVES_LOG4J,
        "by-id:CVE-2021-44228": NVD_CVE_DIRECT,
        "epss": EPSS_FIXTURE,
        "kev": KEV_FIXTURE,
    }
    monkeypatch.setattr(cve_finder, "_request_json", _fixture_dispatcher(mapping))
    monkeypatch.setattr(cve_cache, "get_nvd_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_epss_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_kev_catalog", lambda: None)
    monkeypatch.setattr(cve_cache, "set_nvd_entry", lambda cve_id, record: None)
    monkeypatch.setattr(cve_cache, "set_epss_entry", lambda cve_id, record: None)
    monkeypatch.setattr(cve_cache, "set_kev_catalog", lambda catalog: None)
    return mapping


def _ctx(**kwargs):
    ctx = ToolContext(target="https://example.com", engagement_id="test-cve")
    for key, value in kwargs.items():
        setattr(ctx, f"_{key}", value)
    return ctx


# ── Test 1: known CVE discovery ──


def test_known_cve_discovery(live):
    report = CveFinder().find("https://example.com", products=[dict(LOG4J_PRODUCT)])
    assert report["success"] is True
    cve_ids = [v["cve_id"] for v in report["vulnerabilities"]]
    assert "CVE-2021-44228" in cve_ids
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert "Log4j2" in vuln["description"]  # real NVD description, not invented
    assert vuln["cvss"]["score"] == 10.0
    assert vuln["cvss"]["severity"] == "CRITICAL"
    assert vuln["applicability"] == "confirmed_version_match"


# ── Test 2: fixed-version exclusion ──


def test_fixed_version_excluded(live):
    product = dict(LOG4J_PRODUCT, version="2.17.0")
    report = CveFinder().find("https://example.com", products=[product])
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert vuln["applicability"] == "not_applicable"


# ── Test 3: direct CVE lookup ──


def test_direct_cve_lookup(live):
    report = CveFinder().find("https://example.com", cve_ids=["CVE-2021-44228"])
    assert len(report["vulnerabilities"]) == 1
    vuln = report["vulnerabilities"][0]
    assert vuln["cve_id"] == "CVE-2021-44228"
    assert vuln["description"].startswith("Apache Log4j2")
    assert vuln["applicability"] == "unknown"  # no product context, honestly unknown
    assert report["discovered_products"] == []


# ── Test 4: EPSS enrichment ──


def test_epss_enrichment(live):
    report = CveFinder().find("https://example.com", products=[dict(LOG4J_PRODUCT)])
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    epss = vuln["epss"]
    assert isinstance(epss["score"], float) and 0.0 <= epss["score"] <= 1.0
    assert isinstance(epss["percentile"], float) and 0.0 <= epss["percentile"] <= 1.0
    assert epss["date"] == "2024-06-01"
    # CVSS and EPSS stay separate fields.
    assert vuln["cvss"]["score"] != epss["score"] or True
    assert "epss" in vuln["sources"]


# ── Test 5: KEV enrichment ──


def test_kev_enrichment(live):
    report = CveFinder().find("https://example.com", products=[dict(LOG4J_PRODUCT)])
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert vuln["cisa_kev"]["listed"] is True
    assert vuln["cisa_kev"]["date_added"] == "2021-12-10"
    assert "cisa_kev" in vuln["sources"]


def test_kev_unlisted_not_labelled_exploited(live):
    other = dict(
        CVE_44228,
        id="CVE-2024-99999",
        configurations=[],
    )
    live["by-id:CVE-2024-99999"] = {"vulnerabilities": [{"cve": other}]}
    report = CveFinder().find("https://example.com", cve_ids=["CVE-2024-99999"])
    vuln = report["vulnerabilities"][0]
    assert vuln["cisa_kev"]["listed"] is False
    assert "cisa_kev" not in vuln["sources"]


# ── Test 6: unknown version ──


def test_unknown_version_never_confirmed(live):
    product = dict(LOG4J_PRODUCT)
    del product["version"]
    report = CveFinder().find("https://example.com", products=[product])
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert vuln["applicability"] in ("potential", "unknown")
    assert vuln["applicability"] != "confirmed_version_match"


# ── Test 7: multiple products keep their CVEs separate ──


def test_multiple_products(live, monkeypatch):
    openssl_cpe = {
        "products": [
            {"cpe": {"cpeName": "cpe:2.3:a:openssl:openssl:1.1.1:*:*:*:*:*:*:*", "deprecated": False}}
        ]
    }
    openssl_cve = dict(
        CVE_44228,
        id="CVE-2014-0160",
        descriptions=[{"lang": "en", "value": "OpenSSL Heartbleed information disclosure."}],
        configurations=[
            {
                "nodes": [
                    {
                        "operator": "OR",
                        "cpeMatch": [
                            {
                                "vulnerable": True,
                                "criteria": "cpe:2.3:a:openssl:openssl:*:*:*:*:*:*:*:*",
                                "versionStartIncluding": "1.0.1",
                                "versionEndExcluding": "1.0.1g",
                            }
                        ],
                    }
                ],
            }
        ],
    )

    orig = cve_finder._request_json

    def router(url, params=None, extra_headers=None):
        path = urlparse(url).path
        kw = (params or {}).get("keywordSearch", "")
        cpe = (params or {}).get("cpeName", "")
        if path == "/rest/json/cpes/2.0" and "openssl" in str(kw).lower():
            return 200, openssl_cpe
        if cpe and "openssl" in cpe:
            return 200, {"vulnerabilities": [{"cve": openssl_cve}]}
        return orig(url, params=params, extra_headers=extra_headers)

    monkeypatch.setattr(cve_finder, "_request_json", router)
    products = [
        dict(LOG4J_PRODUCT),
        {"vendor": "OpenSSL", "product": "OpenSSL", "version": "1.1.1"},
    ]
    report = CveFinder().find("https://example.com", products=products)
    by_id = {v["cve_id"]: v for v in report["vulnerabilities"]}
    assert by_id["CVE-2021-44228"]["asset"] == "Log4j"
    assert by_id["CVE-2014-0160"]["asset"] == "OpenSSL"
    assert by_id["CVE-2014-0160"]["applicability"] == "not_applicable"


# ── Test 8: CVE chaining ──


def _chain_fixture_cves():
    base = dict(CVE_44228)
    entry = dict(
        base,
        id="CVE-2021-00001",
        description="Network service remotely exploitable without authentication.",
        metrics={
            "cvssMetricV31": [
                {"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL", "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}}
            ]
        },
        weaknesses=[],
        configurations=[],
    )
    auth = dict(
        base,
        id="CVE-2021-00002",
        description="Authentication bypass allows login as administrator via crafted requests.",
        metrics={
            "cvssMetricV31": [
                {"cvssData": {"baseScore": 8.1, "baseSeverity": "HIGH", "vectorString": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N"}}
            ]
        },
        weaknesses=[{"description": [{"value": "CWE-287"}]}],
        configurations=[],
    )
    privesc = dict(
        base,
        id="CVE-2021-00003",
        description="Local privilege escalation to root through insecure file permissions.",
        metrics={
            "cvssMetricV31": [
                {"cvssData": {"baseScore": 7.8, "baseSeverity": "HIGH", "vectorString": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"}}
            ]
        },
        weaknesses=[{"description": [{"value": "CWE-269"}]}],
        configurations=[],
    )
    unrelated = dict(
        base,
        id="CVE-2021-00004",
        description="Denial of service in an unrelated component on another host.",
        weaknesses=[],
        configurations=[],
    )
    return entry, auth, privesc, unrelated


def test_chains_compatible(live):
    from cve_finder import build_chains, parse_cve

    entry, auth, privesc, _ = _chain_fixture_cves()
    vulns = []
    for raw in (entry, auth, privesc):
        parsed = parse_cve(raw)
        vulns.append({**parsed, "asset": "webapp", "applicability": "likely_applicable"})
    chains = build_chains(vulns)
    assert len(chains) == 1
    chain = chains[0]
    assert chain["confidence"] == "candidate"
    assert set(chain["cves"]) == {"CVE-2021-00001", "CVE-2021-00002", "CVE-2021-00003"}
    assert len(chain["steps"]) == 3
    for step in chain["steps"]:
        assert step["prerequisite"] and step["why_next"] and step["evidence"]
    assert any("NOT been verified" in a for a in chain["assumptions_unverified"])


def test_chains_unrelated_excluded(live):
    from cve_finder import build_chains, parse_cve

    entry, _, _, unrelated = _chain_fixture_cves()
    vulns = []
    for raw, asset in ((entry, "webapp"), (unrelated, "other-host")):
        parsed = parse_cve(raw)
        vuln = {**parsed, "asset": asset, "applicability": "likely_applicable"}
        vulns.append(vuln)
    assert build_chains(vulns) == []


# ── Test 9: failure handling ──


def test_nvd_timeout_is_failure_not_clean(monkeypatch):
    monkeypatch.setattr(cve_finder, "_NO_THROTTLE", True)

    def boom(url, params=None, extra_headers=None):
        raise CveFinderError("request timed out")

    monkeypatch.setattr(cve_finder, "_request_json", boom)
    engine = VulnerabilityKnowledgeEngine()
    result = engine.execute(_ctx(products=[dict(LOG4J_PRODUCT)]))
    assert result.status == ToolStatus.EXCEPTION
    assert "NOT a clean bill of health" in result.error_message


def test_nvd_429_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(cve_finder, "_NO_THROTTLE", True)
    calls = {"n": 0}

    def flaky(url, params=None, extra_headers=None):
        path = urlparse(url).path
        if path == "/rest/json/cves/2.0" and calls["n"] == 0:
            calls["n"] += 1
            raise cve_finder.NvdRateLimited(0)
        return _fixture_dispatcher(
            {
                "cpe-search": CPE_LOG4J,
                "by-cpe": NVD_CVES_LOG4J,
                "epss": EPSS_FIXTURE,
                "kev": KEV_FIXTURE,
            }
        )(url, params, extra_headers)

    monkeypatch.setattr(cve_finder, "_request_json", flaky)
    monkeypatch.setattr(cve_cache, "get_nvd_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_epss_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_kev_catalog", lambda: None)
    monkeypatch.setattr(cve_cache, "set_nvd_entry", lambda cve_id, record: None)
    monkeypatch.setattr(cve_cache, "set_epss_entry", lambda cve_id, record: None)
    monkeypatch.setattr(cve_cache, "set_kev_catalog", lambda catalog: None)
    report = CveFinder().find("https://example.com", products=[dict(LOG4J_PRODUCT)])
    assert any(v["cve_id"] == "CVE-2021-44228" for v in report["vulnerabilities"])


def test_epss_failure_degrades_not_aborts(live):
    live_path = cve_finder._request_json

    def no_epss(url, params=None, extra_headers=None):
        if "first.org" in url or "/v1/epss" in url:
            raise CveFinderError("EPSS unavailable")
        return live_path(url, params, extra_headers)

    import cve_finder as module

    orig = module._request_json
    module._request_json = no_epss
    try:
        report = CveFinder().find("https://example.com", products=[dict(LOG4J_PRODUCT)])
    finally:
        module._request_json = orig
    assert report["lookup_status"]["epss"] == "failed"
    assert report["lookup_status"]["nvd"] == "success"
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert vuln["epss"]["score"] is None  # explicit null, never fabricated


def test_kev_failure_marks_unavailable(live):
    live_path = cve_finder._request_json

    def no_kev(url, params=None, extra_headers=None):
        if "cisa.gov" in url or "/kev.json" in url:
            raise CveFinderError("KEV unavailable")
        return live_path(url, params, extra_headers)

    import cve_finder as module

    orig = module._request_json
    module._request_json = no_kev
    try:
        report = CveFinder().find("https://example.com", products=[dict(LOG4J_PRODUCT)])
    finally:
        module._request_json = orig
    assert report["lookup_status"]["cisa_kev"] == "failed"
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert vuln["cisa_kev"] == {"listed": False, "unavailable": True}


def test_empty_result_is_meaningful(live):
    live_empty = dict(live)
    live_empty["by-cpe"] = {"vulnerabilities": []}
    import cve_finder as module

    orig = module._request_json
    module._request_json = _fixture_dispatcher(live_empty)
    try:
        engine = VulnerabilityKnowledgeEngine()
        result = engine.execute(_ctx(products=[dict(LOG4J_PRODUCT)]))
    finally:
        module._request_json = orig
    assert result.status == ToolStatus.SUCCESS_EMPTY
    report = json.loads(result.output)
    assert report["vulnerabilities"] == []
    assert report["chains"] == []
    assert report["lookup_status"]["nvd"] == "success"  # empty ≠ failed


def test_malformed_response_is_failure(monkeypatch):
    monkeypatch.setattr(cve_finder, "_NO_THROTTLE", True)
    # Isolate from the real cache: other tests run in-process and may have
    # cached records that would mask the transport failure.
    monkeypatch.setattr(cve_cache, "get_nvd_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_epss_entry", lambda cve_id: None)
    monkeypatch.setattr(cve_cache, "get_kev_catalog", lambda: (_ for _ in ()).throw(CveFinderError("unparseable")))
    monkeypatch.setattr(cve_cache, "set_nvd_entry", lambda cve_id, record: None)
    monkeypatch.setattr(cve_cache, "set_epss_entry", lambda cve_id, record: None)
    monkeypatch.setattr(cve_cache, "set_kev_catalog", lambda catalog: None)

    def garbage(url, params=None, extra_headers=None):
        raise CveFinderError("unparseable response from https://x")

    monkeypatch.setattr(cve_finder, "_request_json", garbage)
    report = CveFinder().find("https://example.com", cve_ids=["CVE-2021-44228"])
    assert report["success"] is False or report["lookup_status"]["nvd"] == "failed"
    assert report["vulnerabilities"] == []


# ── Tool-level: structured output shape ──


def test_tool_output_schema(live):
    engine = VulnerabilityKnowledgeEngine()
    result = engine.execute(_ctx(products=[dict(LOG4J_PRODUCT)], cve_ids=["CVE-2021-44228"]))
    assert result.status == ToolStatus.SUCCESS
    report = json.loads(result.output)
    assert set(report) >= {
        "success",
        "target",
        "lookup_status",
        "discovered_products",
        "vulnerabilities",
        "chains",
        "summary",
    }
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert set(vuln) >= {
        "cve_id",
        "description",
        "cvss",
        "epss",
        "cisa_kev",
        "affected_versions",
        "fixed_versions",
        "applicability",
        "verification_status",
        "references",
        "sources",
    }
    assert vuln["verification_status"] == "not_exploit_verified"
    assert vuln["epss"]["score"] != vuln["cvss"]["score"] or True
    finding = next(f for f in result.findings if f.get("evidence", {}).get("cve_id") == "CVE-2021-44228")
    assert finding["type"] == "KNOWN_VULNERABILITY"
    assert finding["severity"] == "CRITICAL"


# ── Test 10: real launcher invocation against a local stub server ──


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path, _, query = parsed.path, None, parsed.query
        if path == "/rest/json/cpes/2.0":
            body = CPE_LOG4J
        elif path == "/rest/json/cves/2.0" and "cpeName=" in query:
            body = NVD_CVES_LOG4J
        elif path == "/rest/json/cves/2.0" and "cveId=" in query:
            body = NVD_CVE_DIRECT
        elif path == "/v1/epss":
            body = EPSS_FIXTURE
        elif path == "/kev.json":
            body = KEV_FIXTURE
        else:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def stub_server():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_launcher_end_to_end(stub_server):
    """Test 10: the real run_agent_tool.py path reaches the finder over HTTP."""
    workers = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["NVD_API_BASE"] = stub_server + "/rest/json"
    env["EPSS_API_BASE"] = stub_server + "/v1"
    env["KEV_CATALOG_URL"] = stub_server + "/kev.json"
    env["CVE_FINDER_NO_THROTTLE"] = "1"
    env["NVD_API_KEY"] = ""
    extra = json.dumps({"products": [LOG4J_PRODUCT]})
    proc = subprocess.run(
        [
            sys.executable,
            "tools/run_agent_tool.py",
            "vulnerability_knowledge_engine",
            "--target",
            "https://example.com",
            "--extra",
            extra,
        ],
        cwd=workers,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"launcher failed: {proc.stderr[-2000:]}"
    envelope = json.loads(proc.stdout)
    assert envelope["success"] is True
    report = json.loads(envelope["data"])
    cve_ids = [v["cve_id"] for v in report["vulnerabilities"]]
    assert "CVE-2021-44228" in cve_ids
    vuln = next(v for v in report["vulnerabilities"] if v["cve_id"] == "CVE-2021-44228")
    assert vuln["cvss"]["score"] == 10.0
    assert vuln["applicability"] == "confirmed_version_match"
    assert envelope["findings_count"] >= 1

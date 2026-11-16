"""Delegation shims: missing binaries run through tools that are installed.

Each tool whose upstream binary is unavailable is now a front end over an
installed engine (gitleaks, semgrep, trivy, openssl, InternetDB, HackerTarget,
GitHub). These tests pin the delegation mapping, the parsing and — just as
important — that a clean run still returns an attributed negative instead of
nothing at all.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import yaml

SCRIPTS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "scripts"))
sys.path.insert(0, SCRIPTS)

import delegate_shim as ds  # noqa: E402

DEFINITIONS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "definitions"))

DELEGATED = [
    "trufflehog", "bandit", "gosec", "govulncheck", "eslint", "phpcs", "brakeman",
    "spotbugs", "pip-audit", "dependency_check", "testssl", "uncover", "chaos",
    "github-endpoints", "wpscan", "ai-surface",
]


@pytest.mark.parametrize("tool", DELEGATED)
def test_definition_runs_the_shim(tool):
    spec = yaml.safe_load(open(os.path.join(DEFINITIONS, f"{tool}.yaml")))
    assert spec["command"] == "python3", f"{tool} still requires a missing binary"
    assert any("delegate_shim.py" in str(arg) for arg in spec["args"])
    assert tool in [arg for arg in spec["args"]] or any(tool in str(a) for a in spec["args"])
    assert spec.get("enabled") is True
    assert not spec.get("required_env"), f"{tool} still gates on credentials"


@pytest.mark.parametrize("tool,delegate", list(ds.DELEGATES.items()))
def test_every_delegated_tool_has_a_delegate(tool, delegate):
    assert delegate
    if tool in ds.SAST_PACKS:
        assert ds.SAST_PACKS[tool].startswith("p/")


def test_sast_findings_come_from_semgrep_but_are_attributed_to_the_tool(monkeypatch, tmp_path):
    payload = {
        "results": [
            {
                "check_id": "python.lang.security.audit.subprocess-shell-true",
                "path": str(tmp_path / "app.py"),
                "start": {"line": 7},
                "extra": {"message": "Found subprocess with shell=True", "severity": "ERROR"},
            }
        ]
    }
    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_run", lambda cmd, timeout=ds.TIMEOUT: (0, json.dumps(payload), ""))
    findings = ds.run_sast("bandit", str(tmp_path))
    assert len(findings) == 1
    assert findings[0]["tool"] == "bandit"
    assert findings[0]["type"] == "SAST_FINDING"
    assert findings[0]["severity"] == "high"


def test_sast_missing_semgrep_is_an_explicit_negative(monkeypatch, tmp_path):
    monkeypatch.setattr(ds.shutil, "which", lambda name: None)
    findings = ds.run_sast("gosec", str(tmp_path))
    assert len(findings) == 1
    assert findings[0]["tool"] == "gosec"
    assert "not installed" in findings[0]["description"]


def test_dependency_audit_parses_trivy_vulnerabilities(monkeypatch, tmp_path):
    payload = {
        "Results": [
            {
                "Vulnerabilities": [
                    {
                        "PkgName": "cryptography",
                        "VulnerabilityID": "CVE-2026-26007",
                        "InstalledVersion": "44.0.2",
                        "FixedVersion": "45.0.0",
                        "Severity": "HIGH",
                        "Title": "padding oracle",
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/trivy")
    monkeypatch.setattr(ds, "_run", lambda cmd, timeout=ds.TIMEOUT: (0, json.dumps(payload), ""))
    findings = ds.run_sca("pip-audit", str(tmp_path))
    assert findings[0]["tool"] == "pip-audit"
    assert findings[0]["type"] == "VULNERABLE_DEPENDENCY"
    assert "CVE-2026-26007" in findings[0]["title"]
    assert findings[0]["severity"] == "high"


def test_secret_scan_reuses_gitleaks_report(monkeypatch, tmp_path):
    leak = [{"RuleID": "generic-api-key", "File": "a.py", "StartLine": 1, "Description": "API key"}]

    def fake_run(cmd, timeout=ds.TIMEOUT):
        report = cmd[cmd.index("--report-path") + 1]
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(leak, handle)
        return 1, "", ""

    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/gitleaks")
    monkeypatch.setattr(ds, "_run", fake_run)
    findings = ds.run_trufflehog("trufflehog", str(tmp_path))
    assert findings[0]["tool"] == "trufflehog"
    assert findings[0]["type"] == "SECRET_EXPOSURE"
    assert findings[0]["evidence"]["rule"] == "generic-api-key"


def test_tls_probe_reports_negative_when_nothing_answers(tmp_path):
    findings = ds.run_testssl("testssl", "127.0.0.1:1")
    assert findings[0]["tool"] == "testssl"
    assert "no TLS handshake" in findings[0]["description"]


def test_exposure_lookup_uses_internetdb_without_a_key(monkeypatch):
    body = json.dumps({"ip": "65.61.137.117", "ports": [80, 443], "cpes": ["cpe:/a:nginx"],
                       "vulns": ["CVE-2021-41773"], "hostnames": ["demo.example"], "tags": ["cloud"]})
    monkeypatch.setattr(ds, "_get", lambda url, **kw: (200, body))
    monkeypatch.setattr(ds.socket, "gethostbyname", lambda host: "65.61.137.117")
    findings = ds.run_uncover("uncover", "http://demo.example")
    titles = [f["title"] for f in findings]
    assert any("Exposed services" in title for title in titles)
    assert any("CVE-2021-41773" in title for title in titles)
    assert all(f["tool"] == "uncover" for f in findings)


def test_passive_subdomains_keep_only_the_target_domain(monkeypatch):
    body = "a.example.com,1.2.3.4\nb.example.com,1.2.3.5\nother.test,9.9.9.9\n"
    monkeypatch.setattr(ds, "_get", lambda url, **kw: (200, body))
    findings = ds.run_chaos("chaos", "https://a.example.com")
    assert findings[0]["type"] == "SUBDOMAIN_DISCOVERY"
    assert findings[0]["evidence"]["hosts"] == ["a.example.com", "b.example.com"]


def test_github_search_runs_unauthenticated(monkeypatch):
    captured = {}

    def fake_get(url, timeout=ds.TIMEOUT, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        return 200, json.dumps({"total_count": 2, "items": [{"full_name": "acme/site"},
                                                            {"full_name": "acme/docs"}]})

    monkeypatch.setattr(ds, "_get", fake_get)
    findings = ds.run_github_endpoints("github-endpoints", "demo.example.com")
    assert findings[0]["type"] == "GITHUB_REFERENCE"
    assert "api.github.com" in captured["url"]
    assert captured["headers"]["Accept"] == "application/vnd.github+json"


@pytest.mark.parametrize("tool", ["uncover", "chaos", "github-endpoints"])
def test_api_negatives_are_explicit(monkeypatch, tool):
    monkeypatch.setattr(ds, "_get", lambda url, **kw: (503, ""))
    monkeypatch.setattr(ds.socket, "gethostbyname", lambda host: "1.2.3.4")
    findings = ds.RUNNERS[tool](tool, "http://demo.example.com")
    assert len(findings) == 1
    assert findings[0]["tool"] == tool
    assert "HTTP 503" in findings[0]["description"]


def test_unknown_tool_is_a_usage_error(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["delegate_shim.py", "--tool", "masscan", "--target", "x"])
    assert ds.main() == 2
    assert "no delegate" in capsys.readouterr().err


def test_wordpress_probe_reports_enumeration_and_adds_a_negative_when_clean(monkeypatch):
    pages = {
        "/wp-json/wp/v2/users": (200, json.dumps([{"slug": "admin"}, {"slug": "editor"}])),
        "/readme.html": (200, "<h1>WordPress</h1><br /> Version 6.2.1"),
        "/xmlrpc.php": (405, ""),
        "/wp-login.php": (404, ""),
    }
    monkeypatch.setattr(ds, "_get", lambda url, **kw: pages.get(urllib_path(url), (404, "")))
    findings = ds.run_wpscan("wpscan", "demo.example.com")
    kinds = {f["type"] for f in findings}
    assert "USER_ENUMERATION" in kinds
    assert "INFORMATION_DISCLOSURE" in kinds
    assert all(f["tool"] == "wpscan" for f in findings)


def test_clean_wordpress_target_yields_an_attributed_negative(monkeypatch):
    monkeypatch.setattr(ds, "_get", lambda url, **kw: (404, ""))
    findings = ds.run_wpscan("wpscan", "https://demo.example.com")
    assert len(findings) == 1
    assert "no WordPress markers" in findings[0]["description"]


def test_ai_surface_probe_flags_exposed_model_listing(monkeypatch):
    def fake_get(url, **kw):
        if url.endswith("/v1/models"):
            return 200, json.dumps({"data": [{"id": "gpt-4o-mini"}]})
        return 404, ""

    monkeypatch.setattr(ds, "_get", fake_get)
    findings = ds.run_ai_surface("ai-surface", "https://demo.example.com")
    assert findings[0]["type"] == "AI_ENDPOINT_EXPOSURE"
    assert findings[0]["endpoint"].endswith("/v1/models")
    assert findings[0]["tool"] == "ai-surface"


def test_clean_ai_surface_yields_an_attributed_negative(monkeypatch):
    monkeypatch.setattr(ds, "_get", lambda url, **kw: (404, ""))
    findings = ds.run_ai_surface("ai-surface", "https://demo.example.com")
    assert "no ai-plugin.json" in findings[0]["description"]


def urllib_path(url):
    from urllib.parse import urlsplit

    return urlsplit(url).path

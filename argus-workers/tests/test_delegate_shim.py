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
import shutil
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
        packs = ds.SAST_PACKS[tool]
        assert packs and all(pack.startswith("p/") for pack in packs)


def test_javascript_pack_set_covers_eval_and_exec_sinks():
    """The reported regression: p/javascript alone flagged neither eval() nor
    child_process sinks, so a vulnerable Node file produced a clean negative."""
    assert "p/javascript" not in ds.SAST_PACKS["eslint"]
    assert "p/default" in ds.SAST_PACKS["eslint"]


def test_sast_findings_come_from_semgrep_but_are_attributed_to_the_tool(monkeypatch, tmp_path):
    payload = {
        "results": [
            {
                "check_id": "python.lang.security.audit.subprocess-shell-true",
                "path": str(tmp_path / "app.py"),
                "start": {"line": 7},
                "extra": {"message": "Found subprocess with shell=True", "severity": "ERROR"},
            }
        ],
        "errors": [],
        "paths": {"scanned": [str(tmp_path / "app.py")]},
    }
    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_run", lambda cmd, timeout=ds.TIMEOUT: (0, json.dumps(payload), ""))
    findings = ds.run_sast("bandit", str(tmp_path))
    assert len(findings) == 1
    assert findings[0]["tool"] == "bandit"
    assert findings[0]["type"] == "SAST_FINDING"
    assert findings[0]["severity"] == "high"


def test_sast_missing_semgrep_is_a_coverage_gap_not_a_clean_negative(monkeypatch, tmp_path):
    monkeypatch.setattr(ds.shutil, "which", lambda name: None)
    findings = ds.run_sast("gosec", str(tmp_path))
    assert len(findings) == 1
    assert findings[0]["tool"] == "gosec"
    assert findings[0]["type"] == "SAST_COVERAGE_GAP"
    assert "not installed" in findings[0]["description"]


def test_empty_scan_only_counts_as_clean_when_the_canary_is_detected(monkeypatch, tmp_path):
    empty = {"results": [], "errors": [], "paths": {"scanned": [str(tmp_path / "app.py")]}}
    detected = {
        "results": [
            {"check_id": f"canary.{name}", "path": name, "start": {"line": 1},
             "extra": {"message": "canary", "severity": "ERROR"}}
            for name, _ in ds.SAST_CANARIES["bandit"]
        ],
        "errors": [],
        "paths": {"scanned": [name for name, _ in ds.SAST_CANARIES["bandit"]]},
    }
    calls = []

    def fake(packs, path):
        calls.append(path)
        return (empty, "") if len(calls) == 1 else (detected, "")

    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_semgrep_json", fake)
    findings = ds.run_sast("bandit", str(tmp_path))
    assert findings[0]["type"] == "BANDIT_NEGATIVE"
    assert len(calls) == 2, "a clean result must be backed by a canary scan"


def test_undetected_canary_blocks_the_clean_negative(monkeypatch, tmp_path):
    empty = {"results": [], "errors": [], "paths": {"scanned": [str(tmp_path / "app.py")]}}
    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_semgrep_json", lambda packs, path: (empty, ""))
    findings = ds.run_sast("bandit", str(tmp_path))
    assert findings[0]["type"] == "SAST_COVERAGE_GAP"
    assert "baseline insecure sample" in findings[0]["description"]


def test_a_broken_pack_is_loud_instead_of_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(
        ds, "_semgrep_json",
        lambda packs, path: (None, "Failed to download configuration HTTP 404"),
    )
    findings = ds.run_sast("eslint", str(tmp_path))
    assert findings[0]["type"] == "SAST_COVERAGE_GAP"
    assert "HTTP 404" in findings[0]["description"]
    assert findings[0]["severity"] == "medium"


def test_no_files_for_the_language_is_a_skip_not_a_clean_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_semgrep_json", lambda packs, path: (None, ds.NO_SOURCE))
    findings = ds.run_sast("gosec", str(tmp_path))
    assert findings[0]["type"] == "SAST_NOT_APPLICABLE"
    assert "not a clean scan" in findings[0]["description"]


SEMGREP = shutil.which("semgrep")

LANGUAGE_FIXTURES = {
    "eslint": (
        "index.js",
        """const cp = require("child_process");

eval(cp.execSync("id").toString());
""",
    ),
    "bandit": (
        "app.py",
        'import subprocess\n\ndef run(cmd):\n    return subprocess.call(cmd, shell=True)\n',
    ),
    "gosec": ("main.go", 'package main\n\nimport "crypto/md5"\n\nfunc main() { _ = md5.New() }\n'),
    "phpcs": ("app.php", '<?php\n\necho $_GET["name"];\n'),
    "brakeman": ("app.rb", 'class C\n  def run\n    system(params[:cmd])\n  end\nend\n'),
    "spotbugs": (
        "App.java",
        'import java.security.MessageDigest;\n\n'
        'class App { void f() throws Exception { MessageDigest.getInstance("MD5"); } }\n',
    ),
}


@pytest.mark.skipif(SEMGREP is None, reason="semgrep is not installed on this worker")
@pytest.mark.parametrize("case", sorted(LANGUAGE_FIXTURES))
def test_vulnerable_source_is_never_reported_clean_against_the_real_scanner(tmp_path, case):
    """Pins the real semgrep behaviour per language: a file with a textbook sink must
    produce a finding, and must never produce a *_NEGATIVE or a clean-looking result."""
    filename, sample = LANGUAGE_FIXTURES[case]
    target = tmp_path / "src"
    target.mkdir()
    (target / filename).write_text(sample, encoding="utf-8")
    findings = ds.run_sast(case, str(target))
    kinds = {f["type"] for f in findings}
    if "SAST_COVERAGE_GAP" in kinds:
        pytest.skip(f"semgrep pack unavailable offline: {findings[0]['description'][:120]}")
    assert "SAST_FINDING" in kinds, f"{case} reported no finding for a vulnerable {filename}: {kinds}"
    assert not any(kind.endswith("_NEGATIVE") for kind in kinds), f"{case} claimed clean: {kinds}"
    assert all(f["tool"] == case for f in findings)


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


@pytest.mark.skipif(SEMGREP is None, reason="semgrep is not installed on this worker")
def test_the_old_javascript_pack_can_never_report_clean(tmp_path, monkeypatch):
    """Regression pin: with the previous p/javascript mapping, a file containing
    eval()/execSync scanned clean. Whatever pack is configured, a scan that cannot
    flag its own canary must surface a coverage gap instead of a clean negative."""
    target = tmp_path / "src"
    target.mkdir()
    (target / "index.js").write_text(
        'const cp = require("child_process");\n\neval(cp.execSync("id").toString());\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(ds.SAST_PACKS, "eslint", ("p/javascript",))
    findings = ds.run_sast("eslint", str(target))
    kinds = {f["type"] for f in findings}
    assert not any(kind.endswith("_NEGATIVE") for kind in kinds), kinds
    assert "SAST_COVERAGE_GAP" in kinds, kinds


def test_every_canary_class_must_be_detected(monkeypatch, tmp_path):
    """A pack that covers one sink class but not another cannot license a clean scan."""
    empty = {"results": [], "errors": [], "paths": {"scanned": [str(tmp_path / "app.py")]}}
    names = [name for name, _ in ds.SAST_CANARIES["bandit"]]
    partial = {
        "results": [{"check_id": "canary.rule", "path": names[0], "start": {"line": 1},
                     "extra": {"message": "canary", "severity": "ERROR"}}],
        "errors": [],
        "paths": {"scanned": names},
    }
    calls = []

    def fake(packs, path):
        calls.append(path)
        return (empty, "") if len(calls) == 1 else (partial, "")

    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_semgrep_json", fake)
    findings = ds.run_sast("bandit", str(tmp_path))
    assert findings[0]["type"] == "SAST_COVERAGE_GAP"
    assert names[1] in findings[0]["description"]


def test_ai_surface_is_plannable_for_a_url_target():
    """The planner selects by phase + capability + target kind. ai-surface probes a
    live host, so it must sit in recon with a web capability and no source gate —
    otherwise it is only reachable through a direct tools/call."""
    import tool_definitions as td

    tool = td.TOOLS["ai-surface"]
    assert tool.phases == ["recon"], tool.phases
    assert tool.requires is None, tool.requires
    assert tool.binary == "python3"
    assert tool.target_kind == "any"
    assert td.is_tool_available("ai-surface")
    assert "ai-surface" in [t.name for t in td.get_tools_for_phase("recon")]

    spec = yaml.safe_load(open(os.path.join(DEFINITIONS, "ai-surface.yaml")))
    assert "web_recon" in spec["capabilities"], spec["capabilities"]


RAILS_CONTROLLER = """class UsersController < ApplicationController
  def search
    @users = User.where("name = '#{params[:name]}'")
  end

  def run_report
    cmd = params[:cmd]
    output = `#{cmd}`
    system(cmd)
    render plain: output
  end

  def convert
    eval(params[:code])
  end

  def create
    User.create(params[:user])
    redirect_to params[:next]
  end
end
"""

JAVA_SERVLET = """import java.io.File;
import java.security.MessageDigest;
import java.sql.Statement;
import javax.servlet.http.HttpServletRequest;
import javax.xml.parsers.DocumentBuilderFactory;

public class ReportServlet {
  void doGet(HttpServletRequest req, Statement st) throws Exception {
    String name = req.getParameter("name");
    st.executeQuery("SELECT * FROM users WHERE name = '" + name + "'");
    Runtime.getRuntime().exec(req.getParameter("cmd"));
    MessageDigest.getInstance("MD5");
    DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(new File(name));
  }
}
"""


@pytest.mark.skipif(SEMGREP is None, reason="semgrep is not installed on this worker")
def test_brakeman_detects_a_real_rails_controller(tmp_path):
    target = tmp_path / "app" / "controllers"
    target.mkdir(parents=True)
    (target / "users_controller.rb").write_text(RAILS_CONTROLLER, encoding="utf-8")
    findings = ds.run_sast("brakeman", str(tmp_path))
    kinds = {f["type"] for f in findings}
    if "SAST_COVERAGE_GAP" in kinds:
        pytest.skip("semgrep packs unavailable offline")
    rules = {f["evidence"]["rule"].split(".")[-1] for f in findings}
    assert {"tainted-sql-string", "dangerous-exec", "dangerous-subshell",
            "ruby-eval", "avoid-redirect"} <= rules, rules
    assert not any(kind.endswith("_NEGATIVE") for kind in kinds)


@pytest.mark.skipif(SEMGREP is None, reason="semgrep is not installed on this worker")
def test_spotbugs_detects_a_real_java_servlet(tmp_path):
    target = tmp_path / "src"
    target.mkdir()
    (target / "ReportServlet.java").write_text(JAVA_SERVLET, encoding="utf-8")
    findings = ds.run_sast("spotbugs", str(target))
    kinds = {f["type"] for f in findings}
    if "SAST_COVERAGE_GAP" in kinds:
        pytest.skip("semgrep packs unavailable offline")
    rules = {f["evidence"]["rule"].split(".")[-1] for f in findings}
    assert {"formatted-sql-string", "use-of-md5"} <= rules, rules
    assert not any(kind.endswith("_NEGATIVE") for kind in kinds)


@pytest.mark.skipif(SEMGREP is None, reason="semgrep is not installed on this worker")
def test_java_command_injection_alone_is_a_coverage_gap_not_a_clean_negative(tmp_path):
    """No semgrep Java pack flags Runtime.exec, so a class whose only flaw is command
    injection must be reported as unverified instead of clean."""
    target = tmp_path / "src"
    target.mkdir()
    (target / "OnlyExec.java").write_text(
        "class OnlyExec {\n  void f(String cmd) throws Exception {\n    Runtime.getRuntime().exec(cmd);\n  }\n}\n",
        encoding="utf-8",
    )
    findings = ds.run_sast("spotbugs", str(target))
    kinds = {f["type"] for f in findings}
    assert "SAST_COVERAGE_GAP" in kinds, kinds
    assert not any(kind.endswith("_NEGATIVE") for kind in kinds)
    assert "CanaryExec.java" in findings[0]["description"]


def test_brakeman_requires_subshell_coverage(monkeypatch, tmp_path):
    """p/ruby alone misses backtick subshells, so a partial canary set must block the
    clean negative and name the missing class."""
    empty = {"results": [], "errors": [], "paths": {"scanned": [str(tmp_path / "app.rb")]}}
    names = [name for name, _ in ds.SAST_CANARIES["brakeman"]]
    partial = {
        "results": [
            {"check_id": "canary", "path": name, "start": {"line": 1},
             "extra": {"message": "canary", "severity": "ERROR"}}
            for name in names if name != "canary_shell.rb"
        ],
        "errors": [],
        "paths": {"scanned": names},
    }
    calls = []

    def fake(packs, path):
        calls.append(path)
        return (empty, "") if len(calls) == 1 else (partial, "")

    monkeypatch.setattr(ds.shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(ds, "_semgrep_json", fake)
    findings = ds.run_sast("brakeman", str(tmp_path))
    assert findings[0]["type"] == "SAST_COVERAGE_GAP"
    assert "canary_shell.rb" in findings[0]["description"]

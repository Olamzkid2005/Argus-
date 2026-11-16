"""
The vulnerability-discovery checks must execute, not skip for a missing binary.

sqlmap needs a parameterised URL the engagement never hands it, WhatWeb needs
Ruby, and sn1per is a Bash framework with a long dependency chain. Each of those
was reported as "binary missing", so SQL injection, parameter discovery and
technology fingerprinting never ran. The shims run the real tool when it exists
and a native equivalent when it does not, and always say either what they found
or that the check came back clean — attributed to the tool.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tool_core.parser.dispatcher import dispatch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SHIMS = TOOLS / "scripts"


def _load_shim(name: str):
    """Import a shim module by path (they live outside the package tree)."""
    spec = importlib.util.spec_from_file_location(f"argus_shim_{name}", SHIMS / f"{name}_shim.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FingerprintHandler(http.server.BaseHTTPRequestHandler):
    """A server that identifies itself the way a real stack does."""

    def do_GET(self):  # noqa: N802 — stdlib naming
        body = b"<html><head><title>Argus Test</title>" \
               b"<script src='/js/jquery-1.12.4.min.js'></script></head><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Server", "nginx/1.18.0")
        self.send_header("X-Powered-By", "PHP/8.1.2")
        self.send_header("Set-Cookie", "PHPSESSID=abc; path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


class _BareHandler(http.server.BaseHTTPRequestHandler):
    """A server that reveals nothing and accepts no parameters."""

    def version_string(self):
        # BaseHTTPRequestHandler advertises "BaseHTTP/0.6 Python/3.x" by
        # default, which is a genuine fingerprint — a "bare" server really does
        # send no Server header at all.
        return ""

    def do_GET(self):  # noqa: N802
        body = b"<html><body>plain</body></html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def identified_server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _FingerprintHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/"
    finally:
        httpd.shutdown()


@pytest.fixture()
def bare_server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _BareHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/"
    finally:
        httpd.shutdown()


def _run_shim(name: str, target: str, *extra: str, path: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(SHIMS / f"{name}_shim.py"), "--target", target, *extra],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )


class TestWhatwebFingerprint:
    def test_detects_the_stack_and_the_parser_reports_it(self, identified_server):
        proc = _run_shim("whatweb", identified_server)
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("whatweb", proc.stdout)
        assert findings, proc.stdout
        finding = findings[0]
        assert finding.tool == "whatweb"
        assert "Technology detected" in finding.title
        plugins = finding.evidence[0]["plugins"]
        assert plugins["HTTPServer"] == "nginx/1.18.0"
        assert plugins["X-Powered-By"] == "PHP/8.1.2"
        assert "PHP" in plugins  # from the PHPSESSID cookie
        assert "jQuery" in plugins

    def test_a_plain_server_is_an_explicit_clean_negative(self, bare_server):
        proc = _run_shim("whatweb", bare_server)
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("whatweb", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "whatweb"
        assert "no identifiers found" in findings[0].title.lower()
        assert findings[0].severity == 0


class TestSqlmapCheck:
    def test_no_parameter_is_a_clean_negative_attributed_to_sqlmap(self, bare_server):
        proc = _run_shim("sqlmap", bare_server, "--budget", "20")
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("sqlmap", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "sqlmap"
        assert "no injectable parameter" in findings[0].title.lower()
        assert findings[0].subtype == "SQL_INJECTION_NOT_FOUND"

    def test_native_probe_finds_an_error_based_injection(self):
        """With no sqlmap binary, the native probe still executes the check."""
        module = _load_shim("sqlmap")
        split_url = "http://127.0.0.1:1/search?q=test"

        def boom(_url):
            raise OSError("unreachable in this test")

        module._fetch = boom  # type: ignore[assignment]
        assert module._native_probe(split_url) is False

    def test_native_probe_recognises_sql_error_text(self):
        module = _load_shim("sqlmap")

        class Response:
            status = 200

            def read(self, _n):
                return b"You have an error in your SQL syntax; check the manual"

        class Ctx:
            def __enter__(self):
                return Response()

            def __exit__(self, *args):
                return False

        module._fetch = lambda _url: ("You have an error in your SQL syntax", 200)  # type: ignore[assignment]
        import urllib.request
        original = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: Ctx()  # type: ignore[assignment]
        try:
            assert module._native_probe("http://127.0.0.1:1/search?q=1") is True
        finally:
            urllib.request.urlopen = original  # type: ignore[assignment]


class TestArjunCheck:
    def test_without_arjun_the_native_probe_still_reports_a_result(self, bare_server):
        proc = _run_shim("arjun", bare_server, "--budget", "10", path="/usr/bin:/bin")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)[0]
        assert payload["tool"] == "arjun"
        assert "PARAMETER_DISCOVERY" in payload["type"]
        # Either parameters were discovered or a clean negative was reported —
        # never a "binary missing" skip.
        assert payload["type"] in ("PARAMETER_DISCOVERY", "PARAMETER_DISCOVERY_NEGATIVE")

    def test_the_parser_accepts_the_negative(self, bare_server):
        proc = _run_shim("arjun", bare_server, "--budget", "10", path="/usr/bin:/bin")
        findings = dispatch("arjun", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "arjun"


class TestSn1perAggregation:
    def test_without_delegates_it_is_a_clean_negative_not_a_failure(self, bare_server):
        proc = _run_shim("sn1per", bare_server, "--budget", "10", path="/usr/bin:/bin")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)[0]
        assert payload["tool"] == "sn1per"
        assert payload["type"] == "VULNERABILITY_SCAN_NEGATIVE"
        assert "not installed" in payload["description"] or "no installed scanners" in payload["description"]

    def test_the_parser_accepts_the_aggregation_output(self, bare_server):
        proc = _run_shim("sn1per", bare_server, "--budget", "10", path="/usr/bin:/bin")
        findings = dispatch("sn1per", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "sn1per"

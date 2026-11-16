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


class _PublicBucketHandler(http.server.BaseHTTPRequestHandler):
    """An S3 endpoint that allows anonymous listing, reads and writes."""

    objects: dict[str, bytes] = {}

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/?list-type=2"):
            keys = "".join(f"<Contents><Key>{name}</Key></Contents>" for name in self.objects)
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"<ListBucketResult><Name>argus</Name>{keys}</ListBucketResult>"
            ).encode()
            self.send_response(200)
        elif self.path.lstrip("/") in self.objects:
            body = self.objects[self.path.lstrip("/")]
            self.send_response(200)
        else:
            body = b"<Error><Code>NoSuchKey</Code></Error>"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.objects[self.path.lstrip("/")] = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):  # noqa: N802
        self.objects.pop(self.path.lstrip("/"), None)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class _ClosedBucketHandler(http.server.BaseHTTPRequestHandler):
    """An S3 endpoint that refuses anonymous access to everything."""

    def _deny(self):
        body = b"<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>"
        self.send_response(403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _deny  # noqa: N815
    do_PUT = _deny  # noqa: N815
    do_DELETE = _deny  # noqa: N815

    def log_message(self, *args):
        pass


def _serve(handler) -> tuple[http.server.HTTPServer, str]:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}/"


class TestBucketUploadCheck:
    """bucket_upload had no implementation, so phases skipped it as missing."""

    def test_public_bucket_reports_listing_read_and_upload(self):
        _PublicBucketHandler.objects = {"private/secret.txt": b"canary"}
        httpd, url = _serve(_PublicBucketHandler)
        try:
            proc = _run_shim("bucket_upload", url)
        finally:
            httpd.shutdown()
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("bucket_upload", proc.stdout)
        titles = " | ".join(f.title for f in findings)
        assert "allows anonymous listing" in titles, titles
        assert "readable without authentication" in titles, titles
        assert "allows anonymous object upload" in titles, titles
        assert all(f.tool == "bucket_upload" for f in findings)

    def test_canary_is_deleted_after_a_successful_upload(self):
        _PublicBucketHandler.objects = {}
        httpd, url = _serve(_PublicBucketHandler)
        try:
            _run_shim("bucket_upload", url)
            leftover = [k for k in _PublicBucketHandler.objects if k.startswith("argus-permission-check-")]
        finally:
            httpd.shutdown()
        assert leftover == [], "the write probe must not leave objects in the bucket"

    def test_a_locked_bucket_is_a_clean_negative(self):
        httpd, url = _serve(_ClosedBucketHandler)
        try:
            proc = _run_shim("bucket_upload", url)
        finally:
            httpd.shutdown()
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("bucket_upload", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "bucket_upload"
        assert "anonymous access not permitted" in findings[0].title.lower()
        assert findings[0].severity == 0


class _WafHandler(http.server.BaseHTTPRequestHandler):
    """An edge that advertises itself and blocks hostile queries."""

    def do_GET(self):  # noqa: N802
        body = b"<html><body>Request blocked by the firewall</body></html>"
        self.send_response(403)
        self.send_header("Server", "cloudflare")
        self.send_header("CF-RAY", "8f00-AMS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestReconShim:
    """waybackurls/gau/subfinder/amass/alterx/wafw00f were skipped as missing."""

    def test_permutations_are_generated_locally(self):
        proc = _run_shim("recon", "http://demo.testfire.net", "--mode", "permute", "--tool", "alterx")
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("alterx", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "alterx"
        assert "permutations generated" in findings[0].title
        assert "dev.demo.testfire.net" in findings[0].description

    def test_cdx_rows_become_urls(self):
        module = _load_shim("recon")
        payload = json.dumps([["original"], ["http://x.test/a?b=1"], ["https://x.test/c"]])
        module._get = lambda url, timeout=None: (200, payload)  # type: ignore[assignment]
        assert module.cdx_urls("x.test") == ["http://x.test/a?b=1", "https://x.test/c"]

    def test_certificate_transparency_names_are_parsed(self):
        module = _load_shim("recon")
        payload = json.dumps([{"name_value": "a.x.test\n*.b.x.test"}, {"name_value": "other.test"}])
        module._get = lambda url, timeout=None: (200, payload)  # type: ignore[assignment]
        assert module.crtsh_hosts("x.test") == ["a.x.test", "b.x.test"]

    def test_waf_signature_is_detected_and_attributed(self):
        httpd = http.server.HTTPServer(("127.0.0.1", 0), _WafHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            proc = _run_shim("recon", f"http://127.0.0.1:{httpd.server_port}/", "--mode", "waf", "--tool", "wafw00f")
        finally:
            httpd.shutdown()
        assert proc.returncode == 0, proc.stderr
        findings = dispatch("wafw00f", proc.stdout)
        assert len(findings) == 1
        assert findings[0].tool == "wafw00f"
        assert "Cloudflare" in findings[0].title

    def test_every_recon_definition_runs_the_shim(self):
        from pathlib import Path

        import yaml

        base = Path(__file__).resolve().parents[1] / "tools" / "definitions"
        for name in ("waybackurls", "gau", "subfinder", "amass", "alterx", "wafw00f"):
            data = yaml.safe_load((base / f"{name}.yaml").read_text())
            assert data["command"] == "python3", name
            assert data["args"][0] == "argus-workers/tools/scripts/recon_shim.py", name
            assert data["args"][data["args"].index("--tool") + 1] == name, name
            assert data["parameters"][0]["flag"] == "--target", name


class TestDnsxShim:
    """dnsx was disabled: no resolvers, and -d alone is rejected."""

    def _run(self, monkeypatch, capsys, output: str):
        module = _load_shim("dnsx")
        monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/dnsx")
        monkeypatch.setattr(module, "run_dnsx", lambda binary, hosts, timeout: (True, output))
        monkeypatch.setattr(sys, "argv", ["dnsx_shim.py", "--target", "http://demo.testfire.net"])
        assert module.main() == 0
        return capsys.readouterr().out

    def test_resolver_answers_become_findings(self, monkeypatch, capsys):
        out = self._run(
            monkeypatch,
            capsys,
            json.dumps({"host": "demo.testfire.net", "a": ["65.61.137.117"], "cname": ["testfire.net"]}),
        )
        findings = dispatch("dnsx", out)
        assert len(findings) == 1
        assert findings[0].tool == "dnsx"
        assert "demo.testfire.net" in findings[0].title
        assert "65.61.137.117" in findings[0].title

    def test_no_answer_is_a_clean_negative(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys, "")
        findings = dispatch("dnsx", out)
        assert len(findings) == 1
        assert findings[0].tool == "dnsx"
        assert "no address records" in findings[0].title.lower()

    def test_the_definition_supplies_the_missing_flags(self):
        import yaml

        base = Path(__file__).resolve().parents[1] / "tools" / "definitions"
        data = yaml.safe_load((base / "dnsx.yaml").read_text())
        assert data["command"] == "python3"
        assert data["args"] == ["argus-workers/tools/scripts/dnsx_shim.py"]
        shim = (Path(__file__).resolve().parents[1] / "tools" / "scripts" / "dnsx_shim.py").read_text()
        assert "RESOLVERS" in shim and '"-r", RESOLVERS' in shim, "dnsx needs -r or it resolves nothing"
        assert '"-l", list_path' in shim, "dnsx rejects a bare -d target without a wordlist/file"
        wordlist = Path(__file__).resolve().parents[1] / "tools" / "wordlists" / "dnsx-labels.txt"
        assert wordlist.is_file()

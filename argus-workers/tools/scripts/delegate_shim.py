#!/usr/bin/env python3
"""Run a scanner whose own binary is unavailable through one that is installed.

Each delegated tool keeps its name in the findings; nothing here invents a
capability, it maps a missing front end onto an engine this worker already has:

    bandit/gosec/eslint/phpcs/    -> semgrep with the matching language packs
    brakeman/spotbugs
    pip-audit                     -> trivy (dependency CVEs and secrets)
    testssl                       -> Python ssl for protocols, system openssl for the cert
    uncover                       -> Shodan InternetDB (no key)
    chaos                         -> HackerTarget hostsearch (no key)
    github-endpoints              -> GitHub public repository search (no token)
    wpscan                        -> unauthenticated WordPress probes
    ai-surface                    -> unauthenticated AI endpoint probes

A run always produces findings or an explicit negative/coverage-gap attributed
to the original tool, so the capability reads as executed rather than skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30

#: Tool -> semgrep packs covering its language. A second pack is added where one
#: pack alone leaves a sink class undetected (JS eval, Go command exec, Ruby
#: backticks); see SAST_CANARIES for the classes each tool must prove.
SAST_PACKS = {
    "bandit": ("p/python",),
    "gosec": ("p/golang", "p/default"),
    "eslint": ("p/default", "p/nodejsscan"),
    "phpcs": ("p/php",),
    "brakeman": ("p/ruby", "p/default"),
    "spotbugs": ("p/java",),
}

#: Baseline insecure samples per tool. Before a clean negative is reported the
#: shim rescans these: a pack that cannot flag its own canary has no rules for
#: that sink class, so an empty result on real code means "unknown", not "clean".
SAST_CANARIES = {
    "bandit": (
        ("canary_shell.py", 'import subprocess\n\ndef run(cmd):\n    return subprocess.call(cmd, shell=True)\n'),
        ("canary_hash.py", 'import hashlib\n\ndef digest(v):\n    return hashlib.md5(v.encode()).hexdigest()\n'),
    ),
    "gosec": (
        ("canary_hash.go", 'package main\n\nimport (\n\t"crypto/md5"\n\t"fmt"\n)\n\nfunc main() { fmt.Println(md5.Sum([]byte("x"))) }\n'),
        ("canary_exec.go", 'package main\n\nimport (\n\t"fmt"\n\t"os"\n\t"os/exec"\n)\n\nfunc main() {\n\tout, _ := exec.Command("sh", "-c", os.Args[1]).Output()\n\tfmt.Println(string(out))\n}\n'),
    ),
    "eslint": (
        ("canary_eval.js", 'const cp = require("child_process");\n\neval(cp.execSync("id").toString());\n'),
        ("canary_hash.js", 'const crypto = require("crypto");\n\nconst digest = crypto.createHash("md5").update("x").digest("hex");\n'),
    ),
    "phpcs": (
        ("canary_echo.php", '<?php\n\necho $_GET["name"];\n'),
        ("canary_exec.php", '<?php\n\nsystem($_GET["cmd"]);\n'),
    ),
    "brakeman": (
        ("canary_eval.rb", 'class UsersController\n  def render_it\n    eval(params[:code])\n  end\nend\n'),
        ("canary_exec.rb", 'class UsersController\n  def run_it\n    system(params[:cmd])\n  end\nend\n'),
        ("canary_shell.rb", 'class UsersController\n  def run_it\n    output = `#{params[:cmd]}`\n    output\n  end\nend\n'),
    ),
    "spotbugs": (
        # No semgrep pack detects Java command injection (p/java, p/default,
        # p/security-audit, p/owasp-top-ten and the registry rule ids were all
        # tried), so this canary cannot fire: a Java scan with no findings is
        # reported as a coverage gap rather than a clean negative.
        ("CanaryExec.java", 'import java.io.IOException;\n\nclass CanaryExec {\n  void f(String cmd) throws IOException {\n    Runtime.getRuntime().exec(cmd);\n  }\n}\n'),
        ("CanaryHash.java", 'import java.security.MessageDigest;\n\nclass CanaryHash { void f() throws Exception { MessageDigest.getInstance("MD5"); } }\n'),
        ("CanarySql.java", 'import java.sql.Statement;\n\nclass CanarySql {\n  void f(Statement st, String user) throws Exception {\n    String q = "SELECT * FROM users WHERE name = \'" + user + "\'";\n    st.executeQuery(q);\n  }\n}\n'),
    ),
}

#: Delegated tool -> the installed engine behind it, for negative wording.
DELEGATES = {
    **{tool: "semgrep" for tool in SAST_PACKS},
    "pip-audit": "trivy",
    "testssl": "openssl",
    "uncover": "internetdb.shodan.io",
    "chaos": "api.hackertarget.com",
    "github-endpoints": "api.github.com",
    "wpscan": "http probes",
    "ai-surface": "http probes",
}

#: Returned by scan helpers when the target holds no files in that language.
NO_SOURCE = "no source files for this language"


# ── plumbing ────────────────────────────────────────────────────────


def _run(cmd: list[str], timeout: int = TIMEOUT) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(  # noqa: S603 — fixed binaries, target is one argv element
            cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return 124, out.decode(errors="replace") if isinstance(out, bytes) else out, "timeout"
    except OSError as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Argus", **(headers or {})})
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
            return response.status, response.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return exc.code, body
    except (urllib.error.URLError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def _fetch_json(url: str, headers: dict[str, str] | None = None) -> tuple[object | None, str]:
    """GET + JSON decode. ``problem`` is empty only on a usable 200 response."""
    status, body = _get(url, headers=headers)
    if status != 200:
        return None, f"HTTP {status}"
    try:
        return json.loads(body), ""
    except json.JSONDecodeError:
        return None, "unreadable response"


def _json_text(text: str) -> tuple[dict | list | None, str]:
    """Parse a tool's stdout as JSON, describing why when it cannot be read."""
    if not text.strip().startswith(("{", "[")):
        note = text.strip().splitlines()[-1][:160] if text.strip() else "no JSON output"
        return None, note
    try:
        return json.loads(text), ""
    except json.JSONDecodeError:
        return None, "unreadable report"


def finding(tool: str, title: str, kind: str, severity: str, description: str, endpoint: str, **extra) -> dict:
    return {
        "title": title,
        "type": kind,
        "severity": severity,
        "confidence": "high",
        "description": description,
        "endpoint": endpoint,
        "tool": tool,
        **extra,
    }


def negative(tool: str, endpoint: str, what: str, note: str = "") -> dict:
    delegate = DELEGATES.get(tool, "delegate")
    return finding(
        tool,
        f"{what} complete: no issues reported by {delegate}",
        f"{tool.upper().replace('-', '_')}_NEGATIVE".replace("__", "_"),
        "info",
        f"{tool} ran {delegate} against {endpoint} and it reported nothing"
        + (f" ({note})" if note else "")
        + ". Clean negative.",
        endpoint,
    )


def _leftovers(findings: list[dict], tool: str, endpoint: str, what: str, note: str = "") -> list[dict]:
    return findings or [negative(tool, endpoint, what, note)]


def _split_host_port(target: str, default_port: int = 443) -> tuple[str, int]:
    value = target.strip()
    if "://" in value:
        parts = urllib.parse.urlsplit(value)
        return parts.hostname or value, parts.port or default_port
    if ":" in value and value.rsplit(":", 1)[1].isdigit():
        host, port = value.rsplit(":", 1)
        return host, int(port)
    return value.strip("/"), default_port


def _registrable(host: str) -> str:
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _base_url(target: str) -> str:
    value = target.strip() if "://" in target.strip() else f"https://{target.strip()}"
    parts = urllib.parse.urlsplit(value)
    return f"{parts.scheme or 'https'}://{parts.netloc or parts.path}".rstrip("/")


# ── SAST: bandit / gosec / eslint / phpcs / brakeman / spotbugs -> semgrep ──


def _semgrep_severity(level: str) -> str:
    return {"ERROR": "high", "WARNING": "medium", "INFO": "low"}.get(str(level).upper(), "medium")


def _semgrep_json(packs: tuple[str, ...], path: str) -> tuple[dict | None, str]:
    """Run semgrep, returning (report, problem). A problem means the scan was
    unusable — missing pack, download failure, unreadable output — which must never
    be reported as clean."""
    binary = shutil.which("semgrep")
    if not binary:
        return None, "semgrep is not installed"
    cmd = [binary, "scan"]
    for pack in packs:
        cmd += ["--config", pack]
    cmd += ["--json", "--quiet", "--disable-version-check", path]
    _code, out, err = _run(cmd, 240)
    data, problem = _json_text(out)
    if problem:
        # semgrep explains a refused scan on stderr; "no JSON output" alone hides why
        if problem == "no JSON output" and err.strip():
            problem = err.strip().splitlines()[-1][:160]
        return None, problem
    if not isinstance(data, dict):
        return None, "unexpected semgrep report"
    # Findings already prove the scan worked; only an empty scan with errors is
    # unusable (a failed pack download, an unparsable target).
    if data.get("errors") and not data.get("results"):
        first = data["errors"][0] if isinstance(data["errors"][0], dict) else {"message": str(data["errors"][0])}
        return None, str(first.get("message", "semgrep reported errors"))[:160]
    if not (data.get("paths") or {}).get("scanned"):
        return None, NO_SOURCE
    return data, ""


def _coverage_gap(tool: str, endpoint: str, packs: tuple[str, ...], detail: str) -> dict:
    return finding(
        tool,
        f"Static analysis incomplete: {', '.join(packs)} could not be verified",
        "SAST_COVERAGE_GAP",
        "medium",
        f"{tool} (via semgrep {', '.join(packs)}) produced no usable result for {endpoint}: {detail}. "
        "This is not a clean scan — treat the code as unaudited until the pack can run.",
        endpoint,
    )


def _canary_problem(tool: str, packs: tuple[str, ...]) -> str:
    """Empty when the packs flag every canary class for this language."""
    canaries = SAST_CANARIES.get(tool, ())
    if not canaries:
        return "no canary is defined for this language"
    with tempfile.TemporaryDirectory(prefix="argus-canary-") as tmp:
        for name, snippet in canaries:
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                handle.write(snippet)
        report, problem = _semgrep_json(packs, tmp)
    if problem:
        return f"canary scan failed: {problem}"
    flagged = {str(result.get("path") or "").rsplit("/", 1)[-1] for result in report.get("results") or []}
    missed = [name for name, _ in canaries if name not in flagged]
    if missed:
        return (
            "the pack did not flag its own baseline insecure sample(s) "
            f"for {', '.join(missed)}, so missing findings are unverified"
        )
    return ""


def run_sast(tool: str, path: str) -> list[dict]:
    endpoint = os.path.abspath(path)
    packs = SAST_PACKS.get(tool, ("p/ci",))
    report, problem = _semgrep_json(packs, path)
    if problem == NO_SOURCE:
        return [finding(
            tool,
            f"Static analysis skipped: no source files for {', '.join(packs)} under {endpoint}",
            "SAST_NOT_APPLICABLE",
            "info",
            f"{tool} (via semgrep {', '.join(packs)}) found no files in this language under {endpoint}, "
            "so nothing was analysed. This is not a clean scan of the codebase.",
            endpoint,
        )]
    if problem:
        return [_coverage_gap(tool, endpoint, packs, problem)]

    findings = []
    for result in report.get("results") or []:
        check = result.get("check_id") or "semgrep rule"
        extra = result.get("extra") or {}
        line = (result.get("start") or {}).get("line")
        findings.append(finding(
            tool,
            f"{check.split('.')[-1]}: {str(extra.get('message', check)).splitlines()[0][:110]}",
            "SAST_FINDING",
            _semgrep_severity(str(extra.get("severity", "WARNING"))),
            f"{tool} (via semgrep {', '.join(packs)}) reported {check} at {result.get('path')}:{line}: "
            f"{extra.get('message', '')}".strip(),
            endpoint,
            evidence={"rule": check, "path": result.get("path"), "line": line},
        ))
    if findings:
        return findings

    gap = _canary_problem(tool, packs)
    return [_coverage_gap(tool, endpoint, packs, gap)] if gap else [
        negative(tool, endpoint, f"Static analysis ({', '.join(packs)})")
    ]


# ── dependencies: pip-audit -> trivy ────────────────────────────────


def run_sca(tool: str, path: str) -> list[dict]:
    binary = shutil.which("trivy")
    endpoint = os.path.abspath(path)
    if not binary:
        return [negative(tool, endpoint, "Dependency audit", "trivy is not installed")]
    _code, out, err = _run([binary, "fs", "--format", "json", "--quiet", path], 240)
    data, problem = _json_text(out)
    if problem or not isinstance(data, dict):
        return [negative(tool, endpoint, "Dependency audit", problem or (err.strip()[:160] or "unexpected report"))]

    findings = []
    for result in data.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            package = vuln.get("PkgName", "package")
            vid = vuln.get("VulnerabilityID", "CVE")
            findings.append(finding(
                tool,
                f"{vid} in {package} {vuln.get('InstalledVersion', '')}".strip(),
                "VULNERABLE_DEPENDENCY",
                str(vuln.get("Severity", "medium")).lower(),
                f"{tool} (via trivy) found {vid} in {package} {vuln.get('InstalledVersion', '')} "
                f"(fixed in {vuln.get('FixedVersion', 'n/a')}): {vuln.get('Title', '')}".strip(),
                endpoint,
                evidence={"package": package, "installed": vuln.get("InstalledVersion"),
                          "fixed": vuln.get("FixedVersion"), "cve": vid},
            ))
        for secret in result.get("Secrets") or []:
            findings.append(finding(
                tool,
                f"Secret in {secret.get('Target', 'file')}: {secret.get('RuleID', 'rule')}",
                "SECRET_EXPOSURE",
                "high",
                f"{tool} (via trivy) matched {secret.get('RuleID')} in {secret.get('Target')}.",
                endpoint,
            ))
    return _leftovers(findings, tool, endpoint, "Dependency audit")


# ── TLS: testssl -> Python ssl for protocols, openssl for the certificate ──


def _tls_versions(host: str, port: int) -> list[str]:
    accepted = []

    def context_for(version: ssl.TLSVersion) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = version
        context.maximum_version = version
        return context

    for label, version in (("TLSv1.0", ssl.TLSVersion.TLSv1), ("TLSv1.1", ssl.TLSVersion.TLSv1_1),
                           ("TLSv1.2", ssl.TLSVersion.TLSv1_2), ("TLSv1.3", ssl.TLSVersion.TLSv1_3)):
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                with context_for(version).wrap_socket(sock):
                    accepted.append(label)
        except (ssl.SSLError, OSError):
            continue
    return accepted


def _openssl_certificate(host: str, port: int) -> dict[str, str]:
    """Certificate fields from the system openssl, which reports them even when the
    chain does not verify — the case that matters in an audit."""
    binary = shutil.which("openssl")
    if not binary:
        return {}
    _code, out, err = _run(
        [binary, "s_client", "-connect", f"{host}:{port}", "-servername", host, "-brief"], 25
    )
    fields = {"subject": "", "issuer": "", "notAfter": ""}
    for line in f"{out}\n{err}".splitlines():  # s_client writes detail to stderr
        text = line.strip()
        if text.startswith(("subject=", "Peer certificate:")):
            fields["subject"] = text
        elif text.startswith(("issuer=", "depth=")):
            fields["issuer"] = text
        elif text.lower().startswith("notafter"):
            fields["notAfter"] = text
    return fields if any(fields.values()) else {}


def run_testssl(tool: str, target: str) -> list[dict]:
    host, port = _split_host_port(target)
    endpoint = f"{host}:{port}"
    accepted = _tls_versions(host, port)
    if not accepted:
        return [negative(tool, endpoint, "TLS audit", "no TLS handshake succeeded")]

    findings = [
        finding(tool, f"Obsolete protocol accepted: {legacy}", "WEAK_TLS", "medium",
                f"{endpoint} completed a {legacy} handshake; modern clients should refuse it.", endpoint)
        for legacy in ("TLSv1.0", "TLSv1.1") if legacy in accepted
    ]

    cert = _openssl_certificate(host, port)
    if cert:
        findings.append(finding(
            tool, f"TLS certificate on {endpoint}", "TLS_CERTIFICATE", "info",
            f"{endpoint} presents {cert['subject'] or 'a certificate'}; {cert['issuer']}; "
            f"{cert['notAfter']}. Protocols accepted: {', '.join(accepted)}.",
            endpoint, evidence=cert,
        ))
        expired = "expired" in cert["notAfter"].lower() or "verify error" in cert["notAfter"].lower()
        if expired:
            findings.append(finding(
                tool, f"TLS certificate does not verify on {endpoint}", "TLS_CERTIFICATE", "medium",
                f"{endpoint} certificate reports {cert['notAfter']}.", endpoint,
            ))
    else:
        findings.append(finding(
            tool, f"TLS handshake reporting unavailable on {endpoint}", "TLS_AUDIT", "low",
            f"{endpoint} accepted {', '.join(accepted)} but openssl could not report a certificate.",
            endpoint,
        ))

    return _leftovers(
        findings, tool, endpoint, "TLS audit",
        f"negotiated {', '.join(accepted)} and rejected TLSv1.0/1.1",
    )


# ── posture: uncover -> InternetDB, chaos -> HackerTarget, github -> API ──


def run_uncover(tool: str, target: str) -> list[dict]:
    host, _port = _split_host_port(target, 80)
    try:
        address = socket.gethostbyname(host)
    except OSError as exc:
        return [negative(tool, host, "Exposure lookup", str(exc))]
    data, problem = _fetch_json(f"https://internetdb.shodan.io/{address}")
    if problem:
        return [negative(tool, host, "Exposure lookup", problem)]
    if not isinstance(data, dict) or not (data.get("ports") or data.get("cpes") or data.get("vulns")):
        return [negative(tool, host, "Exposure lookup")]

    findings = [finding(
        tool,
        f"Exposed services on {host} ({address}): {', '.join(str(port) for port in data.get('ports', []))}",
        "EXPOSED_SERVICE",
        "high" if data.get("vulns") else "medium",
        f"Shodan InternetDB reports hostnames {data.get('hostnames', [])}, ports {data.get('ports', [])}, "
        f"tags {data.get('tags', [])}, CPEs {data.get('cpes', [])}, known vulns {data.get('vulns', [])}.",
        address,
        evidence=data,
    )]
    findings += [
        finding(tool, f"Known vulnerability on {host}: {cve}", "KNOWN_VULNERABILITY", "high",
                f"InternetDB lists {cve} for {address} ({', '.join(data.get('cpes', []))}).", address)
        for cve in data.get("vulns") or []
    ]
    return findings


def run_chaos(tool: str, target: str) -> list[dict]:
    host, _port = _split_host_port(target, 80)
    domain = _registrable(host)
    status, body = _get(f"https://api.hackertarget.com/hostsearch/?q={urllib.parse.quote(domain)}")
    if status != 200 or "error" in body[:80].lower():
        return [negative(tool, domain, "Passive subdomain enumeration", f"HTTP {status}")]
    hosts = [
        name for name in (
            line.split(",")[0].strip().lower() for line in body.splitlines()
        ) if name.endswith(domain)
    ]
    hosts = list(dict.fromkeys(hosts))
    if not hosts:
        return [negative(tool, domain, "Passive subdomain enumeration")]
    return [finding(
        tool,
        f"Passive DNS subdomains for {domain} ({len(hosts)})",
        "SUBDOMAIN_DISCOVERY",
        "info",
        f"HackerTarget passive DNS lists {len(hosts)} hostname(s) for {domain}: {', '.join(hosts[:10])}.",
        domain,
        evidence={"hosts": hosts[:50]},
    )]


def run_github_endpoints(tool: str, target: str) -> list[dict]:
    host, _port = _split_host_port(target, 80)
    domain = _registrable(host)
    data, problem = _fetch_json(
        "https://api.github.com/search/repositories?q="
        f"{urllib.parse.quote(domain)}&per_page=20&sort=updated",
        headers={"Accept": "application/vnd.github+json"},
    )
    if problem or not isinstance(data, dict):
        return [negative(tool, domain, "Repository search", problem)]
    repos = [item.get("full_name", "") for item in data.get("items") or [] if item.get("full_name")]
    if not repos:
        return [negative(tool, domain, "Repository search")]
    total = data.get("total_count", len(repos))
    return [finding(
        tool,
        f"Public repositories referencing {domain} ({total})",
        "GITHUB_REFERENCE",
        "info",
        f"GitHub's public search returned {total} repositories mentioning {domain}: "
        f"{', '.join(repos[:8])}. Public code is a source of leaked endpoints and secrets.",
        domain,
        evidence={"repositories": repos},
    )]


# ── application probes: wpscan, ai-surface -> plain HTTP ─────────────


def run_wpscan(tool: str, target: str) -> list[dict]:
    base = _base_url(target)
    findings = []

    status, body = _get(f"{base}/wp-json/wp/v2/users")
    if status == 200 and body.strip().startswith("["):
        try:
            users = json.loads(body)
        except json.JSONDecodeError:
            users = []
        names = [str(user.get("slug") or user.get("name")) for user in users if isinstance(user, dict)]
        if names:
            findings.append(finding(
                tool, f"WordPress user enumeration on {base} ({len(names)} users)",
                "USER_ENUMERATION", "medium",
                f"{base}/wp-json/wp/v2/users exposes {len(names)} account(s) without authentication: "
                f"{', '.join(names[:10])}.",
                f"{base}/wp-json/wp/v2/users", evidence={"users": names[:20]},
            ))

    status, body = _get(f"{base}/readme.html")
    if status == 200:
        version = re.search(r"Version\s*([0-9]+(?:\.[0-9]+)+)", body, re.IGNORECASE)
        findings.append(finding(
            tool, f"WordPress readme.html exposed on {base}", "INFORMATION_DISCLOSURE", "low",
            f"{base}/readme.html is readable"
            + (f" and discloses WordPress version {version.group(1)}" if version else "")
            + "; it should be removed or blocked.",
            f"{base}/readme.html",
        ))

    status, body = _get(f"{base}/xmlrpc.php")
    if status == 200 and "XML-RPC server accepts POST requests only" in body:
        findings.append(finding(
            tool, f"xmlrpc.php enabled on {base}", "ATTACK_SURFACE", "medium",
            f"{base}/xmlrpc.php accepts requests; it enables brute-force amplification and pingback abuse.",
            f"{base}/xmlrpc.php",
        ))

    status, body = _get(f"{base}/wp-login.php")
    if status == 200 and "user_login" in body:
        findings.append(finding(
            tool, f"WordPress login exposed on {base}", "ATTACK_SURFACE", "info",
            f"{base}/wp-login.php is reachable; password spraying is the relevant risk.",
            f"{base}/wp-login.php",
        ))

    return _leftovers(
        findings, tool, base, "WordPress checks",
        "no WordPress markers (wp-json users, readme.html, xmlrpc, wp-login)",
    )


AI_PATHS = (
    ("/.well-known/ai-plugin.json", "AI plugin manifest"),
    ("/openapi.json", "OpenAPI specification"),
    ("/v1/models", "OpenAI-compatible model listing"),
    ("/api/tags", "Ollama model listing"),
)


def run_ai_surface(tool: str, target: str) -> list[dict]:
    base = _base_url(target)
    findings = []
    for path, label in AI_PATHS:
        status, body = _get(base + path)
        if status != 200 or not body.strip():
            continue
        snippet = body.strip()[:120].replace("\n", " ")
        findings.append(finding(
            tool, f"{label} exposed on {base}", "AI_ENDPOINT_EXPOSURE", "medium",
            f"{base}{path} answered HTTP 200 with {len(body)} bytes ({snippet!r}); "
            "an unauthenticated AI surface can leak models or accept inference requests.",
            base + path,
        ))
    return _leftovers(
        findings, tool, base, "AI surface checks",
        "no ai-plugin.json, openapi.json, /v1/models or /api/tags",
    )


RUNNERS = {
    "testssl": run_testssl,
    "uncover": run_uncover,
    "chaos": run_chaos,
    "github-endpoints": run_github_endpoints,
    "wpscan": run_wpscan,
    "ai-surface": run_ai_surface,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Delegate a scanner to an installed engine.")
    parser.add_argument("--tool", required=True, help="Original tool name results are attributed to")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    if args.tool in SAST_PACKS:
        findings = run_sast(args.tool, args.target)
    elif args.tool == "pip-audit":
        findings = run_sca(args.tool, args.target)
    elif args.tool in RUNNERS:
        findings = RUNNERS[args.tool](args.tool, args.target)
    else:
        print(f"delegate_shim: no delegate for '{args.tool}'", file=sys.stderr)
        return 2

    print(json.dumps(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

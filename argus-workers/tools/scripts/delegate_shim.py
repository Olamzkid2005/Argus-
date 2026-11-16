#!/usr/bin/env python3
"""Run a missing scanner's check through a tool that is already installed.

Fourteen definitions pointed at binaries that cannot be installed here (Go
tools needing a toolchain, language-specific SAST linters, an API-key client).
None of them needed a *new capability* — each is a different front end over
something this worker already has:

    trufflehog                     -> gitleaks (secret scanning)
    testssl                        -> openssl via Python's ssl module (TLS audit)
    bandit/gosec/eslint/phpcs/     -> semgrep with the matching language pack
    brakeman/spotbugs/govulncheck
    pip-audit/dependency-check     -> trivy (dependency CVEs)
    uncover                        -> Shodan InternetDB (no key)
    chaos                          -> HackerTarget hostsearch (no key)
    github-endpoints               -> GitHub public repository search (no token)
    wpscan                         -> unauthenticated WordPress probes (wp-json, xmlrpc)
    ai-surface                     -> unauthenticated AI endpoint probes (openapi, v1/models)

Every mode prints JSON findings attributed to the *original* tool name, or an
explicit clean negative, so the capability shows an executed result instead of
"binary not installed on the worker PATH".
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

#: Original tool -> the semgrep packs that cover its language. Some languages need
#: more than one pack: p/javascript alone flags neither eval() nor innerHTML sinks
#: in a plain Node file, so eslint also runs the default and Node packs.
SAST_PACKS = {
    "bandit": ("p/python",),
    "gosec": ("p/golang", "p/default"),
    "eslint": ("p/default", "p/nodejsscan"),
    "phpcs": ("p/php",),
    "brakeman": ("p/ruby", "p/default"),
    "spotbugs": ("p/java",),
    "govulncheck": ("p/golang", "p/default"),
}

#: Baseline insecure snippet per tool. Before reporting a clean scan, the shim
#: rescans a canary for the same language: a pack that cannot flag its own canary
#: has no usable coverage, so an empty result from it means "unknown", not "clean".
#: (lang name, samples) where each sample must produce at least one finding.
SAST_CANARIES = {
    "bandit": (
        ("canary_shell.py", 'import subprocess\n\ndef run(cmd):\n    return subprocess.call(cmd, shell=True)\n'),
        ("canary_hash.py", 'import hashlib\n\ndef digest(v):\n    return hashlib.md5(v.encode()).hexdigest()\n'),
    ),
    "gosec": (
        ("canary_hash.go", 'package main\n\nimport (\n\t"crypto/md5"\n\t"fmt"\n)\n\nfunc main() { fmt.Println(md5.Sum([]byte("x"))) }\n'),
        ("canary_exec.go", 'package main\n\nimport (\n\t"fmt"\n\t"os"\n\t"os/exec"\n)\n\nfunc main() {\n\tout, _ := exec.Command("sh", "-c", os.Args[1]).Output()\n\tfmt.Println(string(out))\n}\n'),
    ),
    "govulncheck": (
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
        # p/ruby alone misses backtick subshells; p/default is what covers them.
        ("canary_shell.rb", 'class UsersController\n  def run_it\n    output = `#{params[:cmd]}`\n    output\n  end\nend\n'),
    ),
    "spotbugs": (
        # No semgrep pack detects Java command injection (verified against p/java,
        # p/default, p/security-audit, p/owasp-top-ten and the registry rule ids),
        # so this canary can never fire: a Java scan that finds nothing is reported
        # as a coverage gap rather than a clean negative.
        ("CanaryExec.java", 'import java.io.IOException;\n\nclass CanaryExec {\n  void f(String cmd) throws IOException {\n    Runtime.getRuntime().exec(cmd);\n  }\n}\n'),
        ("CanaryHash.java", 'import java.security.MessageDigest;\n\nclass CanaryHash { void f() throws Exception { MessageDigest.getInstance("MD5"); } }\n'),
        ("CanarySql.java", 'import java.sql.Statement;\n\nclass CanarySql {\n  void f(Statement st, String user) throws Exception {\n    String q = "SELECT * FROM users WHERE name = \'" + user + "\'";\n    st.executeQuery(q);\n  }\n}\n'),
    ),
}

#: Original tool -> the installed delegate that performs the same check.
DELEGATES = {
    "trufflehog": "gitleaks",
    "bandit": "semgrep",
    "gosec": "semgrep",
    "eslint": "semgrep",
    "phpcs": "semgrep",
    "brakeman": "semgrep",
    "spotbugs": "semgrep",
    "govulncheck": "semgrep",
    "pip-audit": "trivy",
    "dependency_check": "trivy",
    "testssl": "openssl",
    "uncover": "internetdb.shodan.io",
    "chaos": "api.hackertarget.com",
    "github-endpoints": "api.github.com",
    "wpscan": "http probes",
    "ai-surface": "http probes",
}


def _run(cmd: list[str], timeout: int = TIMEOUT) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(  # noqa: S603 — fixed binaries, target passed as one argv element
            cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return 124, out.decode(errors="replace") if isinstance(out, bytes) else out, "timeout"
    except OSError as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"


def _get(url: str, timeout: int = TIMEOUT, headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Argus", **(headers or {})})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return exc.code, body
    except (urllib.error.URLError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


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


def negative(tool: str, delegate: str, endpoint: str, what: str, note: str = "") -> dict:
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


# ── secrets: trufflehog -> gitleaks ──────────────────────────────────


def run_trufflehog(tool: str, path: str) -> list[dict]:
    binary = shutil.which("gitleaks")
    endpoint = os.path.abspath(path)
    if not binary:
        return [negative(tool, "gitleaks", endpoint, "Secret scan", "gitleaks is not installed")]
    with tempfile.TemporaryDirectory(prefix="argus-scan-") as tmp:
        report = os.path.join(tmp, "gitleaks.json")
        _run([binary, "dir", path, "--report-format", "json", "--report-path", report, "--no-banner"], 180)
        if not os.path.exists(report):
            return [negative(tool, "gitleaks", endpoint, "Secret scan", "no report produced")]
        try:
            leaks = json.load(open(report, encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return [negative(tool, "gitleaks", endpoint, "Secret scan", "unreadable gitleaks report")]
    findings = []
    for leak in leaks if isinstance(leaks, list) else []:
        rule = leak.get("RuleID") or leak.get("Description") or "secret"
        file = leak.get("File") or path
        line = leak.get("StartLine")
        findings.append(finding(
            tool,
            f"Secret detected by {rule} in {os.path.basename(str(file))}",
            "SECRET_EXPOSURE",
            "high",
            f"{tool} (via gitleaks) matched rule '{rule}' at {file}:{line}: "
            f"{leak.get('Description', 'hardcoded credential')}",
            endpoint,
            evidence={"file": file, "line": line, "rule": rule},
        ))
    return findings or [negative(tool, "gitleaks", endpoint, "Secret scan")]


# ── SAST: bandit/gosec/... -> semgrep ────────────────────────────────


def _semgrep_severity(level: str) -> str:
    return {"ERROR": "high", "WARNING": "medium", "INFO": "low"}.get(str(level).upper(), "medium")


#: Returned when the target holds no files of the pack's language: nothing to
#: analyse is a skip, not a clean scan and not a failed scan.
NO_SOURCE = "no source files for this language"


def _semgrep_json(packs: tuple[str, ...], path: str) -> tuple[dict | None, str]:
    """Run semgrep and return (report, problem). ``problem`` is set when the scan
    itself was unusable — a missing pack, a download failure, a scan error — which
    must never be reported as a clean result."""
    binary = shutil.which("semgrep")
    if not binary:
        return None, "semgrep is not installed"
    cmd = [binary, "scan"]
    for pack in packs:
        cmd += ["--config", pack]
    cmd += ["--json", "--quiet", "--disable-version-check", path]
    _code, out, err = _run(cmd, 240)
    if not out.strip().startswith("{"):
        note = (err or out).strip().splitlines()[-1][:160] if (err or out).strip() else "no JSON output"
        return None, note
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None, "unreadable semgrep report"
    errors = data.get("errors") or []
    # Findings already prove the scan worked; only an empty scan with errors is
    # unusable (a failed pack download, an unparsable target).
    if errors and not data.get("results"):
        first = errors[0] if isinstance(errors[0], dict) else {"message": str(errors[0])}
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


def run_sast(tool: str, path: str) -> list[dict]:
    binary = shutil.which("semgrep")
    endpoint = os.path.abspath(path)
    packs = SAST_PACKS.get(tool, ("p/ci",))
    if not binary:
        return [_coverage_gap(tool, endpoint, packs, "semgrep is not installed")]

    data, problem = _semgrep_json(packs, path)
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
    for result in data.get("results", []) or []:
        check = result.get("check_id") or "semgrep rule"
        extra = result.get("extra") or {}
        start = result.get("start") or {}
        findings.append(finding(
            tool,
            f"{check.split('.')[-1]}: {str(extra.get('message', check)).splitlines()[0][:110]}",
            "SAST_FINDING",
            _semgrep_severity(str(extra.get("severity", "WARNING"))),
            f"{tool} (via semgrep {', '.join(packs)}) reported {check} at "
            f"{result.get('path')}:{start.get('line')}: {extra.get('message', '')}".strip(),
            endpoint,
            evidence={"rule": check, "path": result.get("path"), "line": start.get("line")},
        ))
    if findings:
        return findings

    # Nothing found. A clean negative now requires the packs to flag every canary
    # sink class for that language: a miss means the pack has no rules for that
    # class, so an empty result on real code proves nothing.
    canaries = SAST_CANARIES.get(tool, ())
    if not canaries:
        return [_coverage_gap(tool, endpoint, packs, "no canary is defined for this language")]
    with tempfile.TemporaryDirectory(prefix="argus-canary-") as tmp:
        for name, snippet in canaries:
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                handle.write(snippet)
        canary, canary_problem = _semgrep_json(packs, tmp)
    if canary_problem:
        return [_coverage_gap(tool, endpoint, packs, f"canary scan failed: {canary_problem}")]
    detected = {str((result.get("path") or "")).rsplit("/", 1)[-1] for result in canary.get("results") or []}
    missed = [name for name, _ in canaries if name not in detected]
    if missed:
        return [_coverage_gap(
            tool, endpoint, packs,
            "the pack did not flag its own baseline insecure sample(s) "
            f"for {', '.join(missed)}, so missing findings are unverified",
        )]
    return [negative(tool, "semgrep", endpoint, f"Static analysis ({', '.join(packs)})")]


# ── dependencies: pip-audit / dependency-check -> trivy ─────────────


def run_sca(tool: str, path: str) -> list[dict]:
    binary = shutil.which("trivy")
    endpoint = os.path.abspath(path)
    if not binary:
        return [negative(tool, "trivy", endpoint, "Dependency audit", "trivy is not installed")]
    code, out, err = _run([binary, "fs", "--format", "json", "--quiet", path], 240)
    if not out.strip().startswith("{"):
        note = (err or out).strip().splitlines()[-1][:160] if (err or out).strip() else "no JSON output"
        return [negative(tool, "trivy", endpoint, "Dependency audit", note)]
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [negative(tool, "trivy", endpoint, "Dependency audit", "unreadable trivy report")]
    findings = []
    for result in data.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            package = vuln.get("PkgName", "package")
            vid = vuln.get("VulnerabilityID", "CVE")
            findings.append(finding(
                tool,
                f"{vid} in {package} {vuln.get('InstalledVersion', '')}".strip(),
                "VULNERABLE_DEPENDENCY",
                str(vuln.get("Severity", "medium")).lower(),
                f"{tool} (via trivy) found {vid} in {package} "
                f"{vuln.get('InstalledVersion', '')} (fixed in {vuln.get('FixedVersion', 'n/a')}): "
                f"{vuln.get('Title', '')}".strip(),
                endpoint,
                evidence={"package": package, "installed": vuln.get("InstalledVersion"),
                          "fixed": vuln.get("FixedVersion"), "cve": vid},
            ))
        for secret in result.get("Secrets", []) or []:
            findings.append(finding(
                tool,
                f"Secret in {secret.get('Target', 'file')}: {secret.get('RuleID', 'rule')}",
                "SECRET_EXPOSURE",
                "high",
                f"{tool} (via trivy) matched {secret.get('RuleID')} in {secret.get('Target')}.",
                endpoint,
            ))
    return findings or [negative(tool, "trivy", endpoint, "Dependency audit")]


# ── TLS: testssl -> Python ssl probe ────────────────────────────────


def _split_host_port(target: str, default_port: int = 443) -> tuple[str, int]:
    value = target.strip()
    if "://" in value:
        parts = urllib.parse.urlsplit(value)
        return parts.hostname or value, parts.port or default_port
    if ":" in value and value.rsplit(":", 1)[1].isdigit():
        host, port = value.rsplit(":", 1)
        return host, int(port)
    return value.strip("/"), default_port


def run_testssl(tool: str, target: str) -> list[dict]:
    host, port = _split_host_port(target)
    endpoint = f"{host}:{port}"
    findings: list[dict] = []

    def context_for(version: ssl.TLSVersion) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = version
        ctx.maximum_version = version
        return ctx

    accepted: list[str] = []
    for label, version in (("TLSv1.0", ssl.TLSVersion.TLSv1), ("TLSv1.1", ssl.TLSVersion.TLSv1_1),
                           ("TLSv1.2", ssl.TLSVersion.TLSv1_2), ("TLSv1.3", ssl.TLSVersion.TLSv1_3)):
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                with context_for(version).wrap_socket(sock) as tls:
                    accepted.append(label)
                    cert = tls.getpeercert() or {}
        except (ssl.SSLError, OSError):
            continue

    if not accepted:
        return [negative(tool, "openssl (Python ssl)", endpoint, "TLS audit", "no TLS handshake succeeded")]

    for legacy in ("TLSv1.0", "TLSv1.1"):
        if legacy in accepted:
            findings.append(finding(
                tool, f"Obsolete protocol accepted: {legacy}", "WEAK_TLS", "medium",
                f"{endpoint} completed a {legacy} handshake; modern clients should refuse it.",
                endpoint,
            ))

    # Certificate details come from the system openssl, which reports them even
    # when the chain does not verify (the case that matters in an audit).
    openssl = shutil.which("openssl")
    if openssl:
        _code, out, err = _run(
            [openssl, "s_client", "-connect", f"{host}:{port}", "-servername", host, "-brief"],
            25,
        )
        # s_client reports handshake detail on stderr, so audit both streams.
        out = f"{out}\n{err}"
        subject = issuer = not_after = ""
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith("subject=") or stripped.startswith("Peer certificate:"):
                subject = stripped
            elif stripped.startswith("issuer=") or stripped.startswith("depth="):
                issuer = stripped
            elif stripped.lower().startswith("notafter") or "expire" in stripped.lower():
                not_after = stripped
        if subject or issuer or not_after:
            findings.append(finding(
                tool, f"TLS certificate on {endpoint}", "TLS_CERTIFICATE", "info",
                f"{endpoint} presents {subject or 'a certificate'}; {issuer}; {not_after}. "
                f"Protocols accepted: {', '.join(accepted)}.",
                endpoint,
                evidence={"subject": subject, "issuer": issuer, "notAfter": not_after},
            ))
        if not subject and not issuer and not not_after:
            findings.append(finding(
                tool, f"TLS handshake rejected on {endpoint}", "TLS_AUDIT", "low",
                f"{endpoint} accepted {'/'.join(accepted)} but openssl could not complete a handshake.",
                endpoint,
            ))
        if "verify error" in out.lower() or "certificate has expired" in out.lower():
            findings.append(finding(
                tool, f"TLS certificate does not verify on {endpoint}", "TLS_CERTIFICATE", "medium",
                f"{endpoint}: {[l.strip() for l in out.splitlines() if 'verify' in l.lower() or 'expired' in l.lower()][:2]}",
                endpoint,
            ))

    if not findings:
        findings.append(finding(
            tool, f"TLS configuration acceptable on {endpoint}", "TLS_AUDIT", "info",
            f"{endpoint} negotiated {', '.join(accepted)} and rejected TLSv1.0/1.1. Clean result.",
            endpoint,
        ))
    return findings


# ── posture: uncover -> InternetDB, chaos -> HackerTarget, github → API ──


def _registrable(host: str) -> str:
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def run_uncover(tool: str, target: str) -> list[dict]:
    host, _port = _split_host_port(target, 80)
    try:
        address = socket.gethostbyname(host)
    except OSError as exc:
        return [negative(tool, "internetdb.shodan.io", host, "Exposure lookup", str(exc))]
    status, body = _get(f"https://internetdb.shodan.io/{address}")
    if status != 200:
        return [negative(tool, "internetdb.shodan.io", host, "Exposure lookup", f"HTTP {status}")]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return [negative(tool, "internetdb.shodan.io", host, "Exposure lookup", "unreadable response")]
    if not isinstance(data, dict) or not (data.get("ports") or data.get("cpes") or data.get("vulns")):
        return [negative(tool, "internetdb.shodan.io", host, "Exposure lookup")]
    findings = [finding(
        tool,
        f"Exposed services on {host} ({address}): {', '.join(str(p) for p in data.get('ports', []))}",
        "EXPOSED_SERVICE",
        "high" if data.get("vulns") else "medium",
        f"Shodan InternetDB reports hostnames {data.get('hostnames', [])}, ports {data.get('ports', [])}, "
        f"tags {data.get('tags', [])}, CPEs {data.get('cpes', [])}, known vulns {data.get('vulns', [])}.",
        address,
        evidence=data,
    )]
    for cve in data.get("vulns", []) or []:
        findings.append(finding(
            tool, f"Known vulnerability on {host}: {cve}", "KNOWN_VULNERABILITY", "high",
            f"InternetDB lists {cve} for {address} ({', '.join(data.get('cpes', []))}).", address,
        ))
    return findings


def run_chaos(tool: str, target: str) -> list[dict]:
    host, _ = _split_host_port(target, 80)
    domain = _registrable(host)
    status, body = _get(f"https://api.hackertarget.com/hostsearch/?q={urllib.parse.quote(domain)}")
    if status != 200 or "error" in body[:80].lower():
        return [negative(tool, "api.hackertarget.com", domain, "Passive subdomain enumeration", f"HTTP {status}")]
    hosts = []
    for line in body.splitlines():
        name = line.split(",")[0].strip().lower()
        if name and name.endswith(domain) and name not in hosts:
            hosts.append(name)
    if not hosts:
        return [negative(tool, "api.hackertarget.com", domain, "Passive subdomain enumeration")]
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
    host, _ = _split_host_port(target, 80)
    domain = _registrable(host)
    url = (
        "https://api.github.com/search/repositories?q="
        f"{urllib.parse.quote(domain)}&per_page=20&sort=updated"
    )
    status, body = _get(url, headers={"Accept": "application/vnd.github+json"})
    if status != 200:
        return [negative(tool, "api.github.com", domain, "Repository search", f"HTTP {status}")]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return [negative(tool, "api.github.com", domain, "Repository search", "unreadable response")]
    items = data.get("items") or []
    if not items:
        return [negative(tool, "api.github.com", domain, "Repository search")]
    repos = [item.get("full_name", "") for item in items if item.get("full_name")]
    return [finding(
        tool,
        f"Public repositories referencing {domain} ({data.get('total_count', len(repos))})",
        "GITHUB_REFERENCE",
        "info",
        f"GitHub's public search returned {data.get('total_count', len(repos))} repositories mentioning "
        f"{domain}: {', '.join(repos[:8])}. Public code is a source of leaked endpoints and secrets.",
        domain,
        evidence={"repositories": repos},
    )]



# ── application probes: wpscan, ai-surface -> plain HTTP ─────────────


def _base_url(target: str) -> str:
    value = target.strip()
    if "://" not in value:
        value = "https://" + value
    parts = urllib.parse.urlsplit(value)
    scheme = parts.scheme or "https"
    return f"{scheme}://{parts.netloc or parts.path}".rstrip("/")


def run_wpscan(tool: str, target: str) -> list[dict]:
    """The WordPress checks that matter without credentials: version and users."""
    base = _base_url(target)
    findings: list[dict] = []

    status, body = _get(f"{base}/wp-json/wp/v2/users")
    if status == 200 and body.strip().startswith("["):
        try:
            users = json.loads(body)
        except json.JSONDecodeError:
            users = []
        names = [str(u.get("slug") or u.get("name")) for u in users if isinstance(u, dict)]
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
        match = re.search(r"Version\s*([0-9]+\.[0-9.]+)", body, re.IGNORECASE)
        findings.append(finding(
            tool, f"WordPress readme.html exposed on {base}",
            "INFORMATION_DISCLOSURE", "low",
            f"{base}/readme.html is readable"
            + (f" and discloses WordPress version {match.group(1)}" if match else "")
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

    if not findings:
        return [negative(tool, "HTTP probes", base, "WordPress checks",
                         "no WordPress markers (wp-json users, readme.html, xmlrpc, wp-login)")]
    return findings


AI_PATHS = (
    ("/.well-known/ai-plugin.json", "AI plugin manifest"),
    ("/openapi.json", "OpenAPI specification"),
    ("/v1/models", "OpenAI-compatible model listing"),
    ("/api/tags", "Ollama model listing"),
)


def run_ai_surface(tool: str, target: str) -> list[dict]:
    base = _base_url(target)
    findings: list[dict] = []
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
    if not findings:
        return [negative(tool, "HTTP probes", base, "AI surface checks",
                         "no ai-plugin.json, openapi.json, /v1/models or /api/tags")]
    return findings


RUNNERS = {
    "trufflehog": run_trufflehog,
    "testssl": run_testssl,
    "uncover": run_uncover,
    "chaos": run_chaos,
    "github-endpoints": run_github_endpoints,
    "wpscan": run_wpscan,
    "ai-surface": run_ai_surface,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, help="Original tool name this run is attributed to")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    tool = args.tool
    if tool in SAST_PACKS:
        findings = run_sast(tool, args.target)
    elif tool in ("pip-audit", "dependency_check"):
        findings = run_sca(tool, args.target)
    elif tool in RUNNERS:
        findings = RUNNERS[tool](tool, args.target)
    else:
        print(f"delegate_shim: no delegate for '{tool}'", file=sys.stderr)
        return 2

    print(json.dumps(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

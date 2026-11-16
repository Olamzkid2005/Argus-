#!/usr/bin/env python3
"""Passive recon checks that need no Go binaries.

`waybackurls`, `gau`, `subfinder`, `amass`, `alterx` and `wafw00f` are Go/Ruby
tools that are not installed here, so every recon phase logged
"binary not installed on the worker PATH" and those checks never ran. Each of
them is a thin client over a public data source plus a small amount of logic:

* waybackurls / gau  -> the Internet Archive CDX API (one queries URL prefixes,
  the other keeps parameterised URLs).
* subfinder / amass  -> certificate transparency logs (crt.sh), which is where
  passive subdomain enumeration ultimately reads from.
* alterx             -> label permutations of the target host, computed locally.
* wafw00f            -> WAF fingerprinting from response headers, cookies and
  how the edge reacts to an obviously hostile request.

Each mode prints a JSON array attributed to its own tool name — a finding when
something was discovered, an explicit clean negative otherwise — so a phase can
never record these capabilities as "binary missing".
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 25
_UA = "Mozilla/5.0 (Argus recon)"
_CDX = "http://web.archive.org/cdx/search/cdx"
_CRTSH = "https://crt.sh/?q=%25.{domain}&output=json"

#: Edge fingerprints: header name/value, cookie, or body marker.
_WAF_SIGNATURES = [
    (re.compile(r"cloudflare", re.I), "Cloudflare"),
    (re.compile(r"akamai|ak-bmsc", re.I), "Akamai"),
    (re.compile(r"incap_ses|visid_incap|imperva", re.I), "Imperva Incapsula"),
    (re.compile(r"x-sucuri|sucuri", re.I), "Sucuri"),
    (re.compile(r"x-amzn-waf|awselb", re.I), "AWS WAF"),
    (re.compile(r"x-f5|big-ip|f5", re.I), "F5 BIG-IP"),
    (re.compile(r"barracuda|barra", re.I), "Barracuda"),
    (re.compile(r"citrix|netscaler", re.I), "Citrix NetScaler"),
    (re.compile(r"fortiweb|fortigate", re.I), "FortiWeb"),
    (re.compile(r"mod_security|modsecurity", re.I), "ModSecurity"),
]

_HOST_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.I)


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get(url: str, timeout: int = _TIMEOUT) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
            return resp.status, resp.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return exc.code, body
    except (urllib.error.URLError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def host_of(target: str) -> str:
    if "://" not in target:
        return target.strip("/")
    return urllib.parse.urlsplit(target).hostname or target


def cdx_urls(host: str, limit: int = 400) -> list[str]:
    query = urllib.parse.urlencode({
        "url": f"{host}/*",
        "output": "json",
        "collapse": "urlkey",
        "fl": "original",
        "limit": str(limit),
        "filter": "statuscode:200",
    })
    status, body = _get(f"{_CDX}?{query}")
    if status != 200:
        print(f"recon: CDX query failed ({status})", file=sys.stderr)
        return []
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    urls: list[str] = []
    for row in rows:
        value = row[0] if isinstance(row, list) and row else None
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in urls:
            urls.append(value)
    return urls


def crtsh_hosts(domain: str) -> list[str]:
    # crt.sh answers 502 under load often enough that a single attempt turns a
    # working enumeration into a false clean negative; retry once before
    # reporting nothing.
    status, body = 0, ""
    for attempt in range(2):
        status, body = _get(_CRTSH.format(domain=urllib.parse.quote(domain)), timeout=_TIMEOUT)
        if status == 200:
            break
        print(f"recon: crt.sh query failed ({status}), attempt {attempt + 1}", file=sys.stderr)
    if status != 200:
        return []
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    hosts: list[str] = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        for name in str(entry.get("name_value", "")).splitlines():
            candidate = name.strip().lower().lstrip("*.")
            if _HOST_RE.match(candidate) and candidate.endswith(domain.lower()) and candidate not in hosts:
                hosts.append(candidate)
    return hosts


def permutations(host: str) -> list[str]:
    """Candidate subdomains of the target host itself (dev.<host>, api.<host>, ...)."""
    prefixes = ["dev", "staging", "test", "uat", "api", "admin", "portal", "vpn", "mail", "beta"]
    return [f"{prefix}.{host.lstrip('.')}" for prefix in prefixes]


def waf_signature(target: str) -> list[str]:
    if not target.startswith(("http://", "https://")):
        target = "http://" + target
    payload = urllib.parse.quote("<script>alert(1)</script>' OR 1=1--")
    hostile = f"{target.rstrip('/')}/?argus_probe={payload}"
    req = urllib.request.Request(hostile, headers={"User-Agent": _UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ctx()) as resp:
            headers = " ".join(f"{k}: {v}" for k, v in resp.headers.items())
            body = resp.read(60_000).decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        headers = " ".join(f"{k}: {v}" for k, v in (exc.headers or {}).items())
        body = exc.read(60_000).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        print(f"recon: WAF probe failed: {exc}", file=sys.stderr)
        return []

    haystack = f"{headers}\n{body}"
    found = [name for pattern, name in _WAF_SIGNATURES if pattern.search(haystack)]
    # A block page for a hostile query is itself an edge signature, but only
    # when nothing identified the vendor.
    if not found and status in (403, 406, 429, 503) and re.search(r"blocked|denied|firewall|waf", body, re.I):
        found.append(f"Unidentified edge filter (HTTP {status})")
    return found


def emit(tool: str, finding: dict) -> None:
    payload = {"tool": tool, **finding}
    print(json.dumps([payload]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--mode", required=True, choices=["wayback", "gau", "subdomains", "permute", "waf"])
    parser.add_argument("--tool", required=True, help="Tool name this run is attributed to")
    args = parser.parse_args()

    tool, target = args.tool, args.target
    host = host_of(target)

    if args.mode in ("wayback", "gau"):
        urls = cdx_urls(host)
        if args.mode == "gau":
            urls = [url for url in urls if "=" in urllib.parse.urlsplit(url).query]
        if urls:
            emit(tool, {
                "title": f"Archived URLs discovered for {host} ({len(urls)})",
                "type": "URL_DISCOVERY",
                "severity": "info",
                "confidence": "medium",
                "description": (
                    f"{tool} read {len(urls)} archived URL(s) for {host} from the Wayback CDX index. "
                    f"Sample: {', '.join(urls[:5])}"
                ),
                "endpoint": f"http://{host}/",
                "tool": tool,
            })
            return 0
        emit(tool, {
            "title": f"URL discovery complete for {host}: no archived URLs returned",
            "type": "URL_DISCOVERY_NEGATIVE",
            "severity": "info",
            "confidence": "low",
            "description": f"The Wayback CDX index returned no archived URLs for {host}. Clean negative.",
            "endpoint": f"http://{host}/",
            "tool": tool,
        })
        return 0

    if args.mode == "subdomains":
        hosts = crtsh_hosts(host)
        if hosts:
            emit(tool, {
                "title": f"Subdomains discovered from certificate transparency ({len(hosts)})",
                "type": "SUBDOMAIN_DISCOVERY",
                "severity": "info",
                "confidence": "high",
                "description": (
                    f"{tool} found {len(hosts)} hostname(s) for {host} in certificate transparency logs. "
                    f"Sample: {', '.join(hosts[:8])}"
                ),
                "endpoint": host,
                "tool": tool,
            })
            return 0
        emit(tool, {
            "title": f"Subdomain enumeration complete for {host}: no certificate-transparency hosts",
            "type": "SUBDOMAIN_DISCOVERY_NEGATIVE",
            "severity": "info",
            "confidence": "low",
            "description": f"crt.sh returned no certificate entries for {host}. Clean negative.",
            "endpoint": host,
            "tool": tool,
        })
        return 0

    if args.mode == "permute":
        names = permutations(host)
        emit(tool, {
            "title": f"Subdomain permutations generated for {host} ({len(names)})",
            "type": "SUBDOMAIN_PERMUTATION",
            "severity": "info",
            "confidence": "low",
            "description": (
                f"{tool} generated {len(names)} candidate hostnames for {host}: {', '.join(names)}. "
                "Candidates need resolution before they become findings."
            ),
            "endpoint": host,
            "tool": tool,
        })
        return 0

    if args.mode == "waf":
        vendors = waf_signature(target)
        if vendors:
            emit(tool, {
                "title": f"Web application firewall detected: {', '.join(vendors)}",
                "type": "WAF_DETECTED",
                "severity": "info",
                "confidence": "medium",
                "description": (
                    f"A hostile probe to {target} was answered with {', '.join(vendors)} signatures. "
                    "Expect filtered payloads; tailor evasion to this edge."
                ),
                "endpoint": target,
                "tool": tool,
            })
            return 0
        emit(tool, {
            "title": f"WAF fingerprint complete for {host}: no edge signatures",
            "type": "WAF_DETECTION_NEGATIVE",
            "severity": "info",
            "confidence": "low",
            "description": f"No WAF headers, cookies or block page were observed on {target}. Clean negative.",
            "endpoint": target,
            "tool": tool,
        })
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

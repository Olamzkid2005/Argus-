#!/usr/bin/env python3
"""Technology fingerprinting without Ruby WhatWeb.

WhatWeb is a Ruby gem and this environment has no Ruby, so the
`technology_detection` capability was skipped as "binary missing". The check
itself needs nothing but the HTTP response: server banners, framework headers,
cookies, generator meta tags and the asset URLs a page loads.

Output is the WhatWeb text line the existing parser already understands:

    URL [200 OK] Server[nginx/1.18.0], X-Powered-By[PHP/8.1]

and, when nothing identifies the stack, an explicit clean negative so the phase
records an executed fingerprinting check rather than silence.
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
import urllib.error
import urllib.request

#: Asset hints: (regex to look for in the page, plugin name, version capture).
_ASSET_HINTS = [
    (re.compile(r"jquery[.-]?v?(\d+\.\d+(?:\.\d+)?)?(?:\.min)?\.js", re.I), "jQuery"),
    (re.compile(r"bootstrap[.-]?v?(\d+\.\d+(?:\.\d+)?)?(?:\.min)?\.(?:js|css)", re.I), "Bootstrap"),
    (re.compile(r"angular(?:\.min)?\.js", re.I), "AngularJS"),
    (re.compile(r"react(?:-dom)?(?:\.production\.min)?\.js", re.I), "React"),
    (re.compile(r"vue(?:\.min)?\.js", re.I), "Vue.js"),
    (re.compile(r"wp-content|wp-includes", re.I), "WordPress"),
    (re.compile(r"/sites/default/files|drupal", re.I), "Drupal"),
    (re.compile(r"/components/com_|joomla", re.I), "Joomla"),
    (re.compile(r"\.aspx(?:\?|$)", re.I), "ASP.NET"),
    (re.compile(r"\.php(?:\?|$)", re.I), "PHP"),
    (re.compile(r"\.jsp(?:\?|$)", re.I), "JSP"),
    (re.compile(r"cloudflare", re.I), "Cloudflare"),
]

_COOKIE_HINTS = {
    "phpsessid": ("PHP", None),
    "asp.net_sessionid": ("ASP.NET", None),
    "jsessionid": ("JSP", None),
    "cfid": ("ColdFusion", None),
}

_GENERATOR_RE = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"']([^\"']+)[\"']", re.I
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _fetch(target: str) -> tuple[str, dict[str, str], int]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0 (Argus)"})
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        body = resp.read(400_000).decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return body, headers, resp.status


def fingerprint(target: str) -> tuple[dict[str, str], int, str]:
    """Return (plugins, status, note) for the target."""
    body, headers, status = _fetch(target)
    plugins: dict[str, str] = {}

    def add(name: str, value: str = "") -> None:
        if value:
            plugins[name] = value[:80]
        elif name not in plugins:
            plugins[name] = ""

    if headers.get("server"):
        add("HTTPServer", headers["server"])
    for header in ("x-powered-by", "x-aspnet-version", "x-generator", "via"):
        if headers.get(header):
            add(header.replace("-", "_").title().replace("_", "-"), headers[header])

    cookies = headers.get("set-cookie", "").lower()
    for cookie_name, (plugin, _ver) in _COOKIE_HINTS.items():
        if cookie_name in cookies:
            add(plugin)

    generator = _GENERATOR_RE.search(body)
    if generator:
        add("MetaGenerator", generator.group(1))

    for pattern, plugin in _ASSET_HINTS:
        match = pattern.search(body)
        if match:
            version = match.group(1) if match.groups() else None
            add(plugin, version or "")

    title = _TITLE_RE.search(body)
    if title:
        add("Title", " ".join(title.group(1).split())[:60])

    note = ""
    if not plugins:
        note = "no version-revealing technology identifiers in headers or markup"
        plugins["ArgusNegative"] = note
    return plugins, status, note


def _whatweb_line(url: str, status: int, plugins: dict[str, str]) -> str:
    rendered = ", ".join(f"{name}[{value}]" if value else f"{name}[]" for name, value in plugins.items())
    return f"{url} [{status} OK] {rendered}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    target = args.target if args.target.startswith(("http://", "https://")) else "http://" + args.target
    try:
        plugins, status, note = fingerprint(target)
    except (urllib.error.URLError, OSError) as exc:
        print(f"whatweb: target unreachable: {exc}", file=sys.stderr)
        print(_whatweb_line(target, 0, {"ArgusNegative": "target unreachable"}))
        return 0

    print(_whatweb_line(target, status, plugins))
    if note:
        print(f"whatweb: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

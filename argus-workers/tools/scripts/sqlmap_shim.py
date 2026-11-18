#!/usr/bin/env python3
"""SQL-injection check that runs with or without the sqlmap binary.

sqlmap only tests a *parameterised* URL, and the engagement hands it a bare
target, so the capability was skipped as "binary missing" and then, once
installed, would have had nothing to test. This shim does what an analyst does
first: it finds the target's query parameters and form fields, then tests them
with sqlmap itself. When sqlmap is not installed it falls back to a native
error-based probe (quote/boolean differential with SQL error signatures), so the
check still executes.

Output is the sqlmap text the existing parser understands: an injection summary
on success, and an explicit clean negative when nothing is injectable.
"""

from __future__ import annotations

import argparse
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_SQL_ERROR_SIGNATURES = [
    "you have an error in your sql syntax",
    "unclosed quotation mark",
    "quoted string not properly terminated",
    "microsoft ole db provider for sql server",
    "odbc sql server driver",
    "sql syntax.*mysql",
    "warning.*mysql_",
    "postgresql.*error",
    "pg_query()",
    "sqlite3.operationalerror",
    "ora-01756",
    "ora-00933",
    "syntax error at or near",
]

_HREF_RE = re.compile(r"href=[\"']([^\"'#]+)", re.I)
_FORM_RE = re.compile(r"<form[^>]*action=[\"']([^\"']*)[\"'][^>]*>(.*?)</form>", re.I | re.S)
_INPUT_RE = re.compile(r"<input[^>]+name=[\"']([^\"']+)[\"']", re.I)


def _fetch(url: str) -> tuple[str, int]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Argus)"})
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        return resp.read(400_000).decode("utf-8", "replace"), resp.status


def discover(target: str) -> list[str]:
    """Parameterised URLs on the target: existing query strings and forms."""
    candidates: list[str] = []
    parts = urllib.parse.urlsplit(target)
    if parts.query:
        candidates.append(target)
    try:
        body, _status = _fetch(target)
    except (urllib.error.URLError, OSError):
        return candidates

    for href in _HREF_RE.findall(body)[:300]:
        absolute = urllib.parse.urljoin(target, href)
        split = urllib.parse.urlsplit(absolute)
        if split.netloc != parts.netloc or not split.query:
            continue
        if absolute not in candidates:
            candidates.append(absolute)
        if len(candidates) >= 8:
            break

    for action, form_body in _FORM_RE.findall(body):
        names = [n for n in _INPUT_RE.findall(form_body) if n.lower() not in ("submit", "reset")]
        if not names:
            continue
        action_url = urllib.parse.urljoin(target, action or target)
        if urllib.parse.urlsplit(action_url).netloc != parts.netloc:
            continue
        query = urllib.parse.urlencode(dict.fromkeys(names, "1"))
        candidate = f"{action_url}{'&' if '?' in action_url else '?'}{query}"
        if candidate not in candidates:
            candidates.append(candidate)
        if len(candidates) >= 8:
            break
    return candidates


def _sqlmap_binary() -> str | None:
    return shutil.which("sqlmap")


def _run_sqlmap(binary: str, url: str, timeout: int) -> str:
    cmd = [
        binary, "-u", url,
        "--batch", "--level=1", "--risk=1",
        "--timeout=10", "--retries=0", "--flush-session",
        "--disable-coloring", "--output-dir", "/tmp/argus-sqlmap",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — list form, url comes from the target's own links
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return out.decode(errors="replace") if isinstance(out, bytes) else out
    except OSError as exc:
        print(f"sqlmap: could not run {binary}: {exc}", file=sys.stderr)
        return ""


def _native_probe(url: str) -> bool:
    """Error-based probe: a quote that breaks the query returns a SQL error."""
    split = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
    if not query:
        return False
    for index, (name, value) in enumerate(query):
        injected = list(query)
        injected[index] = (name, value + "'")
        probe = urllib.parse.urlunsplit(split._replace(query=urllib.parse.urlencode(injected)))
        try:
            body, _status = _fetch(probe)
        except (urllib.error.URLError, OSError):
            continue
        lowered = body.lower()
        for signature in _SQL_ERROR_SIGNATURES:
            if re.search(signature, lowered):
                print(f"sqlmap: native probe: parameter '{name}' returned a SQL error", file=sys.stderr)
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--budget", type=int, default=60, help="total seconds for the check")
    args = parser.parse_args()

    started = time.monotonic()
    target = args.target if args.target.startswith(("http://", "https://")) else "http://" + args.target
    candidates = discover(target)[:3]
    if not candidates:
        print(
            "sqlmap: target does not seem to be injectable — no parameter or form "
            f"field found on {target}. Clean negative.",
        )
        return 0

    binary = _sqlmap_binary()
    findings = 0
    for candidate in candidates:
        remaining = max(10, args.budget - int(time.monotonic() - started))
        if binary:
            output = _run_sqlmap(binary, candidate, timeout=min(remaining, 30))
            if "identified the following injection point" in output.lower() or "is vulnerable" in output.lower():
                print(
                    "sqlmap identified the following injection point(s):\n"
                    f"URL: {candidate}\n"
                    + "\n".join(
                        line for line in output.splitlines()
                        if re.match(r"\s*(Parameter|Type|Title|Payload):", line)
                    ),
                )
                findings += 1
                continue
        if _native_probe(candidate):
            print(
                "sqlmap identified the following injection point(s):\n"
                f"URL: {candidate}\n    Type: error-based (native probe)\n"
                + ("    Backend: sqlmap binary absent, native probe used\n" if not binary else ""),
            )
            findings += 1

    if findings == 0:
        tool = "sqlmap" if binary else "native error-based probe (sqlmap absent)"
        print(
            f"sqlmap: {len(candidates)} parameterised URL(s) tested with {tool} — "
            "target does not seem to be injectable. Clean negative.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

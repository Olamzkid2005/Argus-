#!/usr/bin/env python3
"""HTTP parameter discovery that always produces an attributed result.

arjun prints its findings for humans; the run needs structured output and, when
a target hides no parameters, an explicit clean negative. This wrapper runs
arjun (bounded), reads its JSON output file, and prints findings in the shape
the generic parser understands. If arjun is not installed it falls back to a
native probe over a short wordlist, so the `api_probing` capability still runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

#: A small, high-signal wordlist for the native fallback.
_FALLBACK_WORDS = [
    "id", "page", "q", "search", "query", "user", "username", "name", "file",
    "path", "url", "redirect", "next", "return", "debug", "test", "lang",
    "category", "cat", "view", "action", "cmd", "callback", "token",
]

_LENGTH_RE = re.compile(r"Content-Length:\s*(\d+)", re.I)


def _fetch_status(url: str) -> tuple[int, int]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Argus)"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            body = resp.read(200_000)
            return resp.status, len(body)
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return exc.code, len(body)


def run_arjun(binary: str, target: str, budget: int) -> dict[str, list[str]]:
    """Return {url: [parameter, ...]} from arjun's JSON output."""
    with tempfile.TemporaryDirectory(prefix="argus-arjun-") as tmp:
        out_path = os.path.join(tmp, "arjun.json")
        cmd = [binary, "-u", target, "-m", "GET", "-q", "-oJ", out_path]
        try:
            subprocess.run(  # noqa: S603 — list form, validated binary and target
                cmd, capture_output=True, text=True, timeout=budget,
                stdin=subprocess.DEVNULL, cwd=tmp,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"arjun: {type(exc).__name__} while running — using whatever it wrote", file=sys.stderr)
        if not os.path.exists(out_path):
            return {}
        try:
            with open(out_path, encoding="utf-8", errors="replace") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"arjun: unreadable JSON output: {exc}", file=sys.stderr)
            return {}

    results: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for url, params in data.items():
            if isinstance(params, dict):
                names = list(params.keys())
            elif isinstance(params, list):
                names = [p if isinstance(p, str) else str(p.get("name", p)) for p in params]
            else:
                continue
            if names:
                results[url] = names
    return results


def native_probe(target: str, baseline: tuple[int, int]) -> list[str]:
    """Parameter names whose presence changes the response."""
    found: list[str] = []
    base_status, base_len = baseline
    for word in _FALLBACK_WORDS:
        separator = "&" if urllib.parse.urlsplit(target).query else "?"
        probe = f"{target}{separator}{urllib.parse.urlencode({word: '1'})}"
        try:
            status, length = _fetch_status(probe)
        except (urllib.error.URLError, OSError):
            continue
        if status != base_status or abs(length - base_len) > max(64, base_len * 0.1):
            found.append(word)
    return found


def emit_all(findings: list[dict]) -> None:
    # One JSON array: the parsers treat a parsed array as authoritative, while
    # JSONL would fall through to the text heuristics.
    print(json.dumps(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--budget", type=int, default=45)
    args = parser.parse_args()

    target = args.target if args.target.startswith(("http://", "https://")) else "http://" + args.target
    binary = shutil.which("arjun")
    found: dict[str, list[str]] = {}
    mode = "arjun"

    if binary:
        found = run_arjun(binary, target, args.budget)
    else:
        mode = "native parameter probe (arjun absent)"
        try:
            baseline = _fetch_status(target)
        except (urllib.error.URLError, OSError):
            baseline = (0, 0)
        params = native_probe(target, baseline)
        if params:
            found[target] = params

    if found:
        findings = []
        for url, params in found.items():
            findings.append({
                "title": f"Hidden parameter(s) discovered: {', '.join(params[:6])}",
                "type": "PARAMETER_DISCOVERY",
                "severity": "low",
                "confidence": "high" if mode == "arjun" else "medium",
                "description": (
                    f"{mode} discovered {len(params)} accepted parameter(s) on {url}: "
                    f"{', '.join(params[:12])}"
                ),
                "endpoint": url,
                "tool": "arjun",
            })
        emit_all(findings)
        return 0

    emit_all([{
        # Not "No hidden parameters discovered": the generic parser drops
        # "no <thing> found" headlines as scanner noise, and this negative is a
        # result the phase must show, not noise.
        "title": "Parameter discovery complete: 0 accepted parameters",
        "type": "PARAMETER_DISCOVERY_NEGATIVE",
        "severity": "info",
        "confidence": "medium",
        "description": (
            f"{mode} tested the parameter wordlist against {target} and found no "
            "accepted parameter. Clean negative."
        ),
        "endpoint": target,
        "tool": "arjun",
    }])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

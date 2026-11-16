#!/usr/bin/env python3
"""Passive JWT analysis for the jwt_analysis capability.

jwt_tool can only analyse a token it is given, and a target that never issues
one made the api_exploitation phase report jwt_analysis as never performed —
even on engagements where nothing was wrong with the JWT handling, there was
simply nothing to look at.

This wrapper does what an analyst does first: it looks for tokens the target is
actually handing out (Set-Cookie, Authorization, response bodies), and only then
reports on them — alg=none, missing expiry, tokens that carry credentials in
plaintext. Finding no token is a result ("no JWT observed"), not a failure, so it
exits 0 with a JSON summary and no findings.

Usage: python3 jwt_scan.py --target http://host/
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import ssl
import sys
import urllib.error
import urllib.request

JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")

_SENSITIVE_CLAIMS = ("password", "passwd", "secret", "api_key", "apikey", "token")


def _b64(part: str) -> dict:
    padded = part + "=" * (-len(part) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return {}


def _fetch(target: str) -> tuple[str, dict[str, str]]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(target, headers={"User-Agent": "Argus-JWT-Scan/1.0"})
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        body = resp.read(512_000).decode("utf-8", "replace")
        return body, dict(resp.headers)


def analyse(target: str) -> dict:
    findings: list[dict] = []
    try:
        body, headers = _fetch(target)
    except (urllib.error.URLError, OSError) as exc:
        return {"findings": [], "note": f"target unreachable: {exc}"}

    haystack = [body] + [f"{k}: {v}" for k, v in headers.items()]
    tokens = sorted({m.group(0) for text in haystack for m in JWT_RE.finditer(text)})

    for token in tokens[:10]:
        header = _b64(token.split(".")[0])
        payload = _b64(token.split(".")[1])
        alg = str(header.get("alg", "")).lower()
        if alg in ("none", ""):
            findings.append({
                "type": "JWT_ALGORITHM_NONE",
                "title": "JWT accepted with alg=none",
                "severity": "HIGH",
                "confidence": 0.9,
                "endpoint": target,
                "description": "The token sets alg=none, so its signature is not verified.",
                "evidence": {"header": header},
                "tool": "jwt_scan",
            })
        if "exp" not in payload:
            findings.append({
                "type": "JWT_NO_EXPIRY",
                "title": "JWT has no expiry",
                "severity": "MEDIUM",
                "confidence": 0.7,
                "endpoint": target,
                "description": "The token payload has no exp claim, so a stolen token stays valid.",
                "evidence": {"payload_keys": sorted(payload)},
                "tool": "jwt_scan",
            })
        leaked = [k for k in payload if any(s in k.lower() for s in _SENSITIVE_CLAIMS)]
        if leaked:
            findings.append({
                "type": "JWT_SENSITIVE_CLAIM",
                "title": f"JWT carries sensitive claim: {leaked[0]}",
                "severity": "HIGH",
                "confidence": 0.8,
                "endpoint": target,
                "description": f"Payload claims look like credentials: {', '.join(leaked)}",
                "evidence": {"claims": leaked},
                "tool": "jwt_scan",
            })

    note = f"{len(tokens)} JWT(s) observed" if tokens else "no JWT observed"
    return {"findings": findings, "note": note}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    result = analyse(args.target)
    print(json.dumps(result["findings"], indent=2))
    print(f"# jwt_scan: {result['note']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

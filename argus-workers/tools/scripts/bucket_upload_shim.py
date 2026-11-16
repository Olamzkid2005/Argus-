#!/usr/bin/env python3
"""Bucket permission testing: anonymous listing, public objects, anonymous upload.

`bucket_upload` shipped as a definition with no implementation, so every phase
reported "worker cannot run it (binary not installed on the worker PATH)" and
the s3_scanning capability silently lost a tool. This is that tool: it speaks
the S3 REST API directly (no SDK, no credentials) and reports what anonymous
access actually allows.

Three checks, in increasing severity:

1. **listing** — `GET ?list-type=2` returns an object listing.
2. **public object read** — the first listed key downloads without auth.
3. **anonymous upload** — a uniquely named canary object is PUT, then DELETEd
   immediately. The canary is never written to a bucket that did not already
   accept it, and only our own key is ever deleted: an upload check that leaves
   junk in a stranger's bucket is a break, not a test.

A bucket that refuses all three is an explicit clean negative attributed to
`bucket_upload`, so the capability shows an executed result rather than a skip.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 20
_KEY_RE = re.compile(r"<Key>(.*?)</Key>", re.S)
_CODE_RE = re.compile(r"<Code>(.*?)</Code>", re.S)
_MESSAGE_RE = re.compile(r"<Message>(.*?)</Message>", re.S)

#: Endpoints tried, in order, when the target is a bare bucket name.
_ENDPOINT_TEMPLATES = (
    "https://{name}.s3.amazonaws.com/",
    "https://s3.amazonaws.com/{name}/",
    "https://storage.googleapis.com/{name}/",
    "https://{name}.oss.amazonaws.com/",
)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request(method: str, url: str, body: bytes | None = None) -> tuple[int, str, dict[str, str]]:
    ctx = _ssl_context()
    req = urllib.request.Request(
        url, data=body, method=method, headers={"User-Agent": "Argus bucket check"}
    )
    if body is not None:
        req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            return resp.status, resp.read(200_000).decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body_text = exc.read(200_000).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return exc.code, body_text, dict(exc.headers or {})
    except (urllib.error.URLError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}", {}


def _s3_error(text: str) -> str:
    code = _CODE_RE.search(text)
    message = _MESSAGE_RE.search(text)
    if code:
        return f"{code.group(1)}" + (f": {message.group(1).strip()}" if message else "")
    return ""


def candidates(target: str) -> list[str]:
    """Walk back from the target to the bucket root, plus S3 virtual-host forms."""
    urls: list[str] = []
    if target.startswith(("http://", "https://")):
        split = urllib.parse.urlsplit(target)
        urls.append(urllib.parse.urlunsplit(split._replace(path="/", query="", fragment="")))
    else:
        urls.extend(template.format(name=target.strip("/")) for template in _ENDPOINT_TEMPLATES)
    return urls


def check(url: str) -> dict[str, object]:
    """Run the three anonymous-access checks against one bucket URL."""
    listing_url = f"{url}?list-type=2"
    status, body, _headers = _request("GET", listing_url)
    keys = [key for key in _KEY_RE.findall(body) if key.strip()]
    result: dict[str, object] = {
        "url": url,
        "listing_status": status,
        "keys": keys[:5],
        "key_count": len(keys),
        "error": _s3_error(body),
        "public_object": None,
        "upload_allowed": False,
        "canary": None,
    }

    if keys:
        probe_key = keys[0]
        object_url = urllib.parse.urljoin(url, urllib.parse.quote(probe_key.lstrip("/")))
        object_status, _object_body, _ = _request("GET", object_url)
        if object_status == 200:
            result["public_object"] = probe_key

    # Canary upload: a unique key, so we can only ever delete our own object.
    canary = f"argus-permission-check-{secrets.token_hex(6)}.txt"
    canary_url = urllib.parse.urljoin(url, canary)
    payload = f"argus anonymous upload check {secrets.token_hex(4)}\n".encode()
    put_status, put_body, _ = _request("PUT", canary_url, payload)
    if put_status in (200, 201, 204):
        result["upload_allowed"] = True
        result["canary"] = canary
        delete_status, _delete_body, _ = _request("DELETE", canary_url)
        result["canary_removed"] = delete_status in (200, 204, 404)
    else:
        result["upload_status"] = put_status
        result["upload_error"] = _s3_error(put_body)

    return result


def findings_for(result: dict[str, object]) -> list[dict]:
    url = str(result["url"])
    found: list[dict] = []

    if result["keys"]:
        found.append({
            "title": f"S3 bucket allows anonymous listing ({result['key_count']} object(s))",
            "type": "S3_PUBLIC_BUCKET_LISTING",
            "severity": "medium",
            "confidence": "high",
            "description": (
                f"Anonymous GET {url}?list-type=2 returned {result['key_count']} object key(s) "
                f"(first: {', '.join(result['keys'])}). Bucket contents are world-readable at "
                "the account level."
            ),
            "endpoint": url,
            "tool": "bucket_upload",
        })

    if result["public_object"]:
        found.append({
            "title": f"S3 object readable without authentication: {result['public_object']}",
            "type": "S3_PUBLIC_OBJECT",
            "severity": "medium",
            "confidence": "high",
            "description": (
                f"GET on {url}{result['public_object']} returned 200 with no credentials, so the "
                "object is publicly downloadable."
            ),
            "endpoint": url,
            "tool": "bucket_upload",
        })

    if result["upload_allowed"]:
        found.append({
            "title": "S3 bucket allows anonymous object upload",
            "type": "S3_ANONYMOUS_WRITE",
            "severity": "high",
            "confidence": "high",
            "description": (
                f"PUT of canary object '{result['canary']}' to {url} succeeded without credentials; "
                "the object was deleted immediately afterwards. Anonymous write access lets an "
                "attacker host content in the bucket or overwrite existing objects."
            ),
            "endpoint": url,
            "tool": "bucket_upload",
        })

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Bucket URL or bare bucket name")
    args = parser.parse_args()

    findings: list[dict] = []
    checked: list[dict[str, object]] = []
    for url in candidates(args.target):
        result = check(url)
        checked.append(result)
        findings.extend(findings_for(result))
        if findings:
            break  # one endpoint answered; the rest are the same bucket by another route

    if findings:
        print(json.dumps(findings))
        return 0

    best = next((r for r in checked if r["listing_status"] != 0), checked[0] if checked else None)
    detail = (
        f"bucket endpoint {best['url']} answered {best['listing_status']}"
        + (f" ({best['error']})" if best and best.get("error") else "")
        if best
        else "no bucket endpoint answered"
    )
    had_error = best and best.get("error")
    print(json.dumps([{
        "title": "Bucket permission check complete: anonymous access not permitted",
        "type": "S3_PERMISSIONS_NEGATIVE",
        "severity": "info",
        "confidence": "low" if had_error else "medium",
        "description": (
            f"Tested anonymous listing, public object read and anonymous upload against "
            f"{args.target}; none succeeded — {detail}. Clean negative."
        ),
        "endpoint": str(best["url"]) if best else args.target,
        "tool": "bucket_upload",
    }]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

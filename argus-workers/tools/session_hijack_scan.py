#!/usr/bin/env python3
"""Local session-hijack probe for the session_hijack_attempt capability.

Nothing in the tool set performed a session takeover check, so a replanned
`session_hijack_attempt` phase had no provider at all and was skipped. This is a
self-contained (stdlib only, no external service) probe that does what an
analyst does before attempting a takeover:

  * reads the session cookie the target issues and checks the attributes that
    decide whether a hijack is possible at all (HttpOnly, Secure, SameSite);
  * measures the identifier: sequential/short ids are forgeable, so it probes a
    neighbouring id and reports whether the server accepts it as a session;
  * checks session fixation: a client-supplied identifier that the server
    adopts without rotating is a takeover primitive;
  * looks for session identifiers placed in URLs (leak via Referer/logs).

The probe is read-only: GET requests with a cookie header, no state changes.
Finding nothing is a result ("no hijackable session observed"), not a failure,
so it always exits 0 with a JSON summary.

Usage: python3 session_hijack_scan.py --target http://host/
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request

UA = "Argus-Session-Hijack/1.0"
SEQUENTIAL_RE = re.compile(r"^(?:user-)?(\d+)$", re.IGNORECASE)
URL_SESSION_RE = re.compile(r"[?&;](?:jsessionid|phpsessid|session|sid|sessionid)=", re.IGNORECASE)

#: Cookies that are not session identifiers.
_NON_SESSION = ("csrf", "xsrf", "consent", "locale", "lang", "theme")


def _request(url: str, cookie: str | None = None) -> tuple[int, str, list[str]]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            set_cookie = resp.headers.get_all("Set-Cookie") or []
            return resp.status, resp.read(256_000).decode("utf-8", "replace"), set_cookie
    except urllib.error.HTTPError as exc:
        set_cookie = exc.headers.get_all("Set-Cookie") or []
        return exc.code, "", set_cookie


def _parse_cookie(raw: str) -> tuple[str, str, str]:
    parts = [p.strip() for p in raw.split(";")]
    name, _, value = parts[0].partition("=")
    return name.strip(), value.strip(), raw.lower()


def _finding(title: str, severity: str, description: str, evidence: dict) -> dict:
    return {
        "type": "SESSION_HIJACK",
        "severity": severity,
        "title": title,
        "description": description,
        "evidence": evidence,
        "confidence": 1.0,
        "tool": "session_hijack_scan",
    }


def analyse(target: str) -> dict:
    findings: list[dict] = []
    notes: list[str] = []

    try:
        status, body, set_cookies = _request(target)
    except (urllib.error.URLError, OSError) as exc:
        return {"findings": [], "note": f"target unreachable: {exc}"}

    if URL_SESSION_RE.search(target):
        findings.append(
            _finding(
                "Session identifier carried in the URL",
                "MEDIUM",
                "The request URL carries a session identifier, which leaks through "
                "Referer headers, logs and shared links.",
                {"url": target},
            )
        )

    session_cookies = []
    for raw in set_cookies:
        name, value, lower = _parse_cookie(raw)
        if any(token in name.lower() for token in _NON_SESSION):
            continue
        session_cookies.append((name, value, raw, lower))

    if not session_cookies:
        notes.append("no session cookie issued on the landing page")

    for name, value, raw, lower in session_cookies:
        missing = [attr for attr in ("httponly", "secure", "samesite") if attr not in lower]
        if missing:
            findings.append(
                _finding(
                    f"Session cookie without {', '.join(missing)}",
                    "HIGH" if "httponly" in missing else "MEDIUM",
                    f"Cookie {name!r} is set without {', '.join(missing)}. Without "
                    "HttpOnly a single XSS reads it; without SameSite it is sent on "
                    "cross-site requests; without Secure it travels over plaintext HTTP.",
                    {"cookie": name, "value": value, "missing_attributes": missing, "set_cookie": raw},
                )
            )

        if len(value) <= 12 or SEQUENTIAL_RE.match(value):
            findings.append(
                _finding(
                    f"Predictable session identifier in {name}",
                    "HIGH",
                    f"Cookie {name!r} = {value!r} is short or sequential, so a valid "
                    "session id can be guessed rather than stolen.",
                    {"cookie": name, "value": value},
                )
            )

        # Active check (read-only): does the server adopt a neighbouring id?
        match = SEQUENTIAL_RE.match(value)
        if match:
            neighbour = str(int(match.group(1)) + 1)
            forged = value[: match.start(1)] + neighbour
            try:
                f_status, f_body, f_set = _request(target, cookie=f"{name}={forged}")
            except (urllib.error.URLError, OSError):
                f_status, f_body, f_set = 0, "", []
            rotated = any(name == _parse_cookie(c)[0] and forged not in c for c in f_set)
            accepted = f_status == status and not rotated
            if accepted and f_body.strip():
                findings.append(
                    _finding(
                        f"Forged session identifier accepted by the server ({name})",
                        "CRITICAL",
                        f"Requesting the target with {name}={forged!r} (a neighbouring id "
                        "of an issued session) returned the same page as the original "
                        "session instead of rejecting or rotating it: sessions can be "
                        "taken over by enumerating identifiers.",
                        {
                            "cookie": name,
                            "issued": value,
                            "forged": forged,
                            "status": f_status,
                            "rotated": rotated,
                        },
                    )
                )

    # Fixation: a client-chosen identifier that survives the response is a
    # fixation primitive (the attacker plants it, the victim logs in with it).
    if session_cookies:
        name = session_cookies[0][0]
        planted = "argusfix123456"
        try:
            _, _, fix_set = _request(target, cookie=f"{name}={planted}")
        except (urllib.error.URLError, OSError):
            fix_set = []
        adopted = any(
            _parse_cookie(c)[0] == name and _parse_cookie(c)[1] == planted for c in fix_set
        )
        if adopted:
            findings.append(
                _finding(
                    f"Session fixation: server adopts a client-supplied {name}",
                    "HIGH",
                    "The server echoes back the session identifier supplied by the "
                    "client instead of issuing a fresh one, so an attacker can fix a "
                    "known session id and take it over after the victim logs in.",
                    {"cookie": name, "planted": planted},
                )
            )

    return {
        "findings": findings,
        "note": "; ".join(notes) if notes else "",
        "target": target,
        "status": status,
        "session_cookies": [c[0] for c in session_cookies],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Session hijack probe (local, read-only)")
    parser.add_argument("--target", required=True, help="Target URL")
    args = parser.parse_args(argv)

    result = analyse(args.target)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

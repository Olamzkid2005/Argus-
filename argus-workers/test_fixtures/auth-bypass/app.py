"""Small, resettable discovery/verification lab (Stage 7.1).

The fixture is still intentionally tiny, but it now exposes the signals a
scanner has to *discover* rather than knowing from source:

  GET  /                    — landing page with the login form and API links
  GET  /login               — renders the same login form
  POST /login               — form or JSON login (session cookie)
  GET  /logout              — clears the session
  GET  /api/docs            — API description listing the resources below
  GET  /api/me              — the authenticated identity
  GET  /api/data/<id>       — VULNERABLE ownership check (any login reads any id)
  GET  /api/secure/data/<id>— secure twin (owner or admin only)
  GET  /admin/profile       — admin data with no access control
  GET  /admin/users         — credential list with no access control
  GET  /flag                — debug-header auth bypass
  GET  /health              — health check

Test-only endpoints (``LAB_TEST_MODE`` defaults on for this fixture):

  POST /__lab/reset         — reset users/resources and rotate the run marker
  GET  /__lab/requests      — the requests this target actually received

Every resource carries the run marker, so a finding can be tied to the run that
produced it. The answer manifest lives in the harness
(``scripts/livefire/lab-answer-manifest.json``), never in the target.
"""

from __future__ import annotations

import os
import threading
import uuid

from flask import Flask, jsonify, redirect, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("LAB_SECRET_KEY", "super-secret-key-12345")

_TEST_MODE = os.environ.get("LAB_TEST_MODE", "1") not in ("0", "false", "no")

# Two synthetic users plus an admin. Passwords stay predictable on purpose:
# weak credentials are one of the fixture's expected findings.
_USERS: dict[str, str] = {
    "user1": "welcome1",
    "user2": "welcome2",
    "admin": "password123",
}

# Templates are copied into the live store on reset, so every run starts from
# the same resources and gets a marker that is unique to that run.
_RESOURCE_TEMPLATE: list[dict] = [
    {"id": 10, "owner": "user1", "kind": "invoice", "amount": 1200},
    {"id": 11, "owner": "user2", "kind": "invoice", "amount": 2400},
    {"id": 12, "owner": "user1", "kind": "note", "text": "user1 private note"},
    {"id": 13, "owner": "user2", "kind": "note", "text": "user2 private note"},
    {"id": 1, "owner": "admin", "kind": "profile", "ssn": "000-00-0000"},
]

_RUN_LOCK = threading.Lock()
_RUN: dict = {"marker": "", "resources": [], "requests": [], "seq": 0}


def _new_marker() -> str:
    return uuid.uuid4().hex[:12]


def reset_lab(marker: str | None = None) -> str:
    """Reset resources and rotate the run marker. Returns the active marker."""
    new_marker = (marker or "").strip() or _new_marker()
    with _RUN_LOCK:
        _RUN["marker"] = new_marker
        _RUN["resources"] = [
            {**resource, "marker": new_marker} for resource in _RESOURCE_TEMPLATE
        ]
        _RUN["requests"] = []
        _RUN["seq"] = 0
    return new_marker


def _identity() -> str:
    return str(session.get("user", ""))


@app.after_request
def _log_request(response):
    """Target-side request log, used by the harness to prove traffic arrived."""
    with _RUN_LOCK:
        _RUN["seq"] += 1
        _RUN["requests"].append(
            {
                "seq": _RUN["seq"],
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "identity": _identity(),
                "marker": _RUN["marker"],
            }
        )
        # Bounded: this is a demo lab, not a production access log.
        del _RUN["requests"][:-500]
    return response


def _find_resource(data_id: int) -> dict | None:
    with _RUN_LOCK:
        for resource in _RUN["resources"]:
            if resource["id"] == data_id:
                return dict(resource)
    return None


def _login_form() -> str:
    return """
    <form method="post" action="/login">
      <label>Username <input name="username" autocomplete="username"></label>
      <label>Password <input name="password" type="password" autocomplete="current-password"></label>
      <button type="submit">Sign in</button>
    </form>
    """


@app.route("/")
def landing() -> str:
    """Discoverable entry point: login form, API docs and resource links."""
    return f"""<!doctype html>
<html><head><title>Argus Lab</title></head>
<body>
<h1>Argus ownership lab</h1>
<p>Run marker: <code>{_RUN['marker']}</code></p>
{_login_form()}
<h2>API</h2>
<ul>
  <li><a href="/api/docs">API description</a></li>
  <li><a href="/api/data/10">Invoice 10</a></li>
  <li><a href="/api/data/11">Invoice 11</a></li>
  <li><a href="/admin/profile">Admin profile</a></li>
  <li><a href="/xss">XSS playground</a></li>
</ul>
<h2>Out-of-scope sentinel</h2>
<ul><li><a href="https://sentinel.argus.invalid/do-not-scan">sentinel (not authorized)</a></li></ul>
</body></html>"""


@app.route("/xss")
def xss_redirect():
    """Point at the existing XSS fixture instead of duplicating its source."""
    return redirect(os.environ.get("XSS_FIXTURE_URL", "http://127.0.0.1:18766"))


@app.route("/login", methods=["GET"])
def login_form():
    return _login_form()


@app.route("/login", methods=["POST"])
def login():
    """Insecure login — weak passwords, no rate limiting, no lockout."""
    payload = request.get_json(silent=True) or request.form
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))

    if username in _USERS and _USERS[username] == password:
        session["user"] = username
        session["role"] = "admin" if username == "admin" else "user"
        if request.is_json:
            return jsonify({"status": "ok", "user": username}), 200
        return redirect("/")

    if request.is_json:
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    return "Invalid credentials", 401


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


@app.route("/api/docs")
def api_docs():
    """API description a crawler can discover from the landing page."""
    return jsonify(
        {
            "name": "Argus ownership lab API",
            "version": "1",
            "marker": _RUN["marker"],
            "auth": {"login": "POST /login", "form": ["username", "password"]},
            "endpoints": [
                {"method": "GET", "path": "/api/me", "auth": True},
                {"method": "GET", "path": "/api/data/{id}", "auth": True},
                {"method": "GET", "path": "/api/secure/data/{id}", "auth": True},
                {"method": "GET", "path": "/admin/profile", "auth": False},
                {"method": "GET", "path": "/admin/users", "auth": False},
            ],
            "resources": [
                {"id": resource["id"], "owner": resource["owner"]}
                for resource in _RUN["resources"]
            ],
        }
    )


@app.route("/api/me")
def api_me():
    identity = _identity()
    if not identity:
        return jsonify({"error": "authentication required"}), 401
    return jsonify(
        {
            "user": identity,
            "role": session.get("role", "user"),
            "marker": _RUN["marker"],
        }
    )


@app.route("/api/data/<int:data_id>")
def api_data(data_id):
    """IDOR — authenticated users can read any owner's resource by id.

    The vulnerability is deliberately the missing ownership comparison
    (compare ``/api/secure/data/<id>``).
    """
    identity = _identity()
    if not identity:
        return jsonify({"error": "authentication required"}), 401

    resource = _find_resource(data_id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(
        {
            "data": resource,
            "requested_by": identity,
            "owner": resource["owner"],
            "marker": _RUN["marker"],
        }
    )


@app.route("/api/secure/data/<int:data_id>")
def api_secure_data(data_id):
    """Secure twin: the ownership check the vulnerable endpoint lacks."""
    identity = _identity()
    if not identity:
        return jsonify({"error": "authentication required"}), 401

    resource = _find_resource(data_id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    if resource["owner"] != identity and session.get("role") != "admin":
        return jsonify({"error": "Forbidden", "reason": "not the owner"}), 403
    return jsonify(
        {
            "data": resource,
            "requested_by": identity,
            "owner": resource["owner"],
            "marker": _RUN["marker"],
        }
    )


@app.route("/admin/profile")
def admin_profile():
    """No role check: any caller sees the admin profile and fake secret."""
    return jsonify(
        {
            "endpoint": "/admin/profile",
            "user": _identity() or "anonymous",
            "message": "Admin profile data",
            "secret_key": "sk-admin-1234567890abcdef",
            "marker": _RUN["marker"],
        }
    )


@app.route("/admin/users")
def admin_users():
    """No access control: returns every username and password."""
    return jsonify(
        {
            "users": [{"username": u, "password": p} for u, p in _USERS.items()],
            "marker": _RUN["marker"],
        }
    )


@app.route("/flag")
def flag():
    """Auth bypass via a debug header; no session required."""
    if request.headers.get("X-Debug-Token", "") == "argus-bypass-2026":
        return jsonify(
            {
                "flag": "ARGUS{XSS_AUTH_BYPASS_2026}",
                "message": "Access granted via debug header",
                "marker": _RUN["marker"],
            }
        ), 200
    return jsonify({"error": "Forbidden", "hint": "Debug header required"}), 403


@app.route("/health")
def health():
    return "ok"


@app.route("/__lab/reset", methods=["POST"])
def lab_reset():
    """Test-only reset; the harness calls this before each run."""
    if not _TEST_MODE:
        return jsonify({"error": "not found"}), 404
    payload = request.get_json(silent=True) or {}
    marker = reset_lab(payload.get("run_marker") or payload.get("marker"))
    return jsonify(
        {
            "ok": True,
            "marker": marker,
            "users": sorted(_USERS),
            "resources": [
                {"id": r["id"], "owner": r["owner"]} for r in _RUN["resources"]
            ],
        }
    )


@app.route("/__lab/requests")
def lab_requests():
    """Test-only target-side request log."""
    if not _TEST_MODE:
        return jsonify({"error": "not found"}), 404
    with _RUN_LOCK:
        return jsonify(
            {"marker": _RUN["marker"], "requests": list(_RUN["requests"])}
        )


reset_lab(os.environ.get("LAB_RUN_MARKER"))


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app.run(host="127.0.0.1", port=port)

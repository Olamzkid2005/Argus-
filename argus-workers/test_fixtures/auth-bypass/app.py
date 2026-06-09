"""Auth Bypass — intentionally vulnerable web app for auth/access-control testing.

Endpoints:
  GET  /health              — Health check
  POST /login               — Login with predictable credentials
  GET  /admin/profile       — Admin-only endpoint with no access control
  GET  /admin/users         — Admin-only endpoint exposed via IDOR
  GET  /api/data/<id>       — IDOR: user data accessible without ownership check
  GET  /flag                — Hidden admin-only endpoint with debug header bypass

Fixture design principle: Make fixtures intentionally tiny, not realistic.
A good fixture is a single vulnerable endpoint in ~30 lines. The purpose is
regression detection, not vulnerability training.
"""

from flask import Flask, jsonify, request, session

app = Flask(__name__)
app.secret_key = "super-secret-key-12345"  # Intentionally weak hardcoded secret

# In-memory user store — all passwords are weak/predictable
_USERS: dict[str, str] = {  # username -> password
    "admin": "password123",
    "user1": "welcome1",
    "analyst": "analyst123",
}

# In-memory user data for IDOR testing
_USER_DATA: dict[str, list[dict]] = {
    "admin": [{"id": 1, "account": "admin", "role": "admin", "ssn": "000-00-0000"},
              {"id": 2, "account": "admin", "role": "admin", "salary": 150000}],
    "user1": [{"id": 10, "account": "user1", "role": "user", "email": "user1@example.com"}],
    "analyst": [{"id": 20, "account": "analyst", "role": "analyst", "email": "analyst@example.com"}],
}


@app.route("/login", methods=["POST"])
def login():
    """Insecure login — accepts weak passwords, no rate limiting, no account lockout.

    Returns a session cookie on any valid username/password match.
    Vulnerabilities:
    - Weak passwords accepted (admin/password123)
    - No rate limiting on the endpoint
    - No account lockout after failures
    - Session is created even with predictable credentials
    """
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    if username in _USERS and _USERS[username] == password:
        session["user"] = username
        session["role"] = "admin" if username == "admin" else "user"
        return jsonify({"status": "ok", "user": username}), 200

    return jsonify({"status": "error", "message": "Invalid credentials"}), 401


@app.route("/admin/profile")
def admin_profile():
    """Admin profile — no access control check.

    Anyone with a session can view the admin profile, even non-admin users.
    There's no role check. This is a Broken Access Control vulnerability.
    """
    user = session.get("user", "anonymous")
    return jsonify({
        "endpoint": "/admin/profile",
        "user": user,
        "message": "Admin profile data",
        "secret_key": "sk-admin-1234567890abcdef",
    })


@app.route("/admin/users")
def admin_users():
    """Admin users list — no access control, exposes all user accounts.

    Returns the full user list without checking if the requester is an admin.
    This is a mass assignment / information disclosure vulnerability.
    """
    return jsonify({
        "users": [
            {"username": u, "password": p}
            for u, p in _USERS.items()
        ]
    })


@app.route("/api/data/<int:data_id>")
def api_data(data_id):
    """IDOR — user data accessible by ID without ownership verification.

    Any authenticated user can access any data record by guessing/iterating IDs.
    There's no check that the data belongs to the requesting user.
    """
    user = session.get("user", "anonymous")

    # Search across ALL users' data — no ownership filter
    for username, records in _USER_DATA.items():
        for record in records:
            if record["id"] == data_id:
                return jsonify({
                    "data": record,
                    "requested_by": user,
                    "owner": username,
                })

    return jsonify({"error": "Not found"}), 404


@app.route("/flag")
def flag():
    """Hidden admin endpoint — gated only by a debug header.

    No session or authentication required — just a custom header.
    This simulates security-by-obscurity and debug-backdoor vulnerabilities.
    """
    debug_token = request.headers.get("X-Debug-Token", "")
    if debug_token == "argus-bypass-2026":
        return jsonify({"flag": "ARGUS{XSS_AUTH_BYPASS_2026}", "message": "Access granted via debug header"}), 200

    return jsonify({"error": "Forbidden", "hint": "Debug header required"}), 403


@app.route("/health")
def health():
    """Health check endpoint used by test fixtures to confirm the app is up."""
    return "ok"


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app.run(host="127.0.0.1", port=port)

"""HTML Forms — web app with HTML-based login and registration forms.

Purpose: Test fixture for the form discovery path in the login/register tools.
Serves actual HTML pages with ``<form>`` tags so that ``discover_auth_endpoints``
can extract field names via BeautifulSoup.

Endpoints:
  GET  /health              — Health check
  GET  /login               — Login page (HTML form)
  POST /login               — Login form handler
  GET  /register            — Registration page (HTML form)
  POST /register            — Registration form handler
  GET  /admin               — Admin page (requires session)

Fixture design principle: Make fixtures intentionally tiny, not realistic.
A good fixture is a single vulnerable endpoint in ~30 lines. The purpose is
regression detection, not vulnerability training.
"""

from __future__ import annotations

import html
import uuid

from flask import Flask, make_response, redirect, request, session

app = Flask(__name__)
app.secret_key = "insecure-fixture-secret-2026"

# In-memory user store: email -> password
_USERS: dict[str, str] = {
    "admin@test.com": "password123",
    "user@test.com": "welcome1",
}

# In-memory CSRF token store: token -> bool (used once)
_CSRF_TOKENS: dict[str, bool] = {}


def _csrf_token() -> str:
    """Generate a CSRF token and store it."""
    token = uuid.uuid4().hex
    _CSRF_TOKENS[token] = True
    return token


def _verify_csrf(token: str | None) -> bool:
    """Verify a CSRF token without consuming it.

    Tokens are NOT consumed so that retry logic in the login tool
    (which extracts the CSRF value once and reuses it) continues to
    work across multiple attempts.
    """
    if token and token in _CSRF_TOKENS:
        return True
    return False


# ── Login ──


@app.route("/login", methods=["GET"])
def login_page():
    """Render the login page with an HTML form."""
    token = _csrf_token()
    html_content = f"""<!DOCTYPE html>
<html>
<head><title>Sign In</title></head>
<body>
  <h1>Sign In</h1>
  <form method="post" action="/login">
    <input name="_token" type="hidden" value="{token}">
    <label>Email: <input name="email" type="email" required></label><br>
    <label>Password: <input name="password" type="password" required></label><br>
    <button type="submit">Sign In</button>
  </form>
  <p><a href="/register">Create an account</a></p>
</body>
</html>"""
    resp = make_response(html_content, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route("/login", methods=["POST"])
def login_handler():
    """Handle login form submission."""
    csrf = request.form.get("_token")
    if not _verify_csrf(csrf):
        return "<h1>CSRF validation failed</h1>", 403

    email = request.form.get("email", "")
    password = request.form.get("password", "")

    stored_password = _USERS.get(email)
    if stored_password and stored_password == password:
        session["user"] = email
        return redirect("/admin")

    return (
        "<h1>Invalid credentials</h1>"
        '<p><a href="/login">Try again</a></p>',
        401,
    )


# ── Registration ──


@app.route("/register", methods=["GET"])
def register_page():
    """Render the registration page with an HTML form."""
    token = _csrf_token()
    html_content = f"""<!DOCTYPE html>
<html>
<head><title>Create Account</title></head>
<body>
  <h1>Create Account</h1>
  <form method="post" action="/register">
    <input name="_token" type="hidden" value="{token}">
    <label>Full Name: <input name="full_name" type="text" required></label><br>
    <label>Email: <input name="email" type="email" required></label><br>
    <label>Password: <input name="password" type="password" required></label><br>
    <label>Confirm Password: <input name="password_confirm" type="password" required></label><br>
    <button type="submit">Register</button>
  </form>
  <p><a href="/login">Already have an account?</a></p>
</body>
</html>"""
    resp = make_response(html_content, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route("/register", methods=["POST"])
def register_handler():
    """Handle registration form submission."""
    csrf = request.form.get("_token")
    if not _verify_csrf(csrf):
        return "<h1>CSRF validation failed</h1>", 403

    email = request.form.get("email", "")
    password = request.form.get("password", "")
    confirm = request.form.get("password_confirm", "")

    if not email or not password:
        return "<h1>Email and password are required</h1>", 400

    if password != confirm:
        return "<h1>Passwords do not match</h1>", 400

    if len(password) < 6:
        return "<h1>Password must be at least 6 characters</h1>", 400

    if email in _USERS:
        return "<h1>Email already registered</h1>", 409

    _USERS[email] = password
    session["user"] = email
    return redirect("/admin")


# ── Admin (authenticated) ──


@app.route("/admin")
def admin_page():
    """Admin page — requires valid session."""
    user = session.get("user")
    if not user:
        return redirect("/login")
    return (
        f"<h1>Welcome, {html.escape(user)}</h1>"
        f"<p>You are logged in.</p>"
        f'<p><a href="/logout">Log out</a></p>'
    )


@app.route("/logout")
def logout():
    """Log out and clear session."""
    session.clear()
    return redirect("/login")


# ── Health ──


@app.route("/health")
def health():
    """Health check endpoint."""
    return "ok"


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app.run(host="127.0.0.1", port=port)

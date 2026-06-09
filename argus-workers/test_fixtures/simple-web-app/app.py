"""Intentionally minimal web app with known vulnerabilities for E2E smoke testing.

This is NOT a realistic application. It is a deliberately small (~30 line)
fixture designed to exercise the Argus scan pipeline against a real HTTP
server and confirm that process-boundary bugs (subprocess invocation, JSON
output parsing, timeout handling) are caught in CI.

Each endpoint exists to trigger a specific scanner detection:

  GET /user?id=<n>   — SQL injection via string interpolation in SQL query
  GET /health        — health check endpoint (returns 200 OK)

Fixture design principle: Make fixtures intentionally tiny, not realistic.
A good fixture is a single vulnerable endpoint in ~30 lines. The purpose is
regression detection, not vulnerability training.
"""

from flask import Flask, request

app = Flask(__name__)


@app.route("/user")
def user():
    """Vulnerable endpoint: SQL injection via string interpolation.

    Intentionally constructs a SQL query with unsanitized user input.
    sqlmap or similar tools should detect this as SQL injection.
    """
    user_id = request.args.get("id", "1")
    # Intentionally vulnerable — string interpolation in SQL query
    return f"SELECT * FROM users WHERE id={user_id}"


@app.route("/health")
def health():
    """Health check endpoint used by test fixtures to confirm the app is up."""
    return "ok"


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app.run(host="127.0.0.1", port=port)

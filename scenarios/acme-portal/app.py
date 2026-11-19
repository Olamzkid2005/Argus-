#!/usr/bin/env python3
"""Acme Expense Portal — an intentionally vulnerable web app for Argus drills.

Fictional context: "Acme Logistics" runs a small internal expense portal for its
sales staff. It was shipped by a contractor in 2019 and never reviewed. The
security team has written authorization to test it; this file exists so an
assessment can be run end to end against a realistic target instead of a
placeholder host.

Deliberate weaknesses (each maps to something a real portal gets wrong):
  * SQL injection in the login form (string-built query)
  * IDOR on /api/expenses (any id readable without an ownership check)
  * Unauthenticated /admin panel
  * Reflected XSS on /search
  * Open redirect on /redirect
  * CORS reflecting any Origin with credentials allowed
  * Session cookie without HttpOnly/Secure, no security headers at all
  * /.env served as a static file, leaking production credentials
  * Verbose framework banners in the Server and X-Powered-By headers

Run it with the repo's worker virtualenv, which already has Flask:
    argus-workers/venv/bin/python scenarios/acme-portal/app.py --port 8080
"""

from __future__ import annotations

import argparse
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent

PAGE = """<!doctype html>
<html><head><title>Acme Expense Portal</title>
<link rel="stylesheet" href="/static/portal.css"></head>
<body>
  <h1>Acme Logistics — Expense Portal</h1>
  <p>Sign in with your sales account to submit receipts.</p>
  <form method="post" action="/login">
    <label>Username <input name="username"></label>
    <label>Password <input name="password" type="password"></label>
    <button type="submit">Sign in</button>
  </form>
  <p class="footer">Build 2019.11 — support: helpdesk@acme-logistics.example</p>
</body></html>
"""

ADMIN = """<!doctype html>
<html><head><title>Acme admin</title></head><body>
<h1>Administration</h1>
<p>Pending reimbursements: 14</p>
<table><tr><th>Employee</th><th>Amount</th></tr>
<tr><td>j.rivera</td><td>1,240.00</td></tr>
<tr><td>m.okafor</td><td>318.50</td></tr></table>
<form method="post" action="/admin/payout"><button>Approve all</button></form>
</body></html>
"""

DB_SEED = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT);
INSERT INTO users VALUES (1, 'j.rivera', 'summer2019', 'employee');
INSERT INTO users VALUES (2, 'm.okafor', 'Expense!42', 'employee');
INSERT INTO users VALUES (3, 'admin', 'AcmeAdmin!2019', 'admin');
CREATE TABLE expenses (id INTEGER PRIMARY KEY, user_id INTEGER, vendor TEXT, amount REAL, note TEXT);
INSERT INTO expenses VALUES (1, 1, 'Delta Air Lines', 412.90, 'Client visit, Chicago');
INSERT INTO expenses VALUES (2, 2, 'Uber', 38.20, 'Airport transfer');
INSERT INTO expenses VALUES (3, 3, 'AWS', 9180.00, 'Production hosting');
"""


def make_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.executescript(DB_SEED)
    return db


class Handler(BaseHTTPRequestHandler):
    server_version = "Werkzeug/2.0.1"
    sys_version = "Python/3.7.3"
    db: sqlite3.Connection

    # ── helpers ────────────────────────────────────────────────────────────
    def _send(self, status: int, body: str, ctype="text/html; charset=utf-8", extra=None):
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Powered-By", "PHP/7.4.3")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):  # quieter console, still realistic
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    # ── routes ─────────────────────────────────────────────────────────────
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)

        if url.path == "/":
            return self._send(200, PAGE, extra={"Set-Cookie": "portal_session=guest; Path=/"})

        if url.path == "/admin":
            return self._send(200, ADMIN)

        if url.path == "/search":
            term = (query.get("q") or [""])[0]
            # Reflected without escaping: the term is written straight back.
            body = (
                "<html><body><h2>Expense search</h2>"
                f"<p>Results for <b>{term}</b>: none</p></body></html>"
            )
            return self._send(200, body)

        if url.path == "/redirect":
            target = (query.get("next") or ["/"])[0]
            return self._send(302, "", extra={"Location": target})

        if url.path == "/api/expenses":
            raw_id = (query.get("id") or ["1"])[0]
            try:
                expense_id = int(raw_id)
            except ValueError:
                return self._send(400, '{"error":"bad id"}', "application/json")
            row = self.db.execute(
                "SELECT id, user_id, vendor, amount, note FROM expenses WHERE id = ?",
                (expense_id,),
            ).fetchone()
            if not row:
                return self._send(404, '{"error":"not found"}', "application/json")
            payload = (
                '{"id":%d,"user_id":%d,"vendor":"%s","amount":%.2f,"note":"%s"}'
                % (row[0], row[1], row[2], row[3], row[4])
            )
            return self._send(200, payload, "application/json")

        if url.path == "/api/users":
            # CORS misconfiguration: any origin is reflected, credentials allowed.
            origin = self.headers.get("Origin", "*")
            body = '[{"id":1,"username":"j.rivera"},{"id":2,"username":"m.okafor"}]'
            return self._send(
                200,
                body,
                "application/json",
                extra={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                },
            )

        if url.path == "/openapi.json":
            spec = (HERE / "openapi.json").read_text()
            return self._send(200, spec, "application/json")

        if url.path in ("/.env", "/.env.production"):
            return self._send(200, (HERE / "dotenv.txt").read_text(), "text/plain")

        if url.path == "/static/portal.css":
            return self._send(200, "body{font-family:sans-serif;margin:3rem}", "text/css")

        if url.path == "/health":
            return self._send(200, '{"status":"ok"}', "application/json")

        return self._send(404, "<h1>404 Not Found</h1>")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode(errors="replace")
        form = parse_qs(raw)
        url = urlparse(self.path)

        if url.path == "/login":
            username = (form.get("username") or [""])[0]
            password = (form.get("password") or [""])[0]
            # String-built SQL: the classic share of login bypasses.
            sql = (
                "SELECT id, username, role FROM users "
                f"WHERE username='{username}' AND password='{password}'"
            )
            try:
                row = self.db.execute(sql).fetchone()
            except sqlite3.Error as exc:
                return self._send(500, f"<h1>Login failed</h1><pre>{exc}</pre>")
            if not row:
                return self._send(401, "<h1>Invalid credentials</h1>")
            cookie = (
                f"portal_session=user-{row[0]}; Path=/"
                f"; Expires=Wed, 21 Oct 2026 07:28:00 GMT"
            )
            return self._send(
                302,
                "",
                extra={
                    "Location": "/admin" if row[2] == "admin" else "/",
                    "Set-Cookie": cookie,
                },
            )

        if url.path == "/admin/payout":
            return self._send(200, "<h1>Approved</h1><p>14 reimbursements paid out.</p>")

        return self._send(404, "<h1>404 Not Found</h1>")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    Handler.db = make_db()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Acme Expense Portal listening on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

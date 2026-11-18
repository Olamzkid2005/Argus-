"""Spec-driven API and GraphQL testing (``tools/api_spec_scan.py``).

The suite pins what the tool must never get wrong: the OpenAPI document decides
what is tested (secured operations first, nothing destructive), an operation-level
``security: []`` is public even when the document defaults to auth, and a clean
result is only reported after the canary target produced every finding class —
otherwise the run is a coverage gap.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

SCRIPTS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, SCRIPTS)

import api_spec_scan as a  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_canary_cache():
    """The canary verdict is process-wide; tests must not inherit it."""
    a._clear_canary_cache()
    yield
    a._clear_canary_cache()


@contextlib.contextmanager
def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _types(findings):
    return [item["type"] for item in findings]


def _served(handler_class, mode):
    class Handler(handler_class):
        pass

    Handler.mode = mode
    return Handler


# ── parsing the document ────────────────────────────────────────────


SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Shop", "version": "1"},
    "servers": [{"url": "https://api.example.com/v1"}],
    "security": [{"bearer": []}],
    "paths": {
        "/orders/{id}": {
            "get": {"responses": {"200": {"description": "ok"}}},
            "delete": {"responses": {"204": {"description": "gone"}}},
        },
        "/health": {"get": {"security": [], "responses": {"200": {"description": "ok"}}}},
        "/orders": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "item": {"type": "string"},
                                    "quantity": {"type": "integer"},
                                    "express": {"type": "boolean"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                },
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "created"}},
            }
        },
    },
}


def test_operations_are_secured_first_and_never_destructive():
    planned = a.operations(SPEC)
    assert [op.method for op in planned] != []
    assert all(op.method != "delete" for op in planned), "a scanner must not delete records"
    assert planned[0].secured, "secured operations carry the finding, so they run first"
    assert planned[0].path == "/orders/{id}"


def test_operation_level_empty_security_opts_out_of_global_requirement():
    planned = {op.path: op for op in a.operations(SPEC)}
    assert planned["/health"].secured is False, "`security: []` is explicitly public"
    assert planned["/orders/{id}"].secured is True


def test_request_body_example_is_synthesised_from_schema():
    planned = {op.path: op for op in a.operations(SPEC)}
    assert planned["/orders"].body == {"item": "argus", "quantity": 1, "express": False, "tags": ["argus"]}


def test_path_parameters_are_filled_in():
    op = next(op for op in a.operations(SPEC) if op.path == "/orders/{id}")
    assert a._operation_url("https://api.example.com/v1", op) == (
        "https://api.example.com/v1/orders/1?argus_probe=1"
    )


def test_server_url_is_resolved_against_the_document():
    assert a._server_base(SPEC, "https://api.example.com/openapi.json") == "https://api.example.com/v1"
    relative = {"servers": [{"url": "/v2"}], "paths": {}}
    assert a._server_base(relative, "https://api.example.com/docs/openapi.json") == "https://api.example.com/v2"
    swagger = {"host": "api.example.com", "basePath": "/v1", "schemes": ["http"]}
    assert a._server_base(swagger, "http://api.example.com/swagger.json") == "http://api.example.com/v1"


# ── spec mode against a real server ─────────────────────────────────


def test_secured_operation_and_weak_posture_are_flagged():
    url, server = a._canary_target("spec")
    try:
        kinds = _types(a.analyse_spec(url))
    finally:
        server.shutdown()
        server.server_close()
    assert "API_AUTH_BYPASS" in kinds
    assert "WILDCARD_CORS_API" in kinds
    assert "VERBOSE_API_ERROR" in kinds
    assert "MISSING_API_SECURITY_HEADERS" in kinds
    assert "API_NO_RATE_LIMIT" in kinds
    assert "EXPOSED_OPENAPI_SPEC" in kinds


def test_spec_is_discovered_under_the_given_base_path():
    """APIs usually publish the document under their base path (/api/v3), so the
    path the engagement supplies must not be dropped."""
    url, server = a._canary_target("spec")
    try:
        document, document_url, problem = a.discover_spec(url + "/v1")
    finally:
        server.shutdown()
        server.server_close()
    assert problem == ""
    assert document is not None
    assert document_url == url + "/v1/openapi.json"


def test_no_published_spec_is_a_result_not_a_failure():
    class NotFound(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):  # noqa: N802 — http.server API
            self.send_response(404)
            self.end_headers()

    with serve(NotFound) as base:
        findings = a.analyse_spec(base)
    assert _types(findings) == ["API_SPEC_NOT_APPLICABLE"]
    assert findings[0]["severity"] == "INFO"


def test_unreadable_document_is_a_coverage_gap():
    class WrongDocument(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):  # noqa: N802
            payload = b"<html>not api documentation</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with serve(WrongDocument) as base:
        findings = a.analyse_spec(base)
    assert _types(findings) == ["API_SPEC_COVERAGE_GAP"]


def test_unreachable_explicit_spec_url_is_a_coverage_gap():
    findings = a.analyse_spec("http://127.0.0.1:9", "http://127.0.0.1:9/openapi.json")
    assert _types(findings) == ["API_SPEC_COVERAGE_GAP"]
    assert "not tested" in findings[0]["description"]


HARDENED_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Hardened", "version": "1"},
    "paths": {"/items": {"get": {"responses": {"200": {"description": "ok"}}}}},
}


class HardenedAPI(BaseHTTPRequestHandler):
    """A well-behaved API: no CORS wildcard, security headers, Rate limiting."""

    calls = 0
    mode = "spec"

    def log_message(self, *args):
        return

    def _send(self, status, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/openapi.json"):
            self._send(200, HARDENED_SPEC)
            return
        type(self).calls += 1
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "deny",
            "Content-Security-Policy": "default-src 'none'",
        }
        self._send(429 if type(self).calls > 5 else 200, {"items": []}, headers)


def test_hardened_api_is_a_clean_negative():
    HardenedAPI.calls = 0
    with serve(HardenedAPI) as base:
        findings = a.analyse_spec(base)
    assert _types(findings) == ["EXPOSED_OPENAPI_SPEC", "API_SPEC_NEGATIVE"]
    assert findings[-1]["severity"] == "INFO"


def test_negative_is_withheld_when_the_canary_cannot_prove_coverage(monkeypatch):
    """A clean result is only allowed once the same code path flags the canary."""
    HardenedAPI.calls = 0
    monkeypatch.setattr(a, "_verify_canary", lambda mode: "canary target not flagged")
    with serve(HardenedAPI) as base:
        findings = a.analyse_spec(base)
    assert _types(findings) == ["API_SPEC_COVERAGE_GAP"]
    assert "unverified" in findings[0]["title"].lower()


# ── GraphQL mode ───────────────────────────────────────────────────


def test_graphql_canary_reports_every_class():
    url, server = a._canary_target("graphql")
    try:
        kinds = _types(a.analyse_graphql(url + "/graphql"))
    finally:
        server.shutdown()
        server.server_close()
    assert "GRAPHQL_INTROSPECTION_ENABLED" in kinds
    assert "GRAPHQL_DEPTH_LIMIT_MISSING" in kinds
    assert "GRAPHQL_UNAUTHENTICATED_MUTATION" in kinds
    assert "GRAPHQL_FIELD_SUGGESTION_LEAK" in kinds


class NoGraphQL(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):  # noqa: N802
        self.send_response(404)
        self.end_headers()

    def do_POST(self):  # noqa: N802
        self.send_response(404)
        self.end_headers()


def test_absent_graphql_endpoint_is_not_applicable():
    with serve(NoGraphQL) as base:
        findings = a.analyse_graphql(base)
    assert _types(findings) == ["GRAPHQL_NOT_APPLICABLE"]


class HardenedGraphQL(BaseHTTPRequestHandler):
    """Introspection off, mutations gated, no depth bypass, no field hints."""

    def log_message(self, *args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        query = str(json.loads(self.rfile.read(length) or b"{}").get("query") or "")
        if "__schema" in query:
            self._send(200, {"errors": [{"message": "introspection is disabled"}]})
        elif query.strip().startswith("mutation"):
            self._send(401, {"errors": [{"message": "authentication required"}]})
        elif "argusNoSuchField" in query:
            self._send(200, {"errors": [{"message": "Cannot query field."}]})
        else:
            self._send(200, {"errors": [{"message": "query too deep"}]})


def test_hardened_graphql_is_a_clean_negative_but_still_tests_mutations():
    with serve(HardenedGraphQL) as base:
        findings = a.analyse_graphql(base + "/graphql")
    assert _types(findings) == ["GRAPHQL_NEGATIVE"]
    assert "introspection" in findings[0]["title"].lower()


def test_depth_query_needs_a_cycle_in_the_schema():
    acyclic = {
        "queryType": {"name": "Query"},
        "types": [
            {"name": "Query", "kind": "OBJECT", "fields": [
                {"name": "user", "type": {"name": "User", "kind": "OBJECT"}},
            ]},
            {"name": "User", "kind": "OBJECT", "fields": [
                {"name": "name", "type": {"name": "String", "kind": "SCALAR"}},
            ]},
        ],
    }
    assert a._depth_query(acyclic) is None
    assert a._depth_query(a.CANARY_SCHEMA).count("friend") >= a.DEPTH - 1


# ── coverage guard ─────────────────────────────────────────────────


def test_canary_verdict_is_empty_for_both_modes():
    assert a._verify_canary("spec") == ""
    assert a._verify_canary("graphql") == ""


def test_canary_failure_names_the_missing_classes(monkeypatch):
    monkeypatch.setattr(a, "analyse_spec", lambda target, spec_url="": [])
    verdict = a._verify_canary("spec")
    assert "API_AUTH_BYPASS" in verdict


def test_verified_canary_is_cached_but_a_failure_is_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(a, "_verify_canary", lambda mode: calls.append(mode) or "")
    assert a._canary_problem("spec") == ""
    assert a._canary_problem("spec") == ""
    assert calls == ["spec"], "a verified canary should not be re-scanned"

    a._clear_canary_cache()
    monkeypatch.setattr(a, "_verify_canary", lambda mode: calls.append(mode) or "broken")
    assert a._canary_problem("graphql") == "broken"
    assert a._canary_problem("graphql") == "broken"
    assert calls == ["spec", "graphql", "graphql"], "a failure must be retried, not cached"


# ── CLI ────────────────────────────────────────────────────────────


def test_main_prints_a_json_list_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["api_spec_scan.py", "--mode", "graphql", "--target", "http://127.0.0.1:9"])
    assert a.main() == 0
    out = capsys.readouterr().out
    assert json.loads(out)[0]["type"] == "GRAPHQL_COVERAGE_GAP"

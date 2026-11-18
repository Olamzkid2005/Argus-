#!/usr/bin/env python3
"""Spec-driven API testing: OpenAPI/Swagger operations and GraphQL endpoints.

Two modes share one HTTP path and one coverage guard.

``--mode spec``
    Finds the target's OpenAPI/Swagger document (or uses ``--spec-url``), then
    replays what the document describes: secured operations without credentials
    (an object the app itself declared protected answering 2xx is an auth bypass),
    CORS headers on JSON responses, verbose error leakage, API security headers and
    rate limiting. Every test is driven by the document, so coverage is "the
    operations this API publishes" rather than whatever a wordlist guessed.

``--mode graphql``
    Finds the GraphQL endpoint, asks for introspection, a query deep enough that a
    depth limit would reject it, an unauthenticated ``mutation`` (only ``__typename``,
    nothing is changed) and a misspelled field (servers that answer with
    "Did you mean ..." disclose the schema even when introspection is off).

Neither mode may report a clean result it has not proven: before any negative, the
same code path runs against a local canary target that must produce every finding
class the negative would claim clean — the same rule the SAST/SCA shims follow. The
verdict is cached per mode for the life of the process, and only successes are
cached so a transient failure is retried instead of pinning a gap.

``ARGUS_API_AUTH_HEADER`` (e.g. ``"Authorization: Bearer <token>"``) supplies
credentials out of band so they never appear in argv; it is only used to check that
a protected operation really is exercised, never to bypass it.

Usage:
    python3 api_spec_scan.py --mode spec --target https://api.example.com
    python3 api_spec_scan.py --mode graphql --target https://api.example.com/graphql
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

TIMEOUT = 20
USER_AGENT = "Argus-API-Audit/1.0"

#: Operations replayed per document. A 400-operation spec must not turn one
#: engagement step into thousands of requests; the cap is reported in the evidence.
MAX_OPERATIONS = 25

#: Requests sent at one operation to see whether anything throttles it.
BURST = 12

#: Document locations, in the order an API gateway usually serves them.
SPEC_PATHS = (
    "/openapi.json",
    "/v3/api-docs",
    "/swagger.json",
    "/swagger/v1/swagger.json",
    "/api-docs",
    "/openapi.yaml",
)

GRAPHQL_PATHS = ("/graphql", "/api/graphql", "/v1/graphql", "/query", "/gql")

#: Methods replayed against a document. DELETE is never sent: a scanner that
#: deletes records to prove a missing check is doing the attacker's work for them.
SAFE_METHODS = ("get", "post", "put", "patch", "head")

VERBOSE_ERROR_MARKERS = (
    "traceback (most recent call last)",
    "stack trace",
    "sqlexception",
    "sqlstate[",
    "syntax error at or near",
    "exception in thread",
    "at java.",
    "node_modules/",
    "odbc drivers error",
)

#: Headers a JSON API should send on every response. Missing ones are reported once
#: per origin, not once per operation.
API_SECURITY_HEADERS = ("x-content-type-options", "x-frame-options", "content-security-policy")

#: (mode) -> "" once the canary target produced every finding class.
_CANARY_CACHE: dict[str, str] = {}


def _clear_canary_cache() -> None:
    _CANARY_CACHE.clear()


# ── plumbing ────────────────────────────────────────────────────────


@dataclass
class Reply:
    """One HTTP exchange. ``problem`` is set only when no response was received."""

    status: int = 0
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    problem: str = ""

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    @property
    def is_json(self) -> bool:
        return "json" in self.header("content-type").lower() or self.body.lstrip()[:1] in ("{", "[")

    @property
    def ok(self) -> bool:
        return not self.problem and 200 <= self.status < 300


def request(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> Reply:
    """One request with the audit's UA, TLS verification off (the target is under
    assessment, and a broken chain is testssl's finding, not a reason to skip)."""
    body = json.dumps(payload).encode() if payload is not None else None
    all_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    if body is not None:
        all_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=all_headers, method=method.upper())
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=context) as response:
            return Reply(
                status=response.status,
                body=response.read(400_000).decode("utf-8", "replace"),
                headers={key.lower(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read(200_000) if hasattr(exc, "read") else b""
        return Reply(
            status=exc.code,
            body=raw.decode("utf-8", "replace") if raw else "",
            headers={key.lower(): value for key, value in (exc.headers or {}).items()},
        )
    except (urllib.error.URLError, OSError) as exc:
        return Reply(problem=f"{type(exc).__name__}: {exc}")


def finding(
    kind: str,
    title: str,
    severity: str,
    endpoint: str,
    description: str,
    confidence: float = 0.85,
    evidence: dict | None = None,
) -> dict:
    return {
        "type": kind,
        "title": title,
        "severity": severity.upper(),
        "confidence": confidence,
        "endpoint": endpoint,
        "description": description,
        "evidence": evidence or {},
    }


def _base_url(target: str) -> str:
    """The target's origin plus any base path it was given. APIs commonly live under
    one (/api/v3), and dropping it would probe the wrong host locations."""
    value = target.strip() if "://" in target.strip() else f"https://{target.strip()}"
    parts = urllib.parse.urlsplit(value)
    origin = f"{parts.scheme or 'https'}://{parts.netloc or parts.path}"
    path = parts.path.rstrip("/")
    return f"{origin}{path}" if path.strip("/") else origin


def _origins(base: str) -> list[str]:
    """The target itself, then its site root — a spec is documented under the API's
    base path or at the origin, and both are worth one probe each."""
    parts = urllib.parse.urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    return [base] if origin == base else [base, origin]


def _auth_headers() -> dict[str, str]:
    raw = os.environ.get("ARGUS_API_AUTH_HEADER", "").strip()
    if not raw:
        return {}
    name, _, value = raw.partition(":")
    return {name.strip(): value.strip()} if name and value else {}


# ── OpenAPI / Swagger ──────────────────────────────────────────────


def _parse_document(body: str) -> dict | None:
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    try:  # YAML documents are common for Swagger; PyYAML ships with the workers.
        import yaml

        data = yaml.safe_load(body)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — an unparsable document is reported, not raised
        return None


def discover_spec(target: str, spec_url: str = "") -> tuple[dict | None, str, str]:
    """(document, url, problem). An empty problem with no document means the API
    publishes no specification at all — a result, not a broken run."""
    base = _base_url(target)
    candidates = (
        [spec_url] if spec_url
        else [origin + path for origin in _origins(base) for path in SPEC_PATHS]
    )
    broken = ""
    for url in candidates:
        reply = request(url)
        if reply.problem:
            broken = f"{url}: {reply.problem}"
            continue
        if reply.status != 200 or not reply.body.strip():
            if reply.status not in (401, 403, 404):
                broken = f"{url}: HTTP {reply.status}"
            continue
        document = _parse_document(reply.body)
        if document is None:
            broken = f"{url}: response is not a readable OpenAPI/Swagger document"
            continue
        return document, url, ""
    return None, "", broken


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    secured: bool
    body: dict | None


def _server_base(document: dict, spec_url: str) -> str:
    servers = document.get("servers") or []
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = str(servers[0].get("url") or "")
        if not url:
            return urllib.parse.urldefrag(spec_url)[0].rsplit("/", 1)[0]
        if url.startswith(("http://", "https://")):
            return url.rstrip("/")
        return urllib.parse.urljoin(spec_url, url).rstrip("/")
    # Swagger 2 puts the host in host/basePath instead of servers.
    host = str(document.get("host") or "")
    if host:
        scheme = str((document.get("schemes") or ["https"])[0])
        return f"{scheme}://{host}{document.get('basePath') or ''}".rstrip("/")
    parts = urllib.parse.urlsplit(spec_url)
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


def _example(schema: object, depth: int = 0) -> object:
    """A harmless value for a request body described by JSON schema."""
    if not isinstance(schema, dict) or depth > 3:
        return "argus"
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return (schema["enum"] or ["argus"])[0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {
            name: _example(value, depth + 1)
            for name, value in (schema.get("properties") or {}).items()
        }
    if kind == "array":
        return [_example(schema.get("items") or {}, depth + 1)]
    if kind in ("integer", "number"):
        return 1
    if kind == "boolean":
        return False
    return "argus"


def _body_for(operation: dict) -> dict | None:
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        content = request_body.get("content") or {}
        for media_type, media in content.items():
            if isinstance(media, dict) and "json" in media_type:
                return _example(media.get("schema") or {})  # type: ignore[return-value]
        return None
    # Swagger 2: parameters with in=body.
    for parameter in operation.get("parameters") or []:
        if isinstance(parameter, dict) and parameter.get("in") == "body":
            return _example(parameter.get("schema") or {})  # type: ignore[return-value]
    return None


def operations(document: dict) -> list[Operation]:
    """Every operation the document describes that can be replayed safely, with
    secured operations first — the ones that carry the finding."""
    global_security = bool(document.get("security"))
    found: list[Operation] = []
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() not in SAFE_METHODS or not isinstance(operation, dict):
                continue
            # OpenAPI: an operation-level list replaces the global one, so `security: []`
            # marks a public operation even when the document requires auth by default.
            secured = bool(operation["security"]) if "security" in operation else global_security
            found.append(Operation(method.lower(), str(path), secured, _body_for(operation)))
    found.sort(key=lambda op: (not op.secured, op.method not in ("get", "head")))
    return found[:MAX_OPERATIONS]


def _operation_url(base: str, operation: Operation) -> str:
    path = operation.path
    for name in {part.split("}")[0] for part in path.split("{")[1:]}:
        path = path.replace("{" + name + "}", "1")
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if operation.method in ("get", "head"):
        query = urllib.parse.urlencode({"argus_probe": "1"})
        url += ("&" if "?" in url else "?") + query
    return url


def _confirmed_protected(base: str, operation: Operation, auth: dict[str, str]) -> bool:
    """False when the operation can be reached with credentials and that replay
    succeeds, i.e. the unauthenticated 2xx is a real bypass rather than a path that
    exists only for the unauthenticated caller. Without credentials there is
    nothing to compare, so the 2xx stands as the only evidence available."""
    if not auth:
        return False
    reply = request(_operation_url(base, operation), operation.method, operation.body, auth)
    return reply.ok


def analyse_spec(target: str, spec_url: str = "") -> list[dict]:
    base = _base_url(target)
    document, document_url, problem = discover_spec(target, spec_url)
    if document is None:
        if problem:
            return [finding(
                "API_SPEC_COVERAGE_GAP",
                "Spec-driven API testing could not run",
                "MEDIUM",
                base,
                f"No usable OpenAPI/Swagger document could be read from {base} ({problem}). The API was "
                "not tested by its own contract; treat its endpoints as unaudited.",
            )]
        return [finding(
            "API_SPEC_NOT_APPLICABLE",
            f"No API specification published on {base}",
            "INFO",
            base,
            f"{base} serves no OpenAPI/Swagger document at the usual locations "
            f"({', '.join(SPEC_PATHS)}), so there is no contract to replay. This says nothing about "
            "whether the API is safe.",
        )]

    api_base = _server_base(document, document_url)
    planned = operations(document)
    findings: list[dict] = [finding(
        "EXPOSED_OPENAPI_SPEC" if not spec_url else "API_SPEC_ANALYSED",
        (
            f"OpenAPI document published on {base} ({len(planned)} operations tested)"
            if not spec_url
            else f"OpenAPI document analysed ({len(planned)} operations tested)"
        ),
        "LOW" if not spec_url else "INFO",
        document_url,
        f"{document_url} describes {document.get('info', {}).get('title', 'this API')} and is being "
        f"replayed against {api_base}. Published contracts hand an attacker the full endpoint list, "
        "parameter names and auth scheme; serve them to authenticated users only where possible.",
        confidence=0.9,
        evidence={"operations": len(planned), "base": api_base, "replayed": MAX_OPERATIONS},
    )]

    if not planned:
        findings.append(finding(
            "API_SPEC_COVERAGE_GAP",
            "OpenAPI document describes no replayable operation",
            "MEDIUM",
            document_url,
            "The document parses but lists no get/post/put/patch operation (or only paths with "
            "unsupported methods), so no operation was exercised. Not a clean API test.",
        ))
        return findings

    auth = _auth_headers()
    bypasses = 0
    checked = 0
    cors_reported = False
    headers_reported = False
    burst_reported = False
    reachable: list[Operation] = []

    for operation in planned:
        url = _operation_url(api_base, operation)
        reply = request(url, operation.method, operation.body)
        if not reply.problem:
            reachable.append(operation)
        if reply.problem:
            continue
        checked += 1

        if operation.secured and reply.ok and reply.is_json:
            bypasses += 1
            findings.append(finding(
                "API_AUTH_BYPASS",
                f"Secured operation {operation.method.upper()} {operation.path} answered without credentials",
                "HIGH",
                url,
                f"The document marks this operation as requiring authentication, but it returned "
                f"HTTP {reply.status} with a JSON body when sent with no credentials. "
                "Unauthenticated access to a declared-protected API operation."
                + ("" if not auth or _confirmed_protected(api_base, operation, auth) else
                   " The same request with ARGUS_API_AUTH_HEADER did not succeed, so confirm the "
                   "operation is genuinely reachable before acting on this."),
                confidence=0.9 if not auth or _confirmed_protected(api_base, operation, auth) else 0.6,
                evidence={
                    "status": reply.status,
                    "declared_security": operation.secured,
                    "body_excerpt": reply.body[:300],
                },
            ))

        lowered = reply.body.lower()
        marker = next((text for text in VERBOSE_ERROR_MARKERS if text in lowered), "")
        if marker:
            findings.append(finding(
                "VERBOSE_API_ERROR",
                f"Verbose error detail returned by {operation.method.upper()} {operation.path}",
                "MEDIUM",
                url,
                f"The response body contains {marker!r}. Stack traces and database errors expose "
                "internal paths, schema and library versions.",
                confidence=0.8,
                evidence={"marker": marker, "status": reply.status},
            ))

        allow_origin = reply.header("access-control-allow-origin")
        allow_credentials = reply.header("access-control-allow-credentials").lower() == "true"
        if not cors_reported and allow_origin in ("*", "null") and allow_credentials:
            cors_reported = True
            findings.append(finding(
                "WILDCARD_CORS_API",
                f"API allows any origin with credentials: {allow_origin}",
                "HIGH" if allow_origin == "*" else "MEDIUM",
                url,
                f"Access-Control-Allow-Origin is {allow_origin!r} while "
                "Access-Control-Allow-Credentials is true, so any site can read this API's "
                "authenticated responses in a victim's browser.",
                confidence=0.95,
                evidence={"allow_origin": allow_origin, "allow_credentials": True},
            ))

        if not headers_reported and reply.is_json and operation.method in ("get", "head"):
            missing = [name for name in API_SECURITY_HEADERS if not reply.header(name)]
            if len(missing) == len(API_SECURITY_HEADERS):
                headers_reported = True
                findings.append(finding(
                    "MISSING_API_SECURITY_HEADERS",
                    f"API responses on {base} send no security headers",
                    "LOW",
                    url,
                    f"A JSON response carried none of {', '.join(API_SECURITY_HEADERS)}. "
                    "Browsers then sniff content types and may frame or script the origin.",
                    confidence=0.7,
                    evidence={"missing": missing},
                ))

    burst_target = next((op for op in reachable if op.method in ("get", "head")), None)
    if burst_target is not None and not burst_reported:
        url = _operation_url(api_base, burst_target)
        statuses = [request(url, burst_target.method).status for _ in range(BURST)]
        answered = [status for status in statuses if 200 <= status < 300]
        if len(answered) == BURST:
            findings.append(finding(
                "API_NO_RATE_LIMIT",
                f"No rate limiting observed on {burst_target.method.upper()} {burst_target.path}",
                "MEDIUM",
                url,
                f"{BURST} back-to-back requests all returned 2xx and none was throttled. "
                "Unlimited request rates make credential stuffing and enumeration cheap.",
                confidence=0.6,
                evidence={"requests": BURST, "statuses": statuses},
            ))

    if checked == 0:
        return [finding(
            "API_SPEC_COVERAGE_GAP",
            "Spec-driven API testing could not reach any described operation",
            "MEDIUM",
            api_base,
            f"The document lists {len(planned)} operations but none of them answered, so no "
            "authorization, CORS, error or throttling check actually ran.",
        )]

    reported = [item for item in findings if item["type"] not in ("EXPOSED_OPENAPI_SPEC", "API_SPEC_ANALYSED")]
    if not reported:
        gap = _canary_problem("spec")
        if gap:
            return [finding(
                "API_SPEC_COVERAGE_GAP",
                "Spec-driven API testing is unverified",
                "MEDIUM",
                api_base,
                f"{checked} published operations answered but the audit's canary target was not "
                f"flagged ({gap}), so a clean result cannot be told apart from a broken check.",
            )]
        findings.append(finding(
            "API_SPEC_NEGATIVE",
            f"Spec-driven API test complete: {checked} operations, no issues reported",
            "INFO",
            api_base,
            f"Replayed {checked} operations from {document_url} without credentials: no declared-secured "
            "operation answered, no wildcard-credentialed CORS, no verbose errors, security headers "
            f"present and {BURST} rapid requests were not all accepted unchecked. Clean negative.",
            confidence=0.8,
            evidence={"operations": checked, "base": api_base},
        ))
    return findings


# ── GraphQL ────────────────────────────────────────────────────────

INTROSPECTION_QUERY = {
    "query": (
        "{ __schema { queryType { name } mutationType { name } types { name kind "
        "fields { name type { name kind ofType { name kind } } } } } }"
    )
}

#: Nests deep enough that a server with a depth limit must reject the query.
DEPTH = 9


def _graphql(target: str, timeout_query: dict) -> Reply:
    return request(target, "POST", timeout_query)


def discover_graphql(target: str) -> tuple[str, str]:
    """(endpoint, problem). No endpoint found is not a problem."""
    base = _base_url(target)
    if urllib.parse.urlsplit(base).path.strip("/"):
        candidates = [base]
    else:
        candidates = [base + path for path in GRAPHQL_PATHS]
    broken = ""
    for candidate in candidates:
        reply = _graphql(candidate, {"query": "{ __typename }"})
        if reply.problem:
            broken = f"{candidate}: {reply.problem}"
            continue
        if reply.status in (401, 403):
            return candidate, ""  # exists, just gated — the auth findings need it
        if reply.status == 200 and reply.is_json:
            return candidate, ""
        if reply.status >= 500:
            broken = f"{candidate}: HTTP {reply.status}"
    return "", broken


def _types(schema: dict) -> dict[str, list[tuple[str, str]]]:
    """type name -> [(field name, field return type name)] for object types."""
    table: dict[str, list[tuple[str, str]]] = {}
    for entry in schema.get("types") or []:
        if not isinstance(entry, dict) or entry.get("kind") != "OBJECT":
            continue
        name = str(entry.get("name") or "")
        fields = []
        for entry_field in entry.get("fields") or []:
            if not isinstance(entry_field, dict) or not entry_field.get("name"):
                continue
            kind = entry_field.get("type") or {}
            return_name = str(kind.get("name") or (kind.get("ofType") or {}).get("name") or "")
            fields.append((str(entry_field["name"]), return_name))
        if name:
            table[name] = fields
    return table


def _depth_query(schema: dict) -> str | None:
    """A query nested DEPTH deep through a self-referencing type, or None when the
    schema has no cycle to nest through."""
    table = _types(schema)
    roots = [str(schema.get("queryType", {}).get("name") or "Query")]
    for root in roots:
        for start, target in table.get(root, []):
            if not target or target not in table:
                continue
            loop = next((name for name, back in table[target] if back == target), "")
            if not loop:
                continue
            selection = loop
            for _ in range(DEPTH - 1):
                selection = f"{loop} {{ {selection} }}"
            return "{ " + start + " { " + selection + " } }"
    return None


def _introspect(endpoint: str) -> tuple[dict | None, str]:
    reply = _graphql(endpoint, INTROSPECTION_QUERY)
    if reply.problem:
        return None, reply.problem
    if reply.status != 200:
        return None, f"HTTP {reply.status}"
    try:
        data = json.loads(reply.body)
    except json.JSONDecodeError:
        return None, "unreadable introspection response"
    schema = ((data or {}).get("data") or {}).get("__schema") if isinstance(data, dict) else None
    return (schema if isinstance(schema, dict) else None), ""


def analyse_graphql(target: str) -> list[dict]:
    base = _base_url(target)
    endpoint, problem = discover_graphql(target)
    if not endpoint:
        if problem:
            return [finding(
                "GRAPHQL_COVERAGE_GAP",
                "GraphQL testing could not run",
                "MEDIUM",
                base,
                f"No GraphQL endpoint answered usefully on {base} ({problem}), so introspection, depth "
                "and unauthenticated-mutation checks were not performed.",
            )]
        return [finding(
            "GRAPHQL_NOT_APPLICABLE",
            f"No GraphQL endpoint on {base}",
            "INFO",
            base,
            f"None of {', '.join(GRAPHQL_PATHS)} answered a GraphQL probe, so there is no GraphQL "
            "surface to assess. This says nothing about the REST API.",
        )]

    findings: list[dict] = []
    schema, problem = _introspect(endpoint)

    if schema:
        types = _types(schema)
        mutations = str((schema.get("mutationType") or {}).get("name") or "")
        mutation_fields = len(types.get(mutations, [])) if mutations else 0
        findings.append(finding(
            "GRAPHQL_INTROSPECTION_ENABLED",
            f"GraphQL introspection enabled on {endpoint} ({len(types)} object types)",
            "MEDIUM",
            endpoint,
            f"Introspection returned the full schema — {len(types)} object types, "
            f"{mutation_fields} uncovered mutation fields. It is the endpoint map for every other test "
            "and is usually disabled in production.",
            confidence=0.95,
            evidence={"object_types": len(types), "mutations": mutation_fields},
        ))

        depth_query = _depth_query(schema)
        if depth_query:
            reply = _graphql(endpoint, {"query": depth_query})
            if reply.status == 200 and '"data"' in reply.body and '"errors"' not in reply.body:
                findings.append(finding(
                    "GRAPHQL_DEPTH_LIMIT_MISSING",
                    f"GraphQL accepts a query nested {DEPTH} levels deep",
                    "MEDIUM",
                    endpoint,
                    f"A query nested {DEPTH} levels through a self-referencing type was accepted with "
                    "no depth error. Without a depth or cost limit a single query can exhaust the "
                    "resolver and the database.",
                    confidence=0.8,
                    evidence={"depth": DEPTH, "query": depth_query[:300]},
                ))
    elif problem:
        findings.append(finding(
            "GRAPHQL_INTROSPECTION_DISABLED",
            f"GraphQL introspection not available on {endpoint}",
            "INFO",
            endpoint,
            f"Introspection did not return a schema ({problem}). Schema disclosure through "
            "introspection is therefore not possible; depth and mutation checks still ran.",
            confidence=0.7,
        ))

    # A mutation carrying only __typename changes nothing but proves mutation
    # operations are reachable without credentials.
    mutation_reply = _graphql(endpoint, {"query": "mutation { __typename }"})
    if mutation_reply.status == 200 and '"data"' in mutation_reply.body and '"errors"' not in mutation_reply.body:
        findings.append(finding(
            "GRAPHQL_UNAUTHENTICATED_MUTATION",
            f"GraphQL mutations accepted without credentials on {endpoint}",
            "MEDIUM",
            endpoint,
            "A mutation document (`mutation { __typename }`) was accepted with no credentials. Nothing "
            "was modified by this probe, but it shows mutation operations are not gated before "
            "resolution, which is where object-level checks usually sit.",
            confidence=0.6,
            evidence={"body_excerpt": mutation_reply.body[:200]},
        ))

    # Schemas stay enumerable through error messages even with introspection off.
    suggestion_reply = _graphql(endpoint, {"query": "{ argusNoSuchField }"})
    if "did you mean" in suggestion_reply.body.lower():
        findings.append(finding(
            "GRAPHQL_FIELD_SUGGESTION_LEAK",
            f"GraphQL error messages disclose field names on {endpoint}",
            "LOW",
            endpoint,
            "An unknown field produced a 'Did you mean ...' suggestion, so the schema can be "
            "reconstructed field by field even when introspection is disabled.",
            confidence=0.85,
            evidence={"body_excerpt": suggestion_reply.body[:200]},
        ))

    if findings and any(item["type"] != "GRAPHQL_INTROSPECTION_DISABLED" for item in findings):
        return findings
    gap = _canary_problem("graphql")
    if gap:
        return [finding(
            "GRAPHQL_COVERAGE_GAP",
            "GraphQL testing is unverified",
            "MEDIUM",
            endpoint,
            f"The endpoint answered but the audit's canary target was not flagged ({gap}), so a clean "
            "result cannot be told apart from a broken check.",
        )]
    return [finding(
        "GRAPHQL_NEGATIVE",
        f"GraphQL test complete: no introspection, depth or auth issue on {endpoint}",
        "INFO",
        endpoint,
        "Introspection was refused, a depth-limit or auth error was returned where one was expected "
        "and unknown fields produced no schema hints. Clean negative.",
        confidence=0.75,
    )]


# ── canary targets ─────────────────────────────────────────────────

#: One instance of every condition the spec audit reports.
CANARY_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Argus canary", "version": "1"},
    "servers": [{"url": ""}],
    "security": [{"bearer": []}],
    "paths": {
        "/admin/users": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/health": {"get": {"security": [], "responses": {"200": {"description": "ok"}}}},
    },
}

CANARY_SCHEMA = {
    "queryType": {"name": "Query"},
    "mutationType": {"name": "Mutation"},
    "types": [
        {"name": "Query", "kind": "OBJECT", "fields": [
            {"name": "user", "type": {"name": "User", "kind": "OBJECT"}},
        ]},
        {"name": "User", "kind": "OBJECT", "fields": [
            {"name": "friend", "type": {"name": "User", "kind": "OBJECT"}},
            {"name": "name", "type": {"name": "String", "kind": "SCALAR"}},
        ]},
        {"name": "Mutation", "kind": "OBJECT", "fields": [
            {"name": "renameUser", "type": {"name": "User", "kind": "OBJECT"}},
        ]},
    ],
}

CANARY_EXPECTED = {
    "spec": {
        "API_AUTH_BYPASS",
        "WILDCARD_CORS_API",
        "VERBOSE_API_ERROR",
        "MISSING_API_SECURITY_HEADERS",
        "API_NO_RATE_LIMIT",
    },
    "graphql": {
        "GRAPHQL_INTROSPECTION_ENABLED",
        "GRAPHQL_DEPTH_LIMIT_MISSING",
        "GRAPHQL_UNAUTHENTICATED_MUTATION",
        "GRAPHQL_FIELD_SUGGESTION_LEAK",
    },
}


class _CanaryHandler(BaseHTTPRequestHandler):
    """Answers every probe the way a maximally-vulnerable API would."""

    mode = "spec"

    def log_message(self, *args) -> None:  # noqa: D102 — keep the test output quiet
        return

    def _send(self, status: int, body: str, content_type: str = "application/json") -> None:
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        path = urllib.parse.urlsplit(self.path).path
        if self.mode == "spec" and path in SPEC_PATHS:
            self._send(200, json.dumps(CANARY_SPEC))
            return
        # 200 + JSON for every operation, secured ones included, with a stack trace.
        self._send(200, json.dumps({
            "error": "Traceback (most recent call last):\n  File \"/srv/app.py\", line 3",
            "detail": "sql syntax error at or near",
        }))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            query = str((json.loads(raw or b"{}") or {}).get("query") or "")
        except (json.JSONDecodeError, AttributeError):
            query = ""
        if "__schema" in query:
            self._send(200, json.dumps({"data": {"__schema": CANARY_SCHEMA}}))
        elif query.strip().startswith("mutation"):
            self._send(200, json.dumps({"data": {"__typename": "Mutation"}}))
        elif query.count("friend") >= DEPTH - 1:
            self._send(200, json.dumps({"data": {"user": {"friend": {}}}}))
        elif "argusNoSuchField" in query:
            self._send(200, json.dumps({"errors": [
                {"message": "Cannot query field 'argusNoSuchField'. Did you mean 'user'?"}
            ]}))
        else:
            self._send(200, json.dumps({"data": {"__typename": "Query"}}))


def _canary_target(mode: str) -> tuple[str, ThreadingHTTPServer]:
    handler = type(f"Canary_{mode}", (_CanaryHandler,), {"mode": mode})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def _verify_canary(mode: str) -> str:
    """Empty when the canary target produced every finding class for this mode."""
    expected = CANARY_EXPECTED[mode]
    url, server = _canary_target(mode)
    try:
        found = {item["type"] for item in (
            analyse_spec(url) if mode == "spec" else analyse_graphql(url + "/graphql")
        )}
    finally:
        server.shutdown()
        server.server_close()
    missed = sorted(expected - found)
    if missed:
        return f"the canary target was not flagged for {', '.join(missed)}"
    return ""


def _canary_problem(mode: str) -> str:
    if mode in _CANARY_CACHE:
        return _CANARY_CACHE[mode]
    verdict = _verify_canary(mode)
    if not verdict:
        _CANARY_CACHE[mode] = verdict
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Spec-driven API testing.")
    parser.add_argument("--mode", choices=("spec", "graphql"), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--spec-url", default="", help="Explicit OpenAPI/Swagger document URL")
    args = parser.parse_args()

    if args.mode == "spec":
        findings = analyse_spec(args.target, args.spec_url)
    else:
        findings = analyse_graphql(args.target)

    print(json.dumps(findings, indent=2))
    print(f"# api_spec_scan ({args.mode}): {len(findings)} finding(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

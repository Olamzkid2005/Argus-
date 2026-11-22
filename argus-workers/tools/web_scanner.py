"""
Comprehensive Web Application Scanner

Integrates advanced web scanning capabilities:
- Security headers audit
- CSP analysis
- Cookie security
- CORS analysis
- XSS testing
- LFI/Path traversal
- SSTI detection
- Command injection
- XXE testing
- Host header injection
- JS secret scanning
- Authentication testing
- Mass assignment
- Open redirect detection
- Debug endpoint detection
- Sensitive file detection
"""

import contextlib
import hashlib
import json
import logging
import os
import queue
import re
import socket
import threading
import time
import uuid
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

# Allowed URL schemes for scan targets — blocks dangerous protocols like
# file:// and gopher:// that could be used for SSRF (H-v3-24)
_ALLOWED_SCAN_SCHEMES = frozenset({"http", "https"})

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, RequestException, Timeout

from config.constants import (
    LLM_MAX_GENERATED_PAYLOADS,
    MAX_PAGES_TO_CRAWL,
    MAX_PARAMETERS_TO_FUZZ,
    RATE_LIMIT_DELAY_MS,
    SSL_TIMEOUT,
    WEB_SCANNER_CHECK_TIMEOUT,
)
from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult
from tools.scope_validator import (  # M-25: scope validation
    ScopeValidator,
    authorize_target,
)
from tools.web_scanner_checks._helpers import test_jwt_alg_none
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

#: Findings at or above these severities must carry the HTTP response they were
#: derived from, so a human can check the claim instead of trusting the label.
#: Attach the observed response to any finding that was derived from one.
#: It used to be limited to MEDIUM and above, which meant a LOW finding that
#: came from a real response could not be checked by the reader.
RESPONSE_EVIDENCE_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})

#: How the property a prototype-pollution payload sets would appear if the
#: server actually merged the input into an object. Used as a differential
#: marker against the unmodified response; the bare word "true" is not one.
_PROTOTYPE_POLLUTION_MARKERS = (
    '"isadmin":true',
    "'isadmin':true",
    '"isadmin": true',
    "'isadmin': true",
    "isadmin=true",
)


def _validate_redirect_chain(
    url: str, target_url: str, engagement_id: str | None = None
) -> bool:
    """Validate one hop of a redirect chain against scope and SSRF policy.

    Delegates the whole decision to ``authorize_target``: the hop is parsed (a
    malformed ``Location`` is refused rather than matched), authorized against
    the engagement's scope, and checked against the internal/metadata policy.

    Without an engagement there is no authoritative scope, so the scan target's
    own origin is the only one a hop may reach — a hop to another scheme, port
    or host is refused, including one that only shares a hostname suffix.

    Returns True when the hop may be followed.
    """
    return authorize_target(
        url, engagement_id, allow_origin=target_url
    ).authorized


def _is_in_scope(
    url: str, target_url: str | None = None, engagement_id: str | None = None
) -> bool:
    """Whether a discovered URL may be used (crawl links, follow-ups).

    Same single entry point as the redirect guard: parsed, scope-authorized and
    SSRF-checked, with the scan target's origin as the fallback when no
    engagement scope exists. H-v3-12.
    """
    return authorize_target(
        url, engagement_id, allow_origin=target_url
    ).authorized


class WebScanner(AbstractTool):
    """
    Comprehensive web application vulnerability scanner.
    Performs security configuration checks and active vulnerability testing.
    """

    tool_name = "web_scanner"

    # Security headers to check, each with the severity its absence justifies.
    #
    # One aggregate MEDIUM for every absent header is a bad score: a site with
    # HSTS and frame options missing is not in the same state as one that has
    # nothing, and the report could not say which header was which.
    #
    # ``X-XSS-Protection`` is deliberately absent. The header is obsolete, and
    # the value browsers recommend (``0``) would otherwise read as "missing".
    # ``Content-Security-Policy`` is scored by ``check_csp``, which knows the
    # difference between a missing policy (MEDIUM) and a weak one.
    SECURITY_HEADERS = {
        "Strict-Transport-Security": "LOW",
        "X-Frame-Options": "LOW",
        "X-Content-Type-Options": "LOW",
        "Referrer-Policy": "LOW",
        "Permissions-Policy": "LOW",
    }

    # One finding type per header, so two absent headers stay two findings
    # instead of overwriting each other (the store treats title+tool+url as
    # the identity of a finding).
    HEADER_FINDING_TYPES = {
        "Strict-Transport-Security": "MISSING_HSTS",
        "X-Frame-Options": "MISSING_X_FRAME_OPTIONS",
        "X-Content-Type-Options": "MISSING_X_CONTENT_TYPE_OPTIONS",
        "Referrer-Policy": "MISSING_REFERRER_POLICY",
        "Permissions-Policy": "MISSING_PERMISSIONS_POLICY",
    }

    # Sensitive file patterns
    SENSITIVE_FILES = [
        ".env",
        ".git/config",
        ".git/HEAD",
        ".git/COMMIT_EDITMSG",
        "config.php",
        "wp-config.php",
        ".DS_Store",
        "credentials.json",
        "secrets.yml",
        ".aws/credentials",
        "id_rsa",
        "docker-compose.yml",
        ".htpasswd",
        "database.yml",
        "settings.py",
        ".npmrc",
        ".pypirc",
        # robots.txt, sitemap.xml and /.well-known/security.txt are published on
        # purpose: they are meant to be fetched by anyone. Listing them here made
        # every ordinary site that has them report three HIGH "exposed sensitive
        # file" findings (observed on www.hisdayspringfamily.org). Keep this list
        # in sync with tools/web_scanner_checks/detection_check.py — a test
        # asserts the two copies are identical.
        "swagger.json",
        "openapi.json",
        "/actuator",
        "/actuator/env",
        "/actuator/health",
        "/debug",
        "/_debug",
        "/console",
        "/__debug__",
        "/phpinfo.php",
        "/info.php",
        "/_profiler",
        "/server-status",
        "/wp-admin/",
        "/admin/",
        "/phpmyadmin/",
        "/api/v1",
        "/api/v2",
        "/graphql",
    ]

    # JS secret patterns
    JS_SECRET_PATTERNS = [
        (
            r'(?:api[_-]?key|apikey|api[_-]?token)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']',
            "API_KEY",
        ),
        (
            r'(?:token|access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*["\']([a-zA-Z0-9_\-\.]{20,})["\']',
            "AUTH_TOKEN",
        ),
        (
            r'(?:secret|secret[_-]?key|client[_-]?secret)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']',
            "SECRET_KEY",
        ),
        (
            r'(?:password|passwd|pwd)\s*[:=]\s*["\']([^"\']{4,})["\']',
            "HARDCODED_PASSWORD",
        ),
        (r"(AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}", "AWS_ACCESS_KEY"),
        (r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "JWT_TOKEN"),
        (
            r'(?:private[_-]?key|encryption[_-]?key)\s*[:=]\s*["\']([^"\']{16,})["\']',
            "ENCRYPTION_KEY",
        ),
        (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "PRIVATE_KEY"),
        (
            r'(?:database[_-]?url|db[_-]?url|connection[_-]?string)\s*[:=]\s*["\']([^"\']+)["\']',
            "DATABASE_URL",
        ),
        (
            r'(?:webhook[_-]?url|webhook[_-]?secret)\s*[:=]\s*["\']([^"\']+)["\']',
            "WEBHOOK_SECRET",
        ),
    ]

    # XSS payloads
    XSS_PAYLOADS = [
        "<script>alert(1)</script>",
        '"><script>alert(1)</script>',
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)>",
        "{{7*7}}",
        "${7*7}",
        "'\"><img src=x onerror=alert(1)>",
        "<body onload=alert(1)>",
    ]

    # SSTI payloads
    SSTI_PAYLOADS = [
        "{{7*7}}",
        "${7*7}",
        "<%= 7*7 %>",
        "#{7*7}",
        "*{7*7}",
    ]

    # LFI payloads
    LFI_PAYLOADS = [
        "../../../../etc/passwd",
        "....//....//etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "..%252fetc%252fpasswd",
        "php://filter/convert.base64-encode/resource=/etc/passwd",
    ]

    # Host header injection targets
    HOST_INJECTION = [
        "evil.com",
        "attacker.com",
        "127.0.0.1",
        "localhost",
    ]

    # Open redirect parameters
    REDIRECT_PARAMS = [
        "redirect",
        "url",
        "next",
        "dest",
        "redirect_url",
        "return",
        "continue",
        "to",
        "ref",
        "dest_url",
        "target",
        "goto",
    ]

    # Mass assignment payloads
    MASS_ASSIGN_PAYLOADS = [
        '{"role":"admin"}',
        '{"is_admin":true}',
        '{"admin":1}',
        '{"privilege":"superuser"}',
        '{"verified":true}',
    ]

    # Default credentials
    DEFAULT_CREDS = [
        ("admin", "admin"),
        ("admin", "password"),
        ("admin", "123456"),
        ("admin", "admin123"),
        ("root", "root"),
        ("test", "test"),
        ("guest", "guest"),
        ("admin", "letmein"),
    ]
    ENABLE_CREDENTIAL_TESTING = False  # Disabled by default for safety

    # GraphQL endpoints to check
    GRAPHQL_ENDPOINTS = [
        "/graphql",
        "/api/graphql",
        "/v1/graphql",
        "/query",
    ]

    # OpenAPI/Swagger paths to check
    OPENAPI_PATHS = [
        "/.well-known/openapi",
        "/api-docs",
        "/swagger.json",
        "/openapi.json",
        "/api/swagger.json",
        "/api/openapi.json",
    ]

    # Prototype pollution payloads
    PROTOTYPE_POLLUTION_PAYLOADS = [
        "?__proto__[isAdmin]=true",
        "?constructor[prototype][isAdmin]=true",
    ]

    # Cache poisoning headers
    CACHE_POISONING_HEADERS = {
        "X-Forwarded-For": "127.0.0.1",
        "X-Original-Forwarded-For": "127.0.0.1",
    }

    # Financial / transaction paths for business logic checks.
    #
    # The money-moving surface of a fintech target is not one endpoint: a
    # transfer, a card top-up, a bill payment and a merchant charge are all
    # amount-accepting endpoints with the same validation questions. Sending
    # the amount probes to only /api/transfer found nothing on targets whose
    # payments live under /api/cards/fund or /api/billers/pay.
    TRANSFER_PATHS = [
        "/api/transfer",
        "/api/transfers",
        "/api/transactions",
        "/api/payment",
        "/api/payments",
        "/api/v1/transfers",
        "/api/v1/payments",
        "/api/send",
        "/api/withdraw",
        "/api/wallet/transfer",
        # Virtual cards
        "/api/cards/fund",
        "/api/card/fund",
        "/api/v1/cards/fund",
        "/api/cards/topup",
        # Bill payments
        "/api/bills/pay",
        "/api/bill-payment",
        "/api/bill-payments",
        "/api/billers/pay",
        "/api/utilities/pay",
        # Merchant / payment API
        "/api/merchant/pay",
        "/api/merchant/payment",
        "/api/merchant/charge",
        "/api/charge",
        "/api/v1/payments/charge",
        # Money-moving handlers are often mounted at the root. A target whose
        # transfer lives at POST /transfer answered every /api/* amount probe
        # with 404, so the business-logic checks never reached a handler.
        "/transfer",
        "/pay",
        "/payments",
        "/withdraw",
    ]

    # Authenticated banking resources. A fintech surface exposes cards, bills
    # and a merchant API alongside ordinary transfers; without these paths the
    # card/bill/merchant classes were only tested for amount handling.
    CARD_LIST_PATHS = [
        "/api/virtual-cards",
        "/api/cards",
        "/api/v1/cards",
        "/cards",
    ]
    CARD_CREATE_PATHS = [
        "/api/virtual-cards/create",
        "/api/cards/create",
        "/api/v1/cards/create",
        "/api/cards",
    ]
    CARD_LIMIT_TEMPLATES = [
        "/api/virtual-cards/{id}/update-limit",
        "/api/cards/{id}/update-limit",
        "/api/cards/{id}/limit",
    ]
    CARD_ACTIVITY_TEMPLATES = [
        "/api/virtual-cards/{id}/transactions",
        "/api/cards/{id}/transactions",
    ]
    MERCHANT_REGISTER_PATHS = [
        "/api/v1/merchants/register",
        "/api/merchants/register",
        "/api/merchant/register",
    ]
    MERCHANT_LOGIN_PATHS = [
        "/api/v1/merchants/login",
        "/api/merchants/login",
        "/api/merchant/login",
    ]
    MERCHANT_PAYMENT_TEMPLATES = [
        "/api/v1/payments/merchant_id/{id}",
        "/api/merchants/{id}/payments",
    ]
    MERCHANT_CHARGE_PATHS = [
        "/api/v1/payments/charge",
        "/api/merchant/charge",
        "/api/payments/charge",
    ]
    LOGOUT_PATHS = [
        "/logout",
        "/api/logout",
        "/api/auth/logout",
        "/auth/logout",
        "/api/v1/logout",
    ]

    # Fields a merchant registration/login response must never echo back.
    MERCHANT_KEY_FIELDS = (
        "api_key",
        "apikey",
        "api_secret",
        "secret_key",
        "password",
    )

    # File upload endpoints (incl. URL-based profile-image import, the SSRF
    # surface of many profile settings pages)
    UPLOAD_PATHS = [
        "/api/upload",
        "/api/profile/image",
        "/api/profile/avatar",
        "/api/avatar",
        "/api/documents",
        "/api/v1/upload",
        "/upload",
    ]

    # Rate limiting sensitive paths
    RATE_LIMIT_PATHS = [
        "/login",
        "/transfer",
        "/api/v1/payments/charge",
        "/api/login",
        "/api/auth/login",
        "/api/reset-password",
        "/api/forgot-password",
        "/api/transfer",
        "/api/payment",
        "/api/cards/fund",
        "/api/bills/pay",
        "/api/merchant/pay",
    ]

    # Password reset endpoints
    RESET_PATHS = [
        "/forgot-password",
        "/api/v1/forgot-password",
        "/api/forgot-password",
        "/api/reset-password",
        "/api/auth/reset",
        "/api/auth/forgot-password",
        "/api/password/reset",
        "/forgot-password",
    ]

    # Race condition test endpoints
    RACE_PATHS = [
        "/transfer",
        "/api/v1/payments/charge",
        "/api/transfer",
        "/api/payment",
        "/api/payments",
        "/api/card/fund",
        "/api/cards/fund",
        "/api/bills/pay",
        "/api/merchant/pay",
        "/api/withdraw",
    ]

    # Object endpoints whose response is expected to belong to the caller.
    # An authenticated request that returns another owner's record is BOLA.
    BOLA_RESOURCE_TEMPLATES = [
        "/api/data/{id}",
        # Banking objects are also mounted at the root: transaction history and
        # balance lookups take the account number in the path.
        "/transactions/{id}",
        "/check_balance/{id}",
        "/api/virtual-cards/{id}",
        "/api/v1/payments/{id}",
        "/api/bill-payments/{id}",
        "/api/accounts/{id}",
        "/api/account/{id}",
        "/api/orders/{id}",
        "/api/transactions/{id}",
        "/api/cards/{id}",
        "/api/bills/{id}",
        "/api/invoices/{id}",
        "/api/documents/{id}",
        "/api/v1/accounts/{id}",
        "/api/v1/transactions/{id}",
    ]

    # Identity endpoints used to learn who "we" are before judging ownership.
    BOLA_IDENTITY_PATHS = [
        "/api/me",
        "/api/v1/merchants/me",
        "/api/transactions",
        "/api/v1/me",
        "/me",
        "/api/user",
        "/api/users/me",
        "/api/profile",
        "/api/v1/profile",
        "/api/auth/me",
    ]

    # Response keys that name the owner of an object.
    BOLA_OWNER_FIELDS = {
        "user_id",
        "userId",
        "owner_id",
        "ownerId",
        "account_id",
        "customer_id",
        "created_by",
        "createdBy",
        "owner",
        "user",
        "username",
        "email",
        "account_number",
        "accountNumber",
    }

    # Sensitive response fields (BOPLA — should not appear in regular user responses)
    SENSITIVE_RESPONSE_FIELDS = {
        "password",
        "password_hash",
        "hashed_password",
        "pwd",
        "card_number",
        "pan",
        "cvv",
        "cvv2",
        "cvc",
        "secret",
        "api_key",
        "api_secret",
        "secret_key",
        "card_details",
        "pan_number",
        "card_holder",
        "authorization_code",
        "access_token",
        "refresh_token",
        "ssn",
        "social_security",
        "pin",
        "credit_score",
        "is_admin",
        "admin",
        "role",
        "privilege",
        "is_superuser",
    }

    # requests.Session is not thread-safe. We keep a pool of sessions
    # (sized above the main worker count) so concurrent checks get
    # exclusive session access while still sharing auth state.
    # Main ThreadPoolExecutor uses 6 workers; check_race_conditions can
    # spawn 5 additional concurrent requests, so 12 gives headroom.
    SESSION_POOL_SIZE = 12

    def __init__(
        self,
        timeout: int = SSL_TIMEOUT,
        rate_limit: float = RATE_LIMIT_DELAY_MS / 1000.0,
        llm_payload_generator=None,
        session: requests.Session | None = None,
        tech_stack: list[str] | None = None,
        verify: bool = True,
        engagement_id: str = "",
        user_agent: str = "",
        emit_finding_callback=None,
        auth_manager=None,
        pool_size: int | None = None,
    ):
        """
        Initialize web scanner.

        Args:
            timeout: Request timeout in seconds
            rate_limit: Seconds between requests
            llm_payload_generator: Optional LLMPayloadGenerator for context-aware payloads
            session: Optional pre-authenticated requests.Session
            tech_stack: Detected technology stack from recon (e.g. ["WordPress", "PHP", "jQuery"])
            verify: Verify SSL certificates
            engagement_id: Engagement ID for log/trace correlation
            user_agent: Custom User-Agent string (falls back to WEB_SCANNER_USER_AGENT env or default)
            emit_finding_callback: Optional callable(engagement_id, finding_dict, tool_name)
                                   called inline each time a finding is discovered for real-time streaming.
                                   If provided, findings are emitted as they're found rather than
                                   batched until scan() completes.
            auth_manager: Optional AuthManager instance for in-flight session re-authentication.
            pool_size: Optional override for the number of pooled sessions.
                     Defaults to SESSION_POOL_SIZE. Lower values reduce memory;
                     higher values reduce contention for I/O-heavy scans.
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.llm_payload_generator = llm_payload_generator
        self.tech_stack = tech_stack or []
        self.verify = verify
        self.engagement_id = engagement_id
        # Template session carries shared headers / cookies / auth config.
        # The actual request pool is created lazily so it can inherit any
        # cookies set by the single-threaded pre-flight request.
        self.session = session or requests.Session()
        # Shared cookie jar keeps cookie state coherent across pooled sessions.
        self._shared_cookie_jar = self.session.cookies
        self._session_generation = 0  # Bumped on re-auth to refresh pooled sessions
        self._session_pool: queue.Queue[requests.Session] | None = None
        self._pool_size = pool_size if pool_size is not None else self.SESSION_POOL_SIZE
        self._pool_lock = threading.Lock()  # Serializes lazy pool creation and close
        self._checked_out = 0  # Approximate count for diagnostics
        self.emit_finding_callback = emit_finding_callback
        _default_ua = "Argus-Scanner/1.0 (security-automation)"
        _ua = user_agent or os.environ.get("WEB_SCANNER_USER_AGENT", _default_ua)
        self.session.headers.setdefault("User-Agent", _ua)
        self.session.headers.setdefault(
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        )
        self.session.headers.setdefault("Accept-Language", "en-US,en;q=0.5")
        self.findings: list[dict] = []
        self.discovered_parameters = None  # Initialized before parameter_discovery()
        self._last_request_time = 0.0  # For token-bucket rate limiting
        self._rate_lock = threading.Lock()  # Thread safety for rate limiting
        self.slog = ScanLogger("web_scanner", engagement_id=self.engagement_id)
        self._auth_manager = auth_manager
        self._reauth_request_counter = 0
        self._reauth_interval = 10
        self._reauth_lock = threading.Lock()
        self._builder: FindingBuilder | None = None
        # Per-thread record of the last response this thread received. Checks
        # run in a thread pool, so a shared attribute would attribute one
        # check's response to another check's finding.
        self._request_state = threading.local()
        # Engagement credentials handed to the scanner through ToolContext
        # (the executor encodes them into --extra). Without them every check
        # ran logged out: 401 responses made auth/BOLA/transaction findings
        # impossible no matter how many checks were implemented.
        self._credentials: dict[str, str] = {}
        self._authenticated = False
        # Authenticated surface harvested before the checks run: links served
        # to a logged-in user plus paths advertised by API documentation.
        self.discovered_urls: list[str] = []
        # Cards created by check_card_security, reused by the activity and
        # transaction-verification checks so they need not create more.
        self._probe_cards: list[dict] = []

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        AbstractTool entry point.

        Sets up a ``FindingBuilder`` from the context, runs all scan checks
        (SSRF check, SSL test, ThreadPoolExecutor with 38+ checks), and
        returns a ``UnifiedToolResult`` populated with findings.

        Args:
            ctx: Tool execution context with target, engagement_id, etc.

        Returns:
            ``UnifiedToolResult`` with findings, status = SUCCESS.
        """
        engagement_id = ctx.engagement_id or self.engagement_id
        self._builder = FindingBuilder(
            source_tool="web_scanner",
            engagement_id=engagement_id,
            emit_finding=ctx.emit_finding or self.emit_finding_callback,
        )

        # Apply ToolContext settings to instance
        self.timeout = ctx.timeout
        self.rate_limit = ctx.rate_limit
        self.tech_stack = ctx.tech_stack or self.tech_stack
        self.engagement_id = engagement_id
        self._credentials = self._extract_credentials(ctx)

        # Run the actual scan logic
        target_url = ctx.target
        try:
            self._run_scan_impl(target_url)
        finally:
            # Close pooled sessions to release connections and sockets.
            # The externally-provided template session is left to the caller.
            self.close()

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=target_url,
        )
        result.findings = self._builder.findings
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def scan(self, target_url: str) -> list[dict]:
        """
        Run comprehensive scan against target.

        Backward-compatible shim that delegates to ``execute()``. Existing
        callers that call ``scan()`` directly still work unchanged.

        Args:
            target_url: Target URL to scan

        Returns:
            List of vulnerability findings

        Raises:
            ValueError: If target_url uses a disallowed scheme (SSRF prevention)
        """
        ctx = ToolContext(target=target_url)
        result = self.execute(ctx)
        return result.findings

    def _ensure_pool(self) -> queue.Queue[requests.Session]:
        """Create the thread-safe session pool from the template session.

        The pool is created lazily so the pre-flight request has a chance to
        populate the template session's cookie jar first. Sessions are copied
        from the template so all workers start with the same headers, cookies,
        auth, proxies, hooks, mounts, and SSL verification settings.
        """
        with self._pool_lock:
            if self._session_pool is not None:
                return self._session_pool

            pool: queue.Queue[requests.Session] = queue.Queue()
            template = self.session
            for i in range(self._pool_size):
                s = requests.Session()
                s._argus_session_id = i  # type: ignore[attr-defined]
                s._argus_generation = self._session_generation  # type: ignore[attr-defined]
                s.headers.update(template.headers)
                # All pooled sessions share the same cookie jar so cookie state
                # stays coherent across concurrent checks.
                s.cookies = self._shared_cookie_jar
                s.verify = template.verify
                s.trust_env = template.trust_env
                s.auth = template.auth
                s.proxies.update(template.proxies)
                s.params.update(template.params)
                # Hooks are a dict of event -> list[callable]. Shallow copy of
                # the dict is enough; the callables themselves can be shared.
                s.hooks.clear()
                for event, hooks in template.hooks.items():
                    s.hooks[event] = list(hooks)
                # Mount adapters so custom transport/auth adapters are preserved.
                # HTTPAdapters are cloned to avoid mutable state races; custom
                # adapters are shared (with a warning) because we cannot safely
                # clone arbitrary subclasses.
                for prefix, adapter in template.adapters.items():
                    if isinstance(adapter, HTTPAdapter):
                        cloned = HTTPAdapter(
                            pool_connections=getattr(adapter, "_pool_connections", 10),
                            pool_maxsize=getattr(adapter, "_pool_maxsize", 10),
                            max_retries=getattr(adapter, "max_retries", 0),
                            pool_block=getattr(adapter, "_pool_block", False),
                        )
                        s.mount(prefix, cloned)
                    else:
                        logger.warning(
                            "Sharing non-HTTPAdapter %r mounted at %s across pooled sessions; "
                            "ensure it is thread-safe",
                            adapter,
                            prefix,
                        )
                        s.mount(prefix, adapter)
                pool.put(s)
            self._session_pool = pool
            logger.debug(
                "Created WebScanner session pool with %s sessions", self._pool_size
            )
            return pool

    def close(self) -> None:
        """Drain and close all sessions in the pool.

        Safe to call multiple times. The template session supplied to
        ``__init__`` is intentionally not closed here; the caller owns it.
        """
        with self._pool_lock:
            pool = self._session_pool
            self._session_pool = None
            if pool is None:
                return
            closed = 0
            while not pool.empty():
                try:
                    session = pool.get_nowait()
                except queue.Empty:
                    break
                try:
                    session.close()
                    closed += 1
                except Exception:
                    logger.debug("Error closing pooled session", exc_info=True)
            logger.debug("Closed %s/%s pooled sessions", closed, self._pool_size)

    def _internal_target_authorized(self, target_url: str) -> bool:
        """Whether an internal target is explicitly authorized for this scan.

        Opt-in (``ARGUS_ALLOW_INTERNAL_TARGETS``) is not authorization on its
        own: the target must also be in the engagement's (or published run)
        scope. With no engagement identity there is nothing to authorize it, so
        the internal guard keeps refusing it (fail closed).
        """
        return bool(
            self.engagement_id
            and authorize_target(target_url, self.engagement_id).authorized
        )

    @staticmethod
    def _extract_credentials(ctx: ToolContext) -> dict[str, str]:
        """Credentials the engagement supplied for this scan.

        Shared with the AI scanner through ``auth_manager`` so both tools
        accept the same executor shape (``_<key>`` attributes from
        ``--extra``) and the direct ``_credentials`` mapping.
        """
        from tools.auth_manager import extract_engagement_credentials

        return extract_engagement_credentials(ctx)

    @staticmethod
    def _session_has_auth(
        session: requests.Session,
        *,
        api_key: str = "",
        cookie: str = "",
        token: str = "",
    ) -> bool:
        """Whether a session actually carries credential material.

        Delegates to ``AuthManager.session_has_auth`` so the "what counts as
        authenticated material" rule lives in one place; this helper only
        decides which engagement credential values to hand to it.
        """
        from tools.auth_manager import AuthManager

        return AuthManager.session_has_auth(
            session,
            api_key=api_key,
            cookie=cookie,
            token=token,
        )

    def _json_login(
        self, session: requests.Session, username: str, password: str
    ) -> requests.Session | None:
        """Log in against a JSON API and attach the returned token."""
        from tools.auth_manager import json_api_login

        return json_api_login(
            session,
            self.target_url,
            username,
            password,
            timeout=self.timeout,
            verify=self.verify,
        )

    def _authenticate_with_credentials(self) -> bool:
        """Log in with the engagement's credentials, if any were supplied.

        Returns True when the scan now carries an authenticated session. A
        target with no credentials (or a login that fails) keeps scanning
        anonymously: that is a coverage limitation to be reported, not a
        reason to abort the whole scan.
        """
        creds = self._credentials
        if not creds:
            return False

        username = creds.get("username") or creds.get("email", "")
        password = creds.get("password", "")
        cookie = creds.get("cookie", "")
        token = creds.get("token", "")
        api_key = creds.get("api_key", "")
        if not (cookie or token or api_key or (username and password)):
            return False

        try:
            from tools.auth_manager import AuthConfig, AuthManager

            config = AuthConfig(
                username=username,
                password=password,
                cookie=cookie,
                token=token,
                api_key=api_key,
                login_url=creds.get("login_url", ""),
            )
            manager = AuthManager(config)
            session = manager.authenticate(self.target_url)
        except Exception as exc:  # login failure must not fail the scan
            logger.info(
                "Web scanner: authenticated scan unavailable for %s (%s); "
                "continuing unauthenticated",
                self.target_url,
                exc,
            )
            return False

        # AuthManager can hand back a session that carries no credentials at
        # all (its form-encoded login is rejected by JSON-only APIs). Reporting
        # that as "authenticated" made every authenticated check answer 401 and
        # find nothing. Verify the session, then fall back to a JSON login.
        if (username and password) and not self._session_has_auth(session):
            session = self._json_login(session, username, password) or session
        if not self._session_has_auth(session, api_key=api_key, cookie=cookie, token=token):
            logger.info(
                "Web scanner: engagement credentials did not produce an "
                "authenticated session for %s; continuing unauthenticated",
                self.target_url,
            )
            return False

        self.session = session
        self._shared_cookie_jar = session.cookies
        self.session.headers.setdefault("User-Agent", "Argus-Scanner/1.0 (security-automation)")
        # Keep re-authenticating through the in-flight hook in _safe_request.
        self._auth_manager = manager
        self._authenticated = True
        self._add_finding(
            finding_type="AUTH_DETECTED",
            severity="INFO",
            endpoint=self.target_url,
            evidence={
                "message": "Engagement credentials authenticated; authenticated surface was scanned",
                "auth_method": "cookie"
                if cookie
                else "token"
                if token
                else "api_key"
                if api_key
                else "form_login",
                "cookies_captured": len(session.cookies),
            },
            confidence=0.9,
        )
        return True

    def _harvest_authenticated_surface(self) -> None:
        """Collect URLs that are only visible to a logged-in user.

        BOLA/IDOR checks need object URLs. Most targets expose them through
        the authenticated landing page or an API description (``/api/docs``,
        OpenAPI), so both are harvested here. Everything goes through
        ``_safe_request`` so scope and SSRF policy still apply to every hop.
        """
        candidates: list[str] = []
        sources = [
            self.target_url,
            urljoin(self.target_url, "/api/docs"),
            urljoin(self.target_url, "/api/docs/"),
            urljoin(self.target_url, "/api-docs"),
            urljoin(self.target_url, "/openapi.json"),
            urljoin(self.target_url, "/static/openapi.json"),
            urljoin(self.target_url, "/swagger.json"),
            urljoin(self.target_url, "/api"),
        ]

        path_re = re.compile(r"(/api/[A-Za-z0-9_\-./{}]+)")
        for source in sources:
            resp = self._safe_request("GET", source)
            if not resp or resp.status_code >= 400:
                continue
            text = resp.text or ""
            for link in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
                absolute = urljoin(source, link)
                if _is_in_scope(absolute, self.target_url, self.engagement_id):
                    candidates.append(absolute)
            for path in path_re.findall(text):
                absolute = urljoin(self.target_url, path.lstrip("/"))
                if _is_in_scope(absolute, self.target_url, self.engagement_id):
                    candidates.append(absolute)

        seen: set[str] = set()
        for url in candidates:
            if url not in seen:
                seen.add(url)
                self.discovered_urls.append(url)

    def _run_scan_impl(self, target_url: str) -> None:
        """
        Core scan logic — SSRF prevention, scope validation, SSL test, then
        all 38+ checks executed in a ThreadPoolExecutor.

        Mutates ``self._builder`` (via ``_add_finding`` calls from each check)
        and ``self.findings`` (synced from builder at the end).

        Raises:
            ValueError: If target_url uses a disallowed scheme (SSRF prevention)
        """
        # SSRF prevention: reject dangerous URL schemes before any requests (H-v3-24)
        parsed = urlparse(target_url)
        if parsed.scheme not in _ALLOWED_SCAN_SCHEMES:
            raise ValueError(
                f"Disallowed URL scheme '{parsed.scheme}' in target {target_url}. "
                f"Only http:// and https:// targets are permitted (H-v3-24 SSRF prevention)."
            )

        # M-25: Scope validation + SSRF — reject targets outside authorized scope
        # or internal/SSRF targets before sending any potentially destructive
        # payloads (mass assignment, credential testing, host header injection).
        hostname = parsed.hostname or target_url.split("/")[0].split(":")[0]
        # Internal targets stay blocked unless the operator opted in via
        # ARGUS_ALLOW_INTERNAL_TARGETS. When they have, the target has already
        # been authorized upstream — the scan pipeline runs validate_target_scope
        # before dispatching any tool — so this tool-level guard defers instead of
        # re-denying it. Cloud metadata / link-local remain blocked regardless.
        _internal_opted_in = ScopeValidator.internal_targets_opt_in()
        if hostname and ScopeValidator.is_blocked_internal_target(
            hostname, authorized=self._internal_target_authorized(target_url)
        ):
            # Refusing is not the same as scanning and finding nothing. Raising
            # turns the refusal into a visible failed tool call; returning an
            # empty finding list used to surface as "succeeded, no findings",
            # which reads as a clean target.
            raise RuntimeError(
                f"Target {target_url} is an internal/SSRF target — scan not run. "
                "Set ARGUS_ALLOW_INTERNAL_TARGETS=1 and authorize the target in "
                "the engagement scope to scan internal targets."
            )
        if (
            self.engagement_id
            and not _internal_opted_in
            and not authorize_target(target_url, self.engagement_id).authorized
        ):
            raise RuntimeError(
                f"Target {target_url} is outside authorized scope for engagement "
                f"{self.engagement_id} — scan not run (M-25)"
            )

        self.findings = []
        self.target_url = target_url.rstrip("/")

        self.slog.phase_header("WEB SCAN", target=self.target_url)
        logger.info("Starting comprehensive web scan: %s", self.target_url)

        # Log in before the pre-flight request so every subsequent request —
        # including the pooled sessions created below — inherits the session.
        self._authenticate_with_credentials()

        # Pre-flight: test SSL/TLS connectivity. If a cert error occurs,
        # report it as a finding and retry with verification disabled so
        # the rest of the scan can proceed against self-signed/internal certs.
        #
        # Redirects are followed manually with scope validation to prevent SSRF
        # via open redirect chains (H-v3-24).
        try:
            resp = self.session.get(
                self.target_url, timeout=self.timeout, allow_redirects=False
            )
            resp = self._follow_redirects_safe(resp)
            self._base_response = resp
        except requests.exceptions.SSLError as e:
            logger.warning(
                "SSL certificate error for %s — reporting as finding and retrying without verification: %s",
                self.target_url,
                e,
            )
            self._report_ssl_finding(str(e))
            # Retry with a SEPARATE unverified session so the shared session
            # maintains SSL verification for all subsequent requests (C-09)
            unverified_session = requests.Session()
            unverified_session.verify = False
            try:
                resp = unverified_session.get(
                    self.target_url, timeout=self.timeout, allow_redirects=False
                )
                resp = self._follow_redirects_safe(resp, session=unverified_session)
                self._base_response = resp
            except Exception as retry_err:
                logger.error(
                    "Web scanner: cannot connect to %s even without SSL verification: %s",
                    self.target_url,
                    retry_err,
                )
                # Sync builder findings before returning (SSL finding may have been added)
                if self._builder:
                    self.findings = self._builder.findings
                return
            finally:
                unverified_session.close()
        except Exception as e:
            logger.error("Web scanner: failed to connect to %s: %s", self.target_url, e)
            return

        # Build the session pool now so it inherits any cookies set by the
        # pre-flight request. Each concurrent check will check out a session
        # exclusively, avoiding requests.Session thread-safety races (C-06).
        self._ensure_pool()

        # Harvest the logged-in surface before the checks that consume it.
        if self._authenticated:
            self._harvest_authenticated_surface()

        # Run parameter discovery sequentially before the concurrent phase.
        # parameter_fuzzing() depends on self.discovered_parameters being
        # populated; running both in the ThreadPoolExecutor created a race
        # where fuzzing could see an empty dict and skip all tests (H-14).
        self.parameter_discovery()

        # Card creation is also sequential: the merchant check charges the card
        # this creates, and running both in the pool made the card list a race.
        self.check_card_security()

        from concurrent.futures import ThreadPoolExecutor, as_completed

        checks = [
            self.check_security_headers,
            self.check_csp,
            self.check_cookies,
            self.check_cors,
            self.parameter_fuzzing,
            self.check_sensitive_files,
            self.check_js_secrets,
            self.check_open_redirects,
            self.check_host_header_injection,
            self.check_verb_tampering,
            self.check_debug_endpoints,
            self.check_auth_endpoints,
            self.check_mass_assignment,
            self.check_csrf,
            self.check_xss,
            self.check_ssti,
            self.check_lfi,
            self.check_ssrf,
            self.check_xxe,
            self.check_graphql_introspection,
            self.check_financial_logic,
            self.check_file_upload,
            self.check_token_storage,
            self.check_session_expiration,
            self.check_password_reset_strength,
            self.check_rate_limiting,
            self.check_race_conditions,
            self.check_bopla,
            self.check_bola,
            self.check_card_activity_monitoring,
            self.check_transaction_verification,
            self.check_merchant_api,
            self.check_token_invalidation,
            self.check_token_in_url,
            self.check_predictable_identifiers,
            self.check_jwt_algorithm_confusion,
            self.check_prototype_pollution,
            self.check_cache_poisoning,
            self.check_http_request_smuggling,
            self.check_dom_xss,
            self.check_openapi_discovery,
            self.differential_analysis,
            self.detect_waf,
            self.time_based_detection,
            self.ssl_verify,
            self.response_analysis,
        ]

        import concurrent.futures as _cf

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(check): getattr(check, "__name__", str(check))
                for check in checks
            }
            try:
                for future in as_completed(futures, timeout=WEB_SCANNER_CHECK_TIMEOUT):
                    try:
                        future.result(timeout=10)
                    except Exception as e:
                        logger.warning("%s failed: %s", futures[future], e)
            except (TimeoutError, _cf.TimeoutError):
                logger.warning("WebScanner check batch timed out")

        # Sync findings from builder to self.findings for backward compat
        if self._builder:
            self.findings = self._builder.findings

        logger.info("Scan complete: %d findings", len(self.findings))

    @staticmethod
    def _redact_for_llm(text: str) -> str:
        """Redact sensitive data before sending to LLM provider.

        Strips potential secrets (tokens, passwords, keys, internal URLs)
        from HTTP response snippets to prevent data exfiltration.
        """
        import re as _re

        # Redact common credential patterns
        text = _re.sub(
            r'(?i)(api[_-]?key|secret|token|password|passwd|auth|credential)\s*[:=]\s*["\']?[^\s"\'&]+',
            r"\1=__REDACTED__",
            text,
        )
        # Redact bearer tokens
        text = _re.sub(r"(?i)(bearer\s+)[a-z0-9_.-]{20,}", r"\1__REDACTED__", text)
        # Redact AWS keys
        text = _re.sub(r"(?i)(AKIA[0-9A-Z]{16})", "__AWS_KEY_REDACTED__", text)
        # Redact internal IPs
        text = _re.sub(
            r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b",
            "INTERNAL_IP_REDACTED",
            text,
        )
        return text[:500]

    def _report_ssl_finding(self, error_msg: str) -> None:
        """Record an SSL/TLS certificate error as a finding."""
        self._add_finding(
            finding_type="SSL_CERTIFICATE_ERROR",
            severity="MEDIUM",
            endpoint=self.target_url,
            evidence={"error": error_msg[:500]},
            confidence=0.85,
        )

    def _follow_redirects_safe(
        self,
        resp: requests.Response | None,
        session: requests.Session | None = None,
        max_redirects: int = 5,
    ) -> requests.Response | None:
        """Manually follow HTTP redirects with scope and private-IP validation.

        After the initial request is made (with ``allow_redirects=False``),
        this method walks the ``Location`` header chain, validating each
        redirect target against ``_validate_redirect_chain``.

        If a redirect target is out of scope or resolves to a private IP,
        the chain is aborted and a warning is logged. The last valid
        response is returned.

        Args:
            resp: The initial response (may have a redirect status code).
            session: The session to use for follow-up requests (default:
                     ``self.session``).
            max_redirects: Maximum number of redirects to follow.

        Returns:
            The final ``Response`` after the redirect chain (or the initial
            response if no redirects or validation fails).
        """
        if resp is None:
            return None

        session = session or self.session
        current = resp
        redirect_count = 0

        while current.status_code in (301, 302, 303, 307, 308) and redirect_count < max_redirects:
            location = current.headers.get("Location", "")
            if not location:
                break
            # Resolve relative redirects
            redirect_url = urljoin(current.url, location)

            if not _validate_redirect_chain(
                redirect_url, self.target_url, self.engagement_id
            ):
                logger.warning(
                    "Redirect blocked — target %s is out of scope or resolves to private IP "
                    "(original target: %s)",
                    redirect_url,
                    self.target_url,
                )
                break

            try:
                current = session.get(
                    redirect_url,
                    timeout=self.timeout,
                    allow_redirects=False,  # We handle each hop manually
                )
                redirect_count += 1
            except Exception as e:
                logger.debug("Redirect follow failed for %s: %s", redirect_url, e)
                break

        return current

    def _safe_request(
        self, method: str, url: str, session: requests.Session | None = None, **kwargs
    ) -> requests.Response | None:
        """Make HTTP request with error handling. Thread-safe.

        By default checks out a session from the thread-safe pool (C-06).
        Pass an explicit session only when a different auth context is needed
        (e.g., the one-off unverified SSL retry session).

        When ``allow_redirects`` is True (default), the final URL after
        redirects is validated against the scan scope. An out-of-scope
        redirect produces a warning rather than an error, since individual
        scan checks may legitimately follow redirects within the same
        origin.

        Args:
            session: Optional explicit session. If provided, the pool is bypassed.
        """
        pooled_session = None
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("verify", self.verify)  # Verify SSL certs by default

            # Extract redirect intent — always pass allow_redirects=False to
            # requests so we can manually follow each hop with scope validation.
            follow_redirects = kwargs.pop("allow_redirects", True)

            if session is not None:
                # Caller supplied a specific session; use it directly.
                req_session = session
                pooled_session = None
                session_id = "explicit"
            else:
                # Check out an isolated session from the pool. Each worker in
                # the ThreadPoolExecutor gets exclusive access for the duration
                # of one request, eliminating Session-level race conditions.
                pool = self._ensure_pool()
                try:
                    req_session = pool.get(timeout=30)
                    pooled_session = req_session
                    session_id = getattr(req_session, "_argus_session_id", "?")
                    self._checked_out += 1
                except queue.Empty:
                    # Pool is unexpectedly exhausted. Fall back to an ad-hoc
                    # session so the scan can continue, but log loudly so the
                    # operator knows sizing may need adjustment.
                    logger.warning(
                        "WebScanner session pool exhausted (size=%s, checked_out≈%s); "
                        "creating ad-hoc session for this request",
                        self._pool_size,
                        self._checked_out,
                    )
                    req_session = requests.Session()
                    req_session.headers.update(self.session.headers)
                    req_session.cookies = self._shared_cookie_jar
                    pooled_session = None
                    session_id = "adhoc"

            # If the template session was refreshed while this pooled session
            # was idle, update its headers and re-attach the shared cookie jar.
            if (
                pooled_session is not None
                and getattr(req_session, "_argus_generation", None)
                != self._session_generation
            ):
                req_session.headers.update(self.session.headers)
                req_session.cookies = self._shared_cookie_jar
                req_session._argus_generation = self._session_generation  # type: ignore[attr-defined]

            # In-flight re-authentication: periodically check session validity.
            # The counter is protected by a lock; the actual session mutation
            # happens on the checked-out pooled session so the refreshed state
            # is returned to the pool and picked up by future borrowers.
            if self._auth_manager and hasattr(self, "target_url"):
                should_reauth = False
                with self._reauth_lock:
                    self._reauth_request_counter += 1
                    if self._reauth_request_counter >= self._reauth_interval:
                        self._reauth_request_counter = 0
                        should_reauth = True
                if should_reauth:
                    refreshed = self._auth_manager.ensure_session(
                        req_session, self.target_url
                    )
                    if refreshed is not req_session:
                        # Replace template and bump generation so every pooled
                        # session picks up the new headers/cookies on checkout.
                        self.session = refreshed
                        self._session_generation += 1
                        self._shared_cookie_jar.update(refreshed.cookies)
                        req_session.headers.update(refreshed.headers)
                        req_session._argus_generation = self._session_generation  # type: ignore[attr-defined]
                    else:
                        # Session was mutated in place; keep template in sync.
                        self.session.headers.update(req_session.headers)

            # Token-bucket rate limiting with thread-safe lock
            with self._rate_lock:
                now = time.time()
                wait_time = self._last_request_time + self.rate_limit - now
                if wait_time > 0:
                    time.sleep(wait_time)
                self._last_request_time = time.time()
            # Always disable automatic redirects — we follow them manually
            # with scope validation (H-v3-24 SSRF prevention).
            logger.debug("WebScanner session=%s %s %s", session_id, method, url)
            resp = req_session.request(method, url, allow_redirects=False, **kwargs)

            # Manually follow redirects with scope + private-IP validation
            if resp is not None and follow_redirects:
                resp = self._follow_redirects_safe(resp, session=req_session)

            # Remember the response on this thread so _add_finding can attach
            # it as evidence for a MEDIUM+ finding without every check having
            # to thread the object through (H-v4 evidence).
            state = getattr(self, "_request_state", None)
            if resp is not None and state is not None:
                state.last_response = resp

            return resp
        except (
            TimeoutError,
            RequestException,
            Timeout,
            ConnectionError,
            urllib3.exceptions.SSLError,
        ) as e:
            logger.debug("Request failed (session=%s): %s", session_id, e)
            return None
        finally:
            if pooled_session is not None and self._session_pool is not None:
                self._session_pool.put(pooled_session)
                self._checked_out -= 1
                logger.debug("WebScanner session=%s returned to pool", session_id)

    def _add_finding(
        self,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float = 0.8,
        response=None,
    ):
        """Add a finding — delegates to FindingBuilder.

        Creates the builder lazily if needed (backward compat for direct
        ``scan()`` calls without ``execute()``). If an emit_finding_callback
        was provided, streaming is handled automatically by the builder.

        The finding is also appended to ``self.findings`` so that direct
        calls to individual check methods (e.g. ``check_graphql_introspection()``)
        produce immediately visible results.
        """
        if (
            severity.upper() in RESPONSE_EVIDENCE_SEVERITIES
            and "http_response" not in evidence
        ):
            observed = response
            if observed is None:
                observed = getattr(
                    getattr(self, "_request_state", None), "last_response", None
                )
            block = self._response_evidence(observed)
            if block:
                evidence = {**evidence, "http_response": block}
        if self._builder is None:
            self._builder = FindingBuilder(
                source_tool="web_scanner",
                engagement_id=self.engagement_id,
                emit_finding=self.emit_finding_callback,
            )
        finding = self._builder.add(
            finding_type, severity, endpoint, evidence, confidence
        )
        self.findings.append(finding)

    @staticmethod
    def _response_evidence(resp) -> dict:
        """Summarise the response a finding was derived from.

        Hashing the body keeps the record verifiable while the preview stays
        readable. Everything is returned as plain data so it survives the JSON
        round trip into an engagement database.
        """
        if resp is None:
            return {}
        try:
            body = resp.text or ""
        except Exception:  # a broken/streamed body must not lose the finding
            body = ""
        encoded = body.encode("utf-8", errors="ignore")
        try:
            headers = {
                str(key): str(value)
                for key, value in list(resp.headers.items())[:30]
            }
        except Exception:
            headers = {}
        url = getattr(resp, "url", "")
        return {
            "url": url if isinstance(url, str) else "",
            "status_code": getattr(resp, "status_code", None),
            "headers": headers,
            "body_bytes": len(encoded),
            "body_sha256": hashlib.sha256(encoded).hexdigest(),
            "body_preview": body[:500],
        }

    def _detect_framework(self, response) -> str:
        """
        Detect web framework from HTTP response headers and content.

        Args:
            response: HTTP response object

        Returns:
            Framework name string or "unknown"
        """
        if not response:
            return "unknown"

        headers = {k.lower(): v for k, v in response.headers.items()}
        body = response.text[:2000].lower() if response.text else ""

        # Check headers — wrap with str() to handle int header values
        powered_by = str(headers.get("x-powered-by", "")).lower()
        if "django" in body or "csrfmiddlewaretoken" in body:
            return "Django"
        if powered_by:
            if "express" in powered_by:
                return "Express"
            if "asp.net" in powered_by:
                return "ASP.NET"
            if "php" in powered_by:
                return "PHP"
            if "rails" in powered_by or "ruby" in powered_by:
                return "Rails"

        # Check server header — wrap with str() to handle int values
        server = str(headers.get("server", "")).lower()
        if "nginx" in server:
            return "nginx"
        if "apache" in server:
            return "Apache"
        if "iis" in server or "microsoft-iis" in server:
            return "IIS"

        # Check body for framework indicators
        if "laravel" in body or "livewire" in body:
            return "Laravel"
        if "spring" in body or "javax.faces" in body:
            return "Spring"
        if "react" in body or "reactroot" in body:
            return "React"
        if "vue" in body or "vuejs" in body or "vueroot" in body:
            return "Vue"
        if "angular" in body or "ng-" in body:
            return "Angular"
        if "next" in body or "__next" in body or "nextjs" in body:
            return "Next.js"
        if "nuxt" in body:
            return "Nuxt"
        if "wordpress" in body or "wp-" in body or "wp-content" in body:
            return "WordPress"
        if "drupal" in body:
            return "Drupal"
        if "joomla" in body:
            return "Joomla"
        if "shopify" in body:
            return "Shopify"
        if "magento" in body:
            return "Magento"

        return "unknown"

    def _tech_hints(self, resp) -> str:
        """
        Combined technology hints from runtime detection + recon tech_stack.

        Args:
            resp: HTTP response object for runtime framework detection

        Returns:
            Comma-separated technology hints string (e.g. "WordPress, PHP, jQuery")
        """
        hints = self._detect_framework(resp)
        if self.tech_stack:
            extra = ", ".join(self.tech_stack[:8])
            if hints != "unknown":
                return f"{hints}, {extra}"
            return extra
        return hints

    def check_security_headers(self):
        """Check for missing security headers."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        headers = {k.lower(): v for k, v in resp.headers.items()}
        present = [h for h in self.SECURITY_HEADERS if h.lower() in headers]

        for header, severity in self.SECURITY_HEADERS.items():
            if header.lower() in headers:
                continue
            self._add_finding(
                finding_type=self.HEADER_FINDING_TYPES[header],
                severity=severity,
                endpoint=self.target_url,
                evidence={
                    "header": header,
                    "missing_headers": [header],
                    "present_headers": present,
                    "message": f"{header} is not set on this response",
                },
                confidence=0.95,
                response=resp,
            )

    def check_csp(self):
        """Analyze Content-Security-Policy for weaknesses."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        csp = resp.headers.get("Content-Security-Policy", "")
        if not csp:
            self._add_finding(
                finding_type="MISSING_CSP",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={"message": "No Content-Security-Policy header found"},
                confidence=0.95,
                response=resp,
            )
            return

        # Check for unsafe directives
        unsafe = []
        if "unsafe-inline" in csp:
            unsafe.append("unsafe-inline")
        if "unsafe-eval" in csp:
            unsafe.append("unsafe-eval")
        if "*." in csp or "*:" in csp:
            unsafe.append("wildcard domains")

        if unsafe:
            self._add_finding(
                finding_type="WEAK_CSP",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "unsafe_directives": unsafe,
                    "csp_preview": csp[:200],
                },
                confidence=0.9,
                response=resp,
            )

    def check_cookies(self):
        """Check cookie security attributes."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Get Set-Cookie headers - use getlist for multi-value headers
        cookie_headers = (
            resp.raw.headers.getlist("Set-Cookie")
            if hasattr(resp.raw.headers, "getlist")
            else []
        )
        if not cookie_headers:
            cookie_header = resp.headers.get("Set-Cookie")
            if not cookie_header:
                return
            # Fallback: use http.cookies to parse multi-cookie headers safely
            from http.cookies import SimpleCookie

            try:
                parsed = SimpleCookie(cookie_header)
                cookie_headers = [
                    c.output(header="", sep="").strip() for c in parsed.values()
                ]
            except Exception:
                # Last resort: split on newlines if present
                cookie_headers = (
                    cookie_header.split("\n")
                    if "\n" in cookie_header
                    else [cookie_header]
                )

        for cookie_str in cookie_headers:
            issues = []
            if "HttpOnly" not in cookie_str:
                issues.append("Missing HttpOnly")
            if "Secure" not in cookie_str:
                issues.append("Missing Secure")
            if "SameSite" not in cookie_str:
                issues.append("Missing SameSite")

            if issues:
                cookie_name = (
                    cookie_str.split("=")[0] if "=" in cookie_str else "unknown"
                )
                self._add_finding(
                    finding_type="INSECURE_COOKIE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "cookie": cookie_name,
                        "issues": issues,
                    },
                    confidence=0.9,
                )

    def check_cors(self):
        """Check for CORS misconfigurations."""
        resp = self._safe_request(
            "GET", self.target_url, headers={"Origin": "http://evil.com"}
        )
        if not resp:
            return

        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        acac = resp.headers.get("Access-Control-Allow-Credentials", "")

        if acao == "*":
            self._add_finding(
                finding_type="WILDCARD_CORS",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "Access-Control-Allow-Origin": "*",
                    "message": "Wildcard CORS allows any origin",
                },
                confidence=0.9,
            )
        elif acao == "http://evil.com":
            acac_str = str(acac) if acac is not None else ""
            severity = "CRITICAL" if acac_str.lower() == "true" else "HIGH"
            self._add_finding(
                finding_type="REFLECTED_ORIGIN_CORS",
                severity=severity,
                endpoint=self.target_url,
                evidence={
                    "Access-Control-Allow-Origin": acao,
                    "Access-Control-Allow-Credentials": acac,
                    "message": "Server reflected evil.com origin",
                },
                confidence=0.9,
            )

        # L-12: Test null origin — exploitable via sandboxed iframes
        null_resp = self._safe_request(
            "GET", self.target_url, headers={"Origin": "null"}
        )
        if null_resp:
            null_acao = null_resp.headers.get("Access-Control-Allow-Origin", "")
            if null_acao == "null":
                null_acac = null_resp.headers.get(
                    "Access-Control-Allow-Credentials", ""
                )
                sev = "CRITICAL" if str(null_acac).lower() == "true" else "HIGH"
                self._add_finding(
                    finding_type="NULL_ORIGIN_CORS",
                    severity=sev,
                    endpoint=self.target_url,
                    evidence={
                        "Access-Control-Allow-Origin": null_acao,
                        "Access-Control-Allow-Credentials": null_acac,
                        "message": "Server accepts null origin — exploitable via sandboxed iframes",
                    },
                    confidence=0.85,
                )

    def check_sensitive_files(self):
        """Check for exposed sensitive files with improved validation."""
        # File signatures to validate actual content
        file_signatures = {
            ".env": [b"=", b"API", b"SECRET", b"DATABASE_URL"],
            ".git/config": b"[core]",
            ".git/HEAD": b"ref: refs/",
            ".git/COMMIT_EDITMSG": b"commit ",
            "credentials.json": b"api",
            ".aws/credentials": b"[default]",
            "id_rsa": b"PRIVATE KEY",
            "wp-config.php": b"<?php",
            "config.php": b"<?php",
            ".htpasswd": b"$apr",
            "database.yml": b"database:",
            "secrets.yml": b"secret:",
            "docker-compose.yml": b"version:",
            "settings.py": b"import ",
            ".npmrc": b"registry",
            ".pypirc": b"[distutils]",
        }

        # Text that indicates NOT_FOUND / custom 404 (even with HTTP 200)
        # These patterns mean the file doesn't actually exist
        not_found_patterns = [
            "not found",
            "does not exist",
            "page not found",
            "return to",
            "go back",
            "homepage",
            "invalid url",
            "wrong url",
            "url not found",
            "nothing here",
            "no such page",
            "page does not",
        ]

        for path in self.SENSITIVE_FILES:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue

            content = resp.text

            # Need substantial content
            if len(content) < 50:
                continue

            # CRITICAL CHECK: Custom 404 that says "not found" (even with HTTP 200)
            content_lower = content.lower()
            is_custom_404 = any(
                pattern in content_lower for pattern in not_found_patterns
            )

            if is_custom_404:
                logger.debug("Skipping %s - custom 404 (not actually exposed)", path)
                continue

            # CRITICAL CHECK: Must not be HTML (SPA catch-all false positive)
            content_first100 = content[:100].lower()
            html_signatures = [b"<!doctype html", b"<html", b"scroll-smooth"]
            is_html_response = any(
                sig in content_first100.encode() for sig in html_signatures
            )

            if is_html_response:
                # This is a false positive - the server returns HTML for all paths
                logger.debug("Skipping %s - returns HTML (not actually exposed)", path)
                continue

            # Check for file-specific signatures
            expected_signatures = file_signatures.get(path, [])
            if expected_signatures:
                content_bytes = content.encode("utf-8", errors="ignore")
                has_signature = any(sig in content_bytes for sig in expected_signatures)
            else:
                # For unknown files, check it's not HTML and has reasonable content
                has_signature = len(content) > 100

            if has_signature:
                # Calculate confidence based on how specific the match is
                confidence = 0.95 if expected_signatures else 0.6
                self._add_finding(
                    finding_type="EXPOSED_SENSITIVE_FILE",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "file": path,
                        "status_code": resp.status_code,
                        "content_length": len(content),
                        "content_preview": content[:200],
                        "verified": bool(expected_signatures),
                    },
                    confidence=confidence,
                    response=resp,
                )

    def check_js_secrets(self):
        """Scan JavaScript files for secrets."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Find JS file references
        js_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', resp.text)

        # Also check inline scripts
        inline_scripts = re.findall(
            r"<script[^>]*>(.*?)</script>", resp.text, re.DOTALL
        )

        # Scan inline scripts
        for script in inline_scripts:
            if len(script) > 50:  # Skip tiny scripts
                self._scan_content_for_secrets(
                    script, self.target_url + "/inline-script"
                )

        # Scan external JS files (limit to first 10)
        for js_url in js_urls[:MAX_PAGES_TO_CRAWL]:
            if not js_url.startswith("http"):
                js_url = urljoin(self.target_url, js_url)

            js_resp = self._safe_request("GET", js_url)
            if js_resp and js_resp.status_code == 200:
                self._scan_content_for_secrets(js_resp.text, js_url)

    def _scan_content_for_secrets(self, content: str, source: str):
        """Scan content for secret patterns."""
        for pattern, secret_type in self.JS_SECRET_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                # Mask the secrets
                masked = []
                for m in matches[:3]:  # Limit to 3
                    if len(m) > 8:
                        masked.append(m[:4] + "..." + m[-4:])
                    else:
                        masked.append("***")

                self._add_finding(
                    finding_type="EXPOSED_SECRET",
                    severity="CRITICAL",
                    endpoint=source,
                    evidence={
                        "secret_type": secret_type,
                        "matches_found": len(matches),
                        "masked_values": masked,
                    },
                    confidence=0.85,
                )

    def check_open_redirects(self):
        """Check for open redirect parameters."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Find URLs with redirect parameters
        url_params = re.findall(r"[?&](\w+)=", resp.text)

        for param in self.REDIRECT_PARAMS:
            if param in url_params or param in resp.text.lower():
                # Test the parameter
                test_url = f"{self.target_url}?{param}=http://evil.com"
                test_resp = self._safe_request("GET", test_url, allow_redirects=False)
                if test_resp and test_resp.status_code in (301, 302, 303, 307, 308):
                    location = test_resp.headers.get("Location", "")
                    if "evil.com" in location:
                        self._add_finding(
                            finding_type="OPEN_REDIRECT",
                            severity="HIGH",
                            endpoint=test_url,
                            evidence={
                                "parameter": param,
                                "redirect_to": location,
                                "status_code": test_resp.status_code,
                            },
                            confidence=0.8,
                        )

    def check_host_header_injection(self):
        """Check for host header injection."""
        for host in self.HOST_INJECTION:
            resp = self._safe_request("GET", self.target_url, headers={"Host": host})
            if resp:
                # Check if response reflects the injected host
                if host.lower() in resp.text.lower():
                    self._add_finding(
                        finding_type="HOST_HEADER_INJECTION",
                        severity="HIGH",
                        endpoint=self.target_url,
                        evidence={
                            "injected_host": host,
                            "reflected_in_response": True,
                        },
                        confidence=0.75,
                    )
                    break

                # Check Location header
                location = resp.headers.get("Location", "")
                if host.lower() in location.lower():
                    self._add_finding(
                        finding_type="HOST_HEADER_INJECTION",
                        severity="HIGH",
                        endpoint=self.target_url,
                        evidence={
                            "injected_host": host,
                            "redirect_to": location,
                        },
                        confidence=0.8,
                    )
                    break

    def check_verb_tampering(self):
        """Check for HTTP verb tampering."""
        methods = ["TRACE", "DELETE", "PUT", "PATCH", "OPTIONS"]

        for method in methods:
            resp = self._safe_request(method, self.target_url)
            # L-11: Report all accepted dangerous methods, not just TRACE.
            # TRACE enables XST (cross-site tracing). DELETE/PUT/PATCH
            # acceptance on non-API endpoints may indicate misconfiguration.
            if resp and resp.status_code not in (405, 404, 403, 501):
                severity = "HIGH" if method == "TRACE" else "MEDIUM"
                self._add_finding(
                    finding_type="HTTP_VERB_TAMPERING",
                    severity=severity,
                    endpoint=self.target_url,
                    evidence={
                        "method": method,
                        "status_code": resp.status_code,
                        "message": f"Server accepts {method} method",
                    },
                    confidence=0.8,
                )

    def check_debug_endpoints(self):
        """Check for exposed debug/admin endpoints with improved validation."""
        debug_paths = [
            "/debug",
            "/_debug",
            "/console",
            "/actuator",
            "/actuator/env",
            "/actuator/health",
            "/__debug__",
            "/phpinfo.php",
            "/info.php",
            "/_profiler",
            "/server-status",
            "/.env",
        ]

        # Content signatures for actual debug pages
        debug_signatures = {
            "/phpinfo.php": [b"php version", b"PHP_VERSION"],
            "/info.php": [b"php version", b"PHP_VERSION"],
            "/actuator/env": [b"spring", b"application", b"property"],
            "/actuator/health": [b"status", b"UP", b"DOWN"],
            "/actuator": [b"href", b"env", b"health"],
            "/server-status": [b"Server Status", b"Apache", b"nginx"],
        }

        # HTML signatures that indicate SPA catch-all
        html_signatures = [b"<!DOCTYPE html", b"<html", b"<!DOCTYPE", b"scroll-smooth"]

        for path in debug_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue

            content = resp.text
            content_lower = content.lower()

            # Must have substantial content
            if len(content) < 100:
                continue

            # CRITICAL CHECK: Must not be HTML (SPA catch-all false positive)
            content_first100 = content[:100].lower().encode()
            is_html_response = any(
                html_sig in content_first100 for html_sig in html_signatures
            )

            if is_html_response:
                logger.debug("Skipping %s - returns HTML (not actually exposed)", path)
                continue

            # Check for actual debug indicators
            debug_indicators = [
                "debug",
                "stack trace",
                "exception",
                "phpinfo",
                "profiler",
                "actuator",
            ]

            has_debug_content = any(
                indicator in content_lower for indicator in debug_indicators
            )

            # Or check specific signatures
            signatures = debug_signatures.get(path, [])
            if signatures:
                content_bytes = content.encode("utf-8", errors="ignore")
                has_signature = any(sig in content_bytes for sig in signatures)
            else:
                has_signature = has_debug_content

            # Also check for HTML forms (potential debug consoles)
            is_console = "function" in content_lower and "eval" in content_lower

            if has_debug_content or has_signature or is_console:
                confidence = 0.9 if (signatures or has_debug_content) else 0.7
                self._add_finding(
                    finding_type="EXPOSED_DEBUG_ENDPOINT",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "path": path,
                        "status_code": resp.status_code,
                        "content_preview": content[:200],
                        "verified": bool(signatures),
                    },
                    confidence=confidence,
                )

    def check_auth_endpoints(self):
        """Check for authentication endpoints and test default credentials."""
        auth_paths = [
            "/login",
            "/signin",
            "/auth",
            "/admin",
            "/dashboard",
            "/api/auth/login",
            "/api/login",
            "/wp-login.php",
        ]

        for path in auth_paths:
            url = urljoin(self.target_url, path.lstrip("/"))

            # Check if endpoint exists
            resp = self._safe_request("GET", url)
            if (
                resp
                and resp.status_code in (200, 302)
                and self.ENABLE_CREDENTIAL_TESTING
            ):
                for username, password in self.DEFAULT_CREDS[:3]:  # Limit to 3
                    login_resp = self._safe_request(
                        "POST",
                        url,
                        data={"username": username, "password": password},
                        allow_redirects=False,
                    )
                    if login_resp and login_resp.status_code in (200, 302):
                        # Check if login was successful (redirect to dashboard, etc.) — wrap with str() for int values
                        location = str(login_resp.headers.get("Location", "")).lower()
                        if any(
                            x in location
                            for x in ["dashboard", "admin", "home", "welcome"]
                        ):
                            self._add_finding(
                                finding_type="DEFAULT_CREDENTIALS",
                                severity="CRITICAL",
                                endpoint=url,
                                evidence={
                                    "username": username,
                                    "password": password,
                                    "redirect_to": location,
                                },
                                confidence=0.7,
                            )

    def parameter_discovery(self):
        """
        Discover input parameters from forms, URLs, JSON, and JavaScript.

        Crawls the target site (up to max_pages) and extracts URL query
        parameters, form input names, JSON keys from inline scripts, and
        JavaScript variable names. Discovered parameters are stored in
        self.discovered_parameters for use by subsequent tests.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running parameter discovery")

        # Initialize early so parameter_fuzzing() doesn't fail if we raise below
        self.discovered_parameters = {
            "url_parameters": [],
            "form_parameters": [],
            "json_parameters": [],
            "javascript_parameters": [],
        }

        discovered = {
            "url_parameters": set(),
            "form_parameters": set(),
            "json_parameters": set(),
            "javascript_parameters": set(),
        }

        # Crawl main page and linked pages
        to_crawl = [self.target_url]
        crawled = set()
        max_pages = MAX_PAGES_TO_CRAWL

        while to_crawl and len(crawled) < max_pages:
            url = to_crawl.pop(0)
            if url in crawled:
                continue
            crawled.add(url)

            resp = self._safe_request("GET", url)
            if not resp:
                continue

            # Extract URL parameters
            url_params = re.findall(r"[?&](\w+)=", url)
            discovered["url_parameters"].update(url_params)

            # Extract form parameters
            form_inputs = re.findall(
                r'<input[^>]*name=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            discovered["form_parameters"].update(form_inputs)

            form_selects = re.findall(
                r'<select[^>]*name=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            discovered["form_parameters"].update(form_selects)

            # Extract JSON keys from inline scripts
            script_blocks = re.findall(
                r"<script[^>]*>(.*?)</script>", resp.text, re.DOTALL | re.IGNORECASE
            )
            script_content = " ".join(script_blocks)
            json_keys = set(re.findall(r'["\'](\w+)["\']\s*:\s*', script_content))
            if not json_keys:
                json_keys = set(re.findall(r'["\'](\w+)["\']\s*:\s*', resp.text)[:50])
            discovered["json_parameters"].update(json_keys)

            # Extract JavaScript variables that might be parameters
            js_vars = re.findall(
                r"(?:var|let|const)\s+(\w+)\s*=",
                resp.text,
            )
            discovered["javascript_parameters"].update(js_vars)

            # Extract links to crawl further
            links = re.findall(
                r'href=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            for link in links:
                absolute = urljoin(url, link)
                # H-v3-12: Use URL-parsed host matching, not string prefix,
                # to prevent scope escape via subdomain squatting (e.g.
                # https://example.com.evil.com matching https://example.com)
                if absolute not in crawled and _is_in_scope(
                    absolute, self.target_url, self.engagement_id
                ):
                    to_crawl.append(absolute)

        # Store discovered parameters for use by other checks
        self.discovered_parameters = {
            key: list(values) for key, values in discovered.items()
        }

        # Add finding if parameters were discovered
        total = sum(len(v) for v in self.discovered_parameters.values())
        if total > 0:
            self._add_finding(
                finding_type="PARAMETER_DISCOVERY",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "total_discovered": total,
                    "url_parameters": self.discovered_parameters["url_parameters"][:20],
                    "form_parameters": self.discovered_parameters["form_parameters"][
                        :20
                    ],
                    "json_parameters": self.discovered_parameters["json_parameters"][
                        :20
                    ],
                    "pages_crawled": len(crawled),
                },
                confidence=0.8,
            )

    def parameter_fuzzing(self):
        """
        Fuzz discovered parameters with a variety of injection payloads.

        Uses parameters stored in self.discovered_parameters and tests
        each with payloads for SQL injection, XSS, path traversal, command
        injection, null bytes, large values, and special characters. Flags
        server errors (500) and payload reflection as potential issues.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running parameter fuzzing")

        if not self.discovered_parameters:
            return

        # Simple fuzz payloads to test parameter handling
        fuzz_payloads = [
            ("sqli", "' OR '1'='1"),
            ("sqli_comment", "admin'--"),
            ("xss", "<script>alert(1)</script>"),
            ("path_traversal", "../../../etc/passwd"),
            ("cmd_injection", "; id"),
            ("null_byte", "test%00.jpg"),
            ("large_value", "A" * 10000),
            ("special_chars", "!@#$%^&*()"),
        ]

        all_params = []
        for param_list in self.discovered_parameters.values():
            all_params.extend(param_list)

        tested = 0
        for param in all_params[:MAX_PARAMETERS_TO_FUZZ]:  # Limit to first 20 params
            for fuzz_type, payload in fuzz_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                resp = self._safe_request("GET", test_url)
                tested += 1

                if not resp:
                    continue

                # Check for interesting responses
                if resp.status_code == 500:
                    self._add_finding(
                        finding_type="PARAMETER_FUZZ_500",
                        severity="MEDIUM",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload_type": fuzz_type,
                            "payload": payload,
                            "status_code": 500,
                            "message": "Payload caused server error",
                        },
                        confidence=0.5,
                    )
                elif payload in resp.text:
                    self._add_finding(
                        finding_type="PARAMETER_REFLECTION",
                        severity="LOW",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload_type": fuzz_type,
                            "payload": payload,
                            "message": "Payload reflected in response",
                        },
                        confidence=0.6,
                    )

        logger.info("Parameter fuzzing complete: %d tests performed", tested)

        # R-08: POST body fuzzing — test form parameters via POST with JSON body.
        # Many injection points only exist in POST bodies, not URL query params.
        form_params = self.discovered_parameters.get("form_parameters", [])
        if form_params:
            post_params = form_params[:MAX_PARAMETERS_TO_FUZZ]
            for param in post_params:
                for fuzz_type, payload in fuzz_payloads[:4]:  # Test core payloads only
                    post_body = {param: payload}
                    resp = self._safe_request(
                        "POST",
                        self.target_url,
                        json=post_body,
                        headers={"Content-Type": "application/json"},
                    )
                    tested += 1
                    if not resp:
                        continue
                    if resp.status_code == 500:
                        self._add_finding(
                            finding_type="POST_FUZZ_500",
                            severity="MEDIUM",
                            endpoint=self.target_url,
                            evidence={
                                "parameter": param,
                                "payload_type": fuzz_type,
                                "payload": payload,
                                "status_code": 500,
                                "message": f"POST body payload caused server error ({fuzz_type})",
                            },
                            confidence=0.55,
                        )
                    elif payload in resp.text:
                        self._add_finding(
                            finding_type="POST_PARAMETER_REFLECTION",
                            severity="LOW",
                            endpoint=self.target_url,
                            evidence={
                                "parameter": param,
                                "payload_type": fuzz_type,
                                "payload": payload,
                                "message": "POST body payload reflected in response",
                            },
                            confidence=0.6,
                        )

    def check_mass_assignment(self):
        """Check for mass assignment vulnerabilities."""
        api_paths = ["/api/v1/users", "/api/users", "/api/v1/accounts", "/api/accounts"]

        resp = None
        for path in api_paths:
            url = urljoin(self.target_url, path.lstrip("/"))

            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="MASS_ASSIGNMENT",
                    param_name="json_body",
                    response_snippet="",
                    framework_hints=self._tech_hints(resp)
                    if resp
                    else ", ".join(self.tech_stack),
                )

            all_payloads = (
                self.MASS_ASSIGN_PAYLOADS[:2]
                + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
            )
            for payload in all_payloads:
                resp = self._safe_request(
                    "POST",
                    url,
                    json=json.loads(payload),
                    headers={"Content-Type": "application/json"},
                )
                if resp and resp.status_code in (200, 201):
                    # Check if response contains admin-related fields
                    try:
                        data = resp.json()
                        data_str = json.dumps(data).lower()
                        if any(
                            x in data_str
                            for x in ["admin", "role", "privilege", "is_admin"]
                        ):
                            self._add_finding(
                                finding_type="MASS_ASSIGNMENT",
                                severity="HIGH",
                                endpoint=url,
                                evidence={
                                    "payload": payload,
                                    "response_preview": json.dumps(data)[:200],
                                },
                                confidence=0.6,
                            )
                    except (json.JSONDecodeError, ValueError):
                        logger.debug(
                            "Mass assignment: failed to parse JSON response from %s",
                            url,
                        )

    #: Hidden field names that indicate a form carries an anti-CSRF token.
    CSRF_TOKEN_FIELD_RE = re.compile(
        r'name=["\'](?:csrf|_csrf|csrf_token|csrfmiddlewaretoken|'
        r'authenticity_token|__requestverificationtoken|_token|xsrf[_-]token)["\']',
        re.I,
    )

    def check_csrf(self):
        """Report state-changing forms with no anti-CSRF token.

        A POST form that submits nothing secret and accepts no ``SameSite``
        cookie is forgeable from any origin. Only forms actually served to the
        scanner are judged, so the finding names a real action URL instead of a
        guess.
        """
        resp = self._safe_request("GET", self.target_url)
        if not resp or not resp.text:
            return

        for form in re.finditer(
            r"<form\b([^>]*)>(.*?)</form>", resp.text, re.I | re.S
        ):
            attrs, body = form.group(1), form.group(2)
            method_match = re.search(r"method=[\"'](\w+)[\"']", attrs, re.I)
            method = (method_match.group(1) if method_match else "get").lower()
            if method != "post":
                continue
            action_match = re.search(r"action=[\"']([^\"']*)[\"']", attrs, re.I)
            action = action_match.group(1) if action_match else self.target_url
            action_url = urljoin(self.target_url + "/", action)

            if self.CSRF_TOKEN_FIELD_RE.search(body):
                continue
            if re.search(r'type=["\']hidden["\'][^>]*name=["\'](?:\w*token\w*)["\']', body, re.I):
                continue

            self._add_finding(
                finding_type="MISSING_CSRF_TOKEN",
                severity="MEDIUM",
                endpoint=action_url,
                evidence={
                    "message": (
                        "State-changing form has no anti-CSRF token; a "
                        "cross-site request can submit it with the victim's cookies"
                    ),
                    "form_action": action,
                    "method": "POST",
                },
                confidence=0.7,
            )
            return

    def check_xss(self):
        """Check for reflected XSS with improved validation."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Find URL parameters that accept user input
        params = re.findall(r"[?&]([\w-]+)=", resp.text)
        if not params:
            return

        # Only test inputs that look like they accept user data
        # Avoid testing navigation params
        ignore_params = [
            "redirect",
            "next",
            "url",
            "dest",
            "target",
            "goto",
            "continue",
            "return",
            "ref",
            "dest_url",
        ]

        for param in set(params[:5]):
            if param.lower() in ignore_params:
                continue

            # Generate LLM payloads for this parameter context
            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="XSS",
                    param_name=param,
                    response_snippet=self._redact_for_llm(resp.text) if resp else "",
                    framework_hints=self._tech_hints(resp),
                )

            # Use static payloads + LLM-generated payloads
            all_payloads = (
                self.XSS_PAYLOADS[:3] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
            )

            for payload in all_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if not test_resp:
                    continue

                # Check if payload is reflected UNENCODED
                # This matters - <script> vs &lt;script&gt;
                if payload in test_resp.text:
                    # Only flag HIGH if it's in script context or event handler
                    # Not just reflected in HTML (which browsers escape)
                    is_script_context = (
                        "<script>" in test_resp.text.lower()
                        or "<script " in test_resp.text.lower()
                    )

                    # Calculate confidence based on context
                    if is_script_context:
                        confidence = 0.85
                        severity = "HIGH"
                    elif payload.startswith("<img") or payload.startswith("<svg"):
                        # These can work in some contexts
                        confidence = 0.7
                        severity = "MEDIUM"
                    else:
                        confidence = 0.5
                        severity = "LOW"

                    self._add_finding(
                        finding_type="REFLECTED_XSS",
                        severity=severity,
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload": payload,
                            "reflected": True,
                            "verified": is_script_context,
                        },
                        confidence=confidence,
                    )
                    break

        # R-01: POST body XSS — test form parameters via POST with JSON body.
        form_params = (
            self.discovered_parameters.get("form_parameters", [])
            if self.discovered_parameters
            else []
        )
        if form_params:
            for param in set(form_params[:5]):
                if param.lower() in ignore_params:
                    continue
                for payload in self.XSS_PAYLOADS[:3]:
                    post_body = {param: payload}
                    test_resp = self._safe_request(
                        "POST",
                        self.target_url,
                        json=post_body,
                        headers={"Content-Type": "application/json"},
                    )
                    if not test_resp:
                        continue
                    if payload in test_resp.text:
                        is_script_ctx = "<script>" in test_resp.text.lower()
                        self._add_finding(
                            finding_type="POST_REFLECTED_XSS",
                            severity="HIGH" if is_script_ctx else "MEDIUM",
                            endpoint=self.target_url,
                            evidence={
                                "parameter": param,
                                "payload": payload,
                                "reflected": True,
                                "method": "POST",
                                "verified": is_script_ctx,
                            },
                            confidence=0.8 if is_script_ctx else 0.6,
                        )
                        break

    def check_ssti(self):
        """Check for Server-Side Template Injection with improved validation."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        params = re.findall(r"[?&](\w+)=", resp.text)
        if not params:
            return

        for param in set(params[:3]):
            # Generate LLM payloads for this parameter context
            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="SSTI",
                    param_name=param,
                    response_snippet=self._redact_for_llm(resp.text) if resp else "",
                    framework_hints=self._tech_hints(resp),
                )

            # Static + LLM payloads
            test_payloads = ["{{7*7}}", "${7*7}", "<%= 7*7 %>"] + llm_payloads[
                :LLM_MAX_GENERATED_PAYLOADS
            ]
            for payload in test_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if not test_resp:
                    continue

                # Must see EVALUATION (49), not just reflection
                # Check for patterns like "49", " 49 ", or numeric 49 in context
                has_evaluation = " 49 " in test_resp.text or ">49<" in test_resp.text

                # Also verify it's NOT error or part of another word
                if (
                    has_evaluation
                    and "error" not in test_resp.text.lower()
                    and "undefined" not in test_resp.text.lower()
                ):
                    self._add_finding(
                        finding_type="SSTI",
                        severity="CRITICAL",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload": payload,
                            "result": "49 (7*7 evaluated)",
                            "verified": True,
                        },
                        confidence=0.9,
                    )
                    break

    def check_lfi(self):
        """Check for Local File Inclusion."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        params = re.findall(r"[?&](\w+)=", resp.text)
        if not params:
            return

        for param in set(params[:3]):
            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="LFI",
                    param_name=param,
                    response_snippet=self._redact_for_llm(resp.text) if resp else "",
                    framework_hints=self._tech_hints(resp),
                )

            all_payloads = (
                self.LFI_PAYLOADS[:2] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
            )
            for payload in all_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if test_resp and "root:x:" in test_resp.text:
                    self._add_finding(
                        finding_type="LFI",
                        severity="CRITICAL",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload": payload,
                            "file_read": "/etc/passwd",
                        },
                        confidence=0.8,
                    )
                    break

    #: Canary used by the SSRF probe. It resolves nowhere and points at a
    #: closed port on loopback: a target that fetches it returns a connection
    #: error, which proves server-side fetching without reading anything real
    #: (no cloud-metadata endpoint is ever contacted).
    SSRF_CANARY = "http://127.0.0.1:1/argus-ssrf-canary"
    SSRF_URL_PARAMS = (
        "url",
        "uri",
        "link",
        "image",
        "image_url",
        "avatar",
        "avatar_url",
        "photo",
        "profile_image",
        "callback",
        "webhook",
        "feed",
        "source",
        "src",
        "target",
    )
    SSRF_ERROR_SIGNATURES = (
        "connection refused",
        "failed to connect",
        "could not connect",
        "connectex",
        "econnrefused",
        "getaddrinfo",
        "name or service not known",
        "nodename nor servname",
        "no route to host",
        "connection timed out",
        "urlopen error",
        "ssrf-canary",
    )

    def check_ssrf(self):
        """Probe URL-accepting inputs for server-side request forgery.

        Profile-image import, webhook configuration and link previews fetch a
        user-supplied URL server-side. The probe supplies a loopback canary and
        looks for the target's own connection error in the response — evidence
        that the server made the request. The canary never points at cloud
        metadata, so a vulnerable target leaks nothing during the test.
        """
        probe_urls: list[str] = [
            urljoin(self.target_url, path.lstrip("/")) for path in self.UPLOAD_PATHS
        ]
        for discovered in self.discovered_urls:
            for param in re.findall(r"[?&](\w+)=", discovered):
                if param.lower() in self.SSRF_URL_PARAMS:
                    probe_urls.append(discovered)
                    break

        seen: set[str] = set()
        for url in probe_urls:
            if url in seen:
                continue
            seen.add(url)
            requests_to_make = []
            if "?" in url:
                parsed = urlparse(url)
                query = parse_qs(parsed.query)
                for param in list(query):
                    if param.lower() in self.SSRF_URL_PARAMS:
                        query[param] = [self.SSRF_CANARY]
                        replaced = parsed._replace(query=urlencode(query, doseq=True))
                        requests_to_make.append(("GET", replaced.geturl(), None))
            else:
                for param in ("url", "image_url", "avatar_url"):
                    requests_to_make.append(
                        ("POST", url, {param: self.SSRF_CANARY})
                    )
                requests_to_make.append(
                    ("GET", f"{url}?url={quote(self.SSRF_CANARY, safe='')}", None)
                )

            for method, probe_url, body in requests_to_make:
                resp = self._safe_request(method, probe_url, json=body) if body else self._safe_request(method, probe_url)
                if not resp or not resp.text:
                    continue
                lowered = resp.text.lower()
                matched = [sig for sig in self.SSRF_ERROR_SIGNATURES if sig in lowered]
                if matched:
                    self._add_finding(
                        finding_type="SSRF",
                        severity="HIGH",
                        endpoint=probe_url,
                        evidence={
                            "message": (
                                "Server fetched a URL supplied by the client — "
                                "response contains the outbound connection error"
                            ),
                            "parameter": body and next(iter(body)) or "url",
                            "canary": self.SSRF_CANARY,
                            "indicators": matched,
                            "status": resp.status_code,
                            "response_preview": resp.text[:300],
                        },
                        confidence=0.8,
                    )
                    return

    def check_xxe(self):
        """Check for XML External Entity injection."""
        xxe_payload = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'

        resp = self._safe_request(
            "POST",
            self.target_url,
            data=xxe_payload,
            headers={"Content-Type": "application/xml"},
        )
        if resp and "root:x:" in resp.text:
            self._add_finding(
                finding_type="XXE",
                severity="CRITICAL",
                endpoint=self.target_url,
                evidence={
                    "payload": "XXE file:///etc/passwd",
                    "file_read": "/etc/passwd",
                },
                confidence=0.8,
            )

    def check_graphql_introspection(self):
        """Check for enabled GraphQL introspection."""
        for path in self.GRAPHQL_ENDPOINTS:
            url = urljoin(self.target_url, path.lstrip("/"))
            # Check if endpoint exists
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code not in (200, 400, 405):
                continue

            # R-07: Use full introspection query that captures types, fields,
            # and their nested type information — the previous query was too
            # minimal and returned partial data from servers that expose
            # detailed schemas.
            introspection_query = {
                "query": """{
                    __schema {
                        queryType { name }
                        mutationType { name }
                        types {
                            kind
                            name
                            fields {
                                name
                                type { name kind }
                            }
                        }
                    }
                }"""
            }
            resp = self._safe_request(
                "POST",
                url,
                json=introspection_query,
                headers={"Content-Type": "application/json"},
            )
            if resp and resp.status_code == 200:
                try:
                    data = resp.json()
                    if "__schema" in data.get("data", {}):
                        self._add_finding(
                            finding_type="GRAPHQL_INTROSPECTION_ENABLED",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "message": "GraphQL introspection is enabled",
                                "response_preview": json.dumps(data)[:200],
                            },
                            confidence=0.9,
                        )
                        break
                except json.JSONDecodeError:
                    pass

        # Depth/complexity limits and raw error disclosure. Run on the first
        # endpoint that actually answers, so a target with no GraphQL costs
        # one request rather than a probe per path.
        for path in self.GRAPHQL_ENDPOINTS:
            candidate = urljoin(self.target_url, path.lstrip("/"))
            probe = self._safe_request("GET", candidate)
            if probe and probe.status_code in (200, 400, 405):
                self._check_graphql_depth_and_errors(candidate)
                break

        # GraphQL depth/complexity check — detect excessive schema exposure
        for path in self.GRAPHQL_ENDPOINTS:
            url = urljoin(self.target_url, path.lstrip("/"))
            depth_query = {
                "query": "{__schema{types{name,fields{name,type{name,fields{name}}}}}}"
            }
            resp = self._safe_request(
                "POST",
                url,
                json=depth_query,
                headers={"Content-Type": "application/json"},
            )
            if resp and resp.status_code == 200 and len(resp.text) > 5000:
                self._add_finding(
                    finding_type="GRAPHQL_DEEP_INTROSPECTION",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={
                        "response_size": len(resp.text),
                        "message": "GraphQL schema exposes deeply nested type details",
                    },
                    confidence=0.7,
                )
            break  # Only test first available endpoint

        # GraphQL SQLi-in-resolver test
        for path in self.GRAPHQL_ENDPOINTS[:1]:
            url = urljoin(self.target_url, path.lstrip("/"))
            sqli_query = {"query": '{users(search:"\' OR 1=1--"){id,name}}'}
            resp = self._safe_request(
                "POST",
                url,
                json=sqli_query,
                headers={"Content-Type": "application/json"},
            )
            if (
                resp
                and resp.status_code == 200
                and resp.text
                and len(resp.text.strip("{} \t\n\r\x00")) > 5
            ):
                try:
                    data = resp.json()
                    if (
                        isinstance(data.get("data"), dict)
                        and len(data.get("data", {})) > 0
                    ):
                        self._add_finding(
                            finding_type="GRAPHQL_SQLI_RESOLVER",
                            severity="CRITICAL",
                            endpoint=url,
                            evidence={
                                "payload": sqli_query["query"],
                                "response_preview": json.dumps(data)[:200],
                                "message": "Possible SQL injection in GraphQL resolver — query returned data",
                            },
                            confidence=0.6,
                        )
                except json.JSONDecodeError:
                    pass

    #: A deliberately deep query. A server without a depth/complexity limit
    #: executes it; one with a limit answers with an error instead of data.
    GRAPHQL_DEPTH_QUERY = (
        "{a{a{a{a{a{a{a{a{a{a{id}}}}}}}}}}"
    )

    def _check_graphql_depth_and_errors(self, url: str) -> None:
        """Depth/complexity limit and raw-error disclosure for a GraphQL URL."""
        resp = self._safe_request(
            "POST",
            url,
            json={"query": self.GRAPHQL_DEPTH_QUERY},
            headers={"Content-Type": "application/json"},
        )
        if resp and resp.status_code == 200:
            try:
                body = resp.json()
            except (ValueError, json.JSONDecodeError):
                body = None
            errors = (body or {}).get("errors") if isinstance(body, dict) else None
            error_text = json.dumps(errors).lower() if errors else ""
            limited = any(
                word in error_text
                for word in (
                    "depth",
                    "complexity",
                    "too complex",
                    "max",
                    "limit",
                    "exceed",
                )
            )
            if not limited:
                self._add_finding(
                    finding_type="GRAPHQL_DEPTH_LIMIT_MISSING",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={
                        "message": "GraphQL endpoint executed a deeply nested query with no depth/complexity limit",
                        "query": self.GRAPHQL_DEPTH_QUERY,
                        "status": resp.status_code,
                    },
                    confidence=0.7,
                )

        # Raw error disclosure: an invalid selection should be answered with a
        # generic error, not a stack trace / file path / "Did you mean" hints.
        resp = self._safe_request(
            "POST",
            url,
            json={"query": "{__argus_no_such_field_xyz}"},
            headers={"Content-Type": "application/json"},
        )
        if resp and resp.status_code in (200, 400, 500) and resp.text:
            text = resp.text
            lowered = text.lower()
            disclosure_indicators = (
                "did you mean",
                "traceback",
                "stack trace",
                "at line",
                "node_modules",
                "/usr/",
                "graphql.ts",
                "resolver",
                "sql",
                "exception",
            )
            matched = [word for word in disclosure_indicators if word in lowered]
            if matched:
                self._add_finding(
                    finding_type="VERBOSE_API_ERROR",
                    severity="LOW",
                    endpoint=url,
                    evidence={
                        "message": "GraphQL error response discloses internal details",
                        "indicators": matched,
                        "response_preview": text[:300],
                    },
                    confidence=0.75,
                )

    def check_financial_logic(self):
        """Test financial API endpoints for business logic flaws."""
        for path in self.TRANSFER_PATHS:
            url = urljoin(self.target_url, path)
            # Field names differ per product: "from"/"to", "to_account",
            # "recipient". Sending every alias costs nothing and stops a 422
            # (unknown field) from hiding an accepted amount.
            base_payload = {
                "from": "test_source",
                "from_account": "test_source",
                "to": "test_dest",
                "to_account": "test_dest",
                "recipient": "test_dest",
            }

            # Test 1: Negative amount
            neg_resp = self._safe_request(
                "POST", url, json={**base_payload, "amount": -100}
            )
            if neg_resp and neg_resp.status_code in (200, 201):
                self._add_finding(
                    finding_type="NEGATIVE_AMOUNT_ACCEPTED",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "amount": -100,
                        "status": neg_resp.status_code,
                        "message": "API accepted a negative transaction amount",
                    },
                    confidence=0.85,
                )

            # Test 2: Zero amount
            zero_resp = self._safe_request(
                "POST", url, json={**base_payload, "amount": 0}
            )
            if zero_resp and zero_resp.status_code in (200, 201):
                self._add_finding(
                    finding_type="ZERO_AMOUNT_ACCEPTED",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={
                        "amount": 0,
                        "status": zero_resp.status_code,
                        "message": "API accepted a zero-value transaction",
                    },
                    confidence=0.75,
                )

            # Test 3: Extremely large amount
            large_resp = self._safe_request(
                "POST", url, json={**base_payload, "amount": 99999999999}
            )
            if large_resp and large_resp.status_code in (200, 201):
                self._add_finding(
                    finding_type="NO_TRANSACTION_LIMIT",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "amount": 99999999999,
                        "status": large_resp.status_code,
                        "message": "API accepted an extremely large amount with no limit",
                    },
                    confidence=0.8,
                )

            # Test 4: Idempotency / replay check
            replay_responses = []
            replay_payload = {**base_payload, "amount": 1}
            for _ in range(3):
                r = self._safe_request("POST", url, json=replay_payload)
                if r:
                    replay_responses.append(r.status_code)
            if replay_responses.count(200) + replay_responses.count(201) >= 2:
                self._add_finding(
                    finding_type="REPLAY_VULNERABLE",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={
                        "success_count": replay_responses.count(200),
                        "total_requests": 3,
                        "message": "API accepted repeated identical requests — no idempotency key",
                    },
                    confidence=0.7,
                )
            break  # Only test first available endpoint

    def check_file_upload(self):
        """Test file upload endpoints for security controls."""
        # Benign, uniquely identifiable payload (C-v3-06) — previously used a live
        # PHP webshell (<?php @eval($_POST['cmd']); ?>) which could compromise the
        # target. Replaced with a harmless text marker that cannot execute.
        benign_marker = b"ARGUS_UPLOAD_TEST_MARKER_%s" % uuid.uuid4().hex[:8].encode()
        malicious_payloads = [
            ("shell.php.txt", benign_marker, "text/plain"),
            ("test.php.jpg", b"ARGUS_UPLOAD_TEST_JPG", "image/jpeg"),
            ("../../../etc/passwd", b"content", "text/plain"),
            ("test.phtml.txt", benign_marker, "text/plain"),
            ("test.phar.txt", benign_marker, "application/octet-stream"),
        ]

        for path in self.UPLOAD_PATHS:
            url = urljoin(self.target_url, path)
            for filename, content, mime in malicious_payloads:
                resp = self._safe_request(
                    "POST", url, files={"file": (filename, content, mime)}
                )
                if resp and resp.status_code in (200, 201):
                    if (
                        filename.endswith(".php")
                        or filename.endswith(".phtml")
                        or filename.endswith(".phar")
                    ):
                        self._add_finding(
                            finding_type="UNRESTRICTED_FILE_UPLOAD",
                            severity="CRITICAL",
                            endpoint=url,
                            evidence={
                                "filename": filename,
                                "mime": mime,
                                "status": resp.status_code,
                                "message": f"Executable file '{filename}' accepted by server",
                            },
                            confidence=0.9,
                        )
                    if ".." in filename:
                        self._add_finding(
                            finding_type="PATH_TRAVERSAL_IN_FILENAME",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "filename": filename,
                                "status": resp.status_code,
                                "message": "Path traversal characters accepted in filename",
                            },
                            confidence=0.85,
                        )
            break  # Only test first available endpoint

    def check_token_storage(self):
        """Check if JWT/session tokens are stored in localStorage."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Look for localStorage.setItem with token keywords in page JS
        token_storage_patterns = [
            r'localStorage\.setItem\s*\(\s*["\'].*(?:token|jwt|auth|session|access)',
            r'localStorage\[["\'].*(?:token|jwt|auth)\s*["\']\s*\]\s*=',
        ]
        for pattern in token_storage_patterns:
            match = re.search(pattern, resp.text, re.I)
            if match:
                context_start = max(0, match.start() - 30)
                context_end = min(len(resp.text), match.end() + 50)
                self._add_finding(
                    finding_type="TOKEN_IN_LOCALSTORAGE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "snippet": resp.text[context_start:context_end],
                        "pattern": pattern,
                        "message": "JWT or session token stored in localStorage — vulnerable to XSS extraction",
                    },
                    confidence=0.8,
                )
                break

    def check_session_expiration(self):
        """Check whether login tokens have expiry claims (JWT exp field)."""
        # Try to extract JWTs from responses — look in common auth response patterns
        auth_paths = ["/login", "/api/auth/login", "/api/login", "/auth/login"]
        jwt_pattern = r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"

        for path in auth_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            # Use the engagement's credentials when present. A login probe
            # with test/test is rejected by every real target, which is why
            # "no session expiration" was never observable on authenticated
            # engagements even though the check existed.
            login_payload = {"username": "test", "password": "test"}
            cred_user = self._credentials.get("username") or self._credentials.get(
                "email", ""
            )
            cred_pass = self._credentials.get("password", "")
            if cred_user and cred_pass:
                login_payload = {"username": cred_user, "password": cred_pass}
            resp = self._safe_request(
                "POST",
                url,
                json=login_payload,
                headers={"Content-Type": "application/json"},
            )
            if not resp:
                continue

            # Look for JWT in response body
            tokens = re.findall(jwt_pattern, resp.text)
            if not tokens:
                # Check response headers too
                auth_header = resp.headers.get("Authorization") or resp.headers.get(
                    "Set-Cookie", ""
                )
                tokens = re.findall(jwt_pattern, auth_header)

            import base64 as _b64

            for raw_token in tokens[:2]:
                try:
                    # Decode JWT without signature verification
                    parts = raw_token.split(".")
                    if len(parts) != 3:
                        continue
                    padding = 4 - len(parts[1]) % 4
                    if padding != 4:
                        parts[1] += "=" * padding
                    payload_bytes = _b64.urlsafe_b64decode(parts[1])
                    payload = json.loads(payload_bytes)
                    exp = payload.get("exp")
                    now = time.time()

                    if not exp:
                        self._add_finding(
                            finding_type="NO_TOKEN_EXPIRATION",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "token_preview": raw_token[:30] + "...",
                                "jwt_payload_keys": list(payload.keys()),
                                "message": "JWT has no 'exp' claim — token never expires",
                            },
                            confidence=0.9,
                        )
                    elif exp - now > 86400 * 30:
                        days = min(int((exp - now) / 86400), 365)
                        self._add_finding(
                            finding_type="EXCESSIVE_TOKEN_LIFETIME",
                            severity="MEDIUM",
                            endpoint=url,
                            evidence={
                                "expiry_days": days,
                                "token_preview": raw_token[:30] + "...",
                                "message": f"JWT expiry set to {days} days — exceeds 30-day maximum",
                            },
                            confidence=0.8,
                        )
                except (json.JSONDecodeError, KeyError):
                    logger.debug(
                        "JWT session expiration check failed for %s",
                        url,
                        exc_info=False,
                    )
            break

    def check_password_reset_strength(self):
        """Detect weak reset tokens — numeric-only PINs, short codes."""
        for path in self.RESET_PATHS:
            url = urljoin(self.target_url, path)
            resp = self._safe_request(
                "POST",
                url,
                json={"email": "test@example.com"},
                headers={"Content-Type": "application/json"},
            )
            # Only fall back to form-encoded if JSON was explicitly rejected (415)
            if resp and resp.status_code == 415:
                resp = self._safe_request(
                    "POST", url, data={"email": "test@example.com"}
                )

            if resp and resp.status_code in (200, 201):
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    data = {}
                reset_token = str(
                    data.get("token") or data.get("code") or data.get("pin") or ""
                )
                if not reset_token:
                    # Check if token is embedded in a message
                    token_match = re.search(
                        r'(?:token|code|pin)[:\s]+["\']?(\w{3,32})["\']?',
                        resp.text,
                        re.I,
                    )
                    if token_match:
                        reset_token = token_match.group(1)

                if reset_token:
                    if reset_token.isdigit() and len(reset_token) <= 6:
                        self._add_finding(
                            finding_type="WEAK_RESET_TOKEN",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "token_length": len(reset_token),
                                "type": "numeric",
                                "message": f"Password reset uses a {len(reset_token)}-digit numeric PIN — brute-forceable",
                            },
                            confidence=0.85,
                        )
                    elif len(reset_token) < 16:
                        self._add_finding(
                            finding_type="SHORT_RESET_TOKEN",
                            severity="MEDIUM",
                            endpoint=url,
                            evidence={
                                "token_length": len(reset_token),
                                "message": f"Reset token is only {len(reset_token)} chars — minimum recommended is 32",
                            },
                            confidence=0.7,
                        )
            break  # Only test first available endpoint

    def check_rate_limiting(self):
        """Test whether endpoints enforce rate limiting."""
        for path in self.RATE_LIMIT_PATHS:
            url = urljoin(self.target_url, path)
            responses = []
            for _ in range(20):
                r = self._safe_request(
                    "POST",
                    url,
                    json={"username": "test", "password": "wrong"},
                    headers={"Content-Type": "application/json"},
                )
                if r:
                    responses.append(r.status_code)

            has_rate_limit = any(code in (429, 403) for code in responses)
            if not has_rate_limit and len(responses) >= 15:
                self._add_finding(
                    finding_type="NO_RATE_LIMITING",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "requests_sent": 20,
                        "responses_received": len(responses),
                        "rate_limit_response_received": False,
                        "status_codes_seen": list(set(responses)),
                        "message": "No 429/403 response after 20 rapid requests — no rate limiting in place",
                    },
                    confidence=0.85,
                )
            break  # Only test first available endpoint

    def check_race_conditions(self):
        """Test financial endpoints for race conditions via simultaneous requests."""
        import concurrent.futures as _cf

        for path in self.RACE_PATHS:
            url = urljoin(self.target_url, path)
            payload = {"amount": 1, "from": "race_source", "to": "race_dest"}

            # Use a barrier to maximize simultaneity
            barrier = threading.Barrier(5, timeout=5)
            barrier_broken = [False]  # Mutable to capture from thread closures

            def _race_request(
                barrier=barrier, barrier_broken=barrier_broken, url=url, payload=payload
            ):
                try:
                    barrier.wait(timeout=5)
                except threading.BrokenBarrierError:
                    barrier_broken[0] = True
                return self._safe_request("POST", url, json=payload)

            with _cf.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(_race_request) for _ in range(5)]
                responses = [f.result() for f in _cf.as_completed(futures)]

            if barrier_broken[0]:
                continue  # Test inconclusive — threads didn't synchronize

            success_count = sum(
                1 for r in responses if r and r.status_code in (200, 201)
            )
            if success_count > 1:
                self._add_finding(
                    finding_type="RACE_CONDITION",
                    severity="CRITICAL",
                    endpoint=url,
                    evidence={
                        "simultaneous_requests": 5,
                        "successful_responses": success_count,
                        "response_codes": [r.status_code for r in responses if r],
                        "note": "Multiple concurrent requests succeeded — possible double-spend",
                    },
                    confidence=0.8,
                )
            break  # Only test first available endpoint

    def check_bopla(self):
        """Check for sensitive fields in API responses (Broken Object Property Level Auth)."""
        api_paths = [
            "/api/v1/users",
            "/api/users",
            "/api/v1/accounts",
            "/api/accounts",
            "/api/v1/me",
            "/api/me",
            "/api/profile",
            # Card/bill/merchant surfaces expose PAN, CVV, limits and
            # billing details; they belong in the property-level check.
            "/api/cards",
            "/api/v1/cards",
            "/api/wallet",
            "/api/transactions",
            "/api/bills",
            "/api/billers",
            "/api/merchant/transactions",
            "/api/merchant/profile",
        ]

        for path in api_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request(
                "GET", url, headers={"Content-Type": "application/json"}
            )
            if not resp or resp.status_code != 200:
                continue

            try:
                data = resp.json()
            except json.JSONDecodeError:
                continue

            # Search response for sensitive field names
            data_str = json.dumps(data).lower()
            exposed_fields = []
            for field in self.SENSITIVE_RESPONSE_FIELDS:
                pattern = f'"{field}"'
                if pattern in data_str:
                    exposed_fields.append(field)

            if exposed_fields:
                self._add_finding(
                    finding_type="SENSITIVE_FIELD_EXPOSURE",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "exposed_fields": exposed_fields,
                        "response_keys": list(data.keys())
                        if isinstance(data, dict)
                        else "array",
                        "message": f"API response includes {len(exposed_fields)} sensitive fields that should be filtered",
                    },
                    confidence=0.85,
                )

    @staticmethod
    def _owner_values(payload, depth: int = 0) -> set[str]:
        """Owner identifiers found anywhere in a JSON response.

        Depth is bounded so a hostile or accidentally recursive document
        cannot make the scanner spin.
        """
        found: set[str] = set()
        if depth > 4:
            return found
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in WebScanner.BOLA_OWNER_FIELDS and isinstance(
                    value, (str, int)
                ):
                    found.add(str(value).lower())
                found |= WebScanner._owner_values(value, depth + 1)
        elif isinstance(payload, list):
            for value in payload[:20]:
                found |= WebScanner._owner_values(value, depth + 1)
        return found

    def _own_identity(self) -> set[str]:
        """Who the current session is, as identifiers usable for ownership.

        Includes JWT claims when the session carries a token, because a
        target that never exposes ``/api/me`` can still tell us our subject.
        """
        identity: set[str] = set()

        token = self.session.headers.get("Authorization", "")
        token = token.replace("Bearer", "").strip()
        parts = token.split(".")
        if len(parts) == 3:
            try:
                import base64 as _b64

                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                claims = json.loads(_b64.urlsafe_b64decode(padded).decode("utf-8"))
                for key in ("sub", "user_id", "userId", "id", "email", "username"):
                    if isinstance(claims.get(key), (str, int)):
                        identity.add(str(claims[key]).lower())
            except Exception:
                pass

        for path in self.BOLA_IDENTITY_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                continue
            values = self._owner_values(data)
            if values:
                identity |= values
                break
        return identity

    def check_bola(self):
        """Test object-level authorization (BOLA/IDOR) on a logged-in session.

        A request made as one user must not return another user's object. The
        check learns the session's own identifiers, then fetches object URLs
        (harvested from the authenticated surface and from common resource
        shapes) and compares the owner recorded in each response with them.
        When no identity endpoint exists, two adjacent ids that both return
        200 with *different* owners are still proof that one session can read
        objects belonging to more than one principal.
        """
        if not self._authenticated:
            return

        own = self._own_identity()

        candidates: list[str] = []
        for url in self.discovered_urls:
            if re.search(r"/\d+(?:/|$|\?)", url) or re.search(
                r"[?&](?:id|user_id|account_id|card_id|bill_id)=\d+", url
            ):
                candidates.append(url)
        for template in self.BOLA_RESOURCE_TEMPLATES:
            for object_id in (1, 2, 3):
                candidates.append(
                    urljoin(self.target_url, template.format(id=object_id).lstrip("/"))
                )

        seen: set[str] = set()
        observed: list[tuple[str, set[str]]] = []
        checked = 0
        for url in candidates:
            if url in seen or checked >= 12:
                continue
            seen.add(url)
            checked += 1
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                continue
            owners = self._owner_values(data)
            if not owners:
                continue

            if own and not (owners & own):
                self._add_finding(
                    finding_type="BOLA",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": (
                            "Authenticated session received an object owned by "
                            "another user — missing object-level authorization"
                        ),
                        "own_identity": sorted(own)[:5],
                        "object_owner": sorted(owners)[:5],
                        "status": resp.status_code,
                    },
                    confidence=0.85,
                )
                return

            observed.append((url, owners))

        # No identity endpoint: different owners served to one session.
        if not own and len(observed) >= 2:
            first_url, first_owners = observed[0]
            for other_url, other_owners in observed[1:]:
                if first_owners and other_owners and not (first_owners & other_owners):
                    self._add_finding(
                        finding_type="BOLA",
                        severity="HIGH",
                        endpoint=other_url,
                        evidence={
                            "message": (
                                "One authenticated session can read objects "
                                "belonging to different principals — possible BOLA"
                            ),
                            "first_object_owner": sorted(first_owners)[:5],
                            "second_object_owner": sorted(other_owners)[:5],
                            "first_url": first_url,
                        },
                        confidence=0.7,
                    )
                    return

    # --- Banking surface checks (cards, merchant API, session lifecycle) ---

    def _api_json(self, method: str, url: str, **kwargs):
        """Request helper returning ``(response, parsed_json_or_None)``."""
        resp = self._safe_request(method, url, **kwargs)
        if resp is None:
            return None, None
        try:
            return resp, resp.json()
        except (ValueError, json.JSONDecodeError):
            return resp, None

    @staticmethod
    def _card_number(card: dict) -> str:
        """Digits of a PAN from any of the field names products use."""
        for key in ("card_number", "pan", "number", "masked_number", "card_no"):
            value = card.get(key)
            if isinstance(value, (str, int)):
                digits = re.sub(r"\D", "", str(value))
                if 12 <= len(digits) <= 19:
                    return digits
        return ""

    def check_card_security(self):
        """Cards: plaintext details, predictable PANs, mass-assigned limits.

        A virtual-card surface has four observable flaws without touching
        another customer: full PAN/CVV returned to the client, sequentially
        generated card numbers, limit/balance fields that mass assignment can
        overwrite, and a limit update that ignores validation. All four need a
        logged-in session; the card the check creates is its own object.
        """
        if not self._authenticated:
            return

        # 1. List cards and look for full card data in the response.
        for path in self.CARD_LIST_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp, data = self._api_json("GET", url)
            if not resp or resp.status_code != 200:
                continue
            text = json.dumps(data) if data is not None else (resp.text or "")
            has_pan = bool(re.search(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)", text))
            has_cvv = bool(re.search(r'"(?:cvv2?|cvc|security_code)"\s*:', text, re.I))
            if has_pan and has_cvv:
                self._add_finding(
                    finding_type="CARD_DETAILS_EXPOSED",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": (
                            "Card API returns the full PAN together with CVV; "
                            "card details are stored and served in plaintext"
                        ),
                        "response_preview": self._redact_for_llm(text)[:400],
                    },
                    confidence=0.9,
                )
            break

        # 2. Create two cards and compare their numbers.
        created: list[dict] = []
        create_url = ""
        for path in self.CARD_CREATE_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp, data = self._api_json(
                "POST", url, json={"card_limit": 100, "card_type": "standard"}
            )
            if resp is None or resp.status_code not in (200, 201):
                continue
            create_url = url
            card = None
            if isinstance(data, dict):
                for key in ("card_details", "card", "data"):
                    if isinstance(data.get(key), dict):
                        card = data[key]
                        break
                card = card or data
            if isinstance(card, dict):
                created.append({"url": url, "card": card})
            if len(created) >= 2:
                break

        pans = [self._card_number(entry["card"]) for entry in created]
        usable = [p for p in pans if p]
        if len(usable) >= 2:
            try:
                delta = abs(int(usable[0]) - int(usable[1]))
            except ValueError:
                delta = -1
            same_bin = usable[0][:8] == usable[1][:8]
            if same_bin and 0 < delta < 1000:
                self._add_finding(
                    finding_type="PREDICTABLE_CARD_NUMBER",
                    severity="HIGH",
                    endpoint=create_url or self.target_url,
                    evidence={
                        "message": (
                            "Two cards created in a row differ by a small offset "
                            "under the same BIN — card numbers are sequential and "
                            "predictable"
                        ),
                        "card_numbers": [f"****{p[-4:]}" for p in usable[:2]],
                        "numeric_delta": delta,
                    },
                    confidence=0.85,
                )

        # A create/read response that hands back the full PAN with its CVV is
        # plaintext card storage + card-detail disclosure even when the card
        # list itself was empty before the check created anything.
        for entry in created:
            blob = json.dumps(entry["card"])
            if re.search(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)", blob) and re.search(
                r'"(?:cvv2?|cvc|security_code)"\s*:', blob, re.I
            ):
                self._add_finding(
                    finding_type="CARD_DETAILS_EXPOSED",
                    severity="HIGH",
                    endpoint=entry["url"],
                    evidence={
                        "message": (
                            "Card creation response returns the full PAN and CVV "
                            "— card details are stored and disclosed in plaintext"
                        ),
                        "response_preview": self._redact_for_llm(blob)[:400],
                    },
                    confidence=0.9,
                )
                break

        self._probe_cards = [
            {**entry, "pan": pan}
            for entry, pan in zip(created, pans, strict=False)
            if entry
        ]

        # 3. Mass assignment on the card limit update.
        if created:
            card = created[0]["card"]
            card_id = card.get("id") or card.get("card_id")
            if card_id is not None:
                injected = {
                    "limit": 99999,
                    "card_limit": 99999,
                    "balance": 999999,
                    "status": "active",
                    "user_id": 1,
                    "card_number": "4111111111111111",
                }
                for template in self.CARD_LIMIT_TEMPLATES:
                    url = urljoin(
                        self.target_url, template.format(id=card_id).lstrip("/")
                    )
                    resp, data = self._api_json("POST", url, json=injected)
                    if resp is None:
                        continue
                    blob = (json.dumps(data) if data is not None else "") + (
                        resp.text or ""
                    )
                    reflected = [
                        field
                        for field in ("999999", "4111111111111111", "99999")
                        if field in blob
                    ]
                    # A handler that builds SQL from the client-controlled
                    # limit/balance/user_id fields answers 500 with the query
                    # in the body. That still proves the fields are accepted
                    # (mass assignment) and additionally leaks SQL.
                    field_echo = re.search(
                        r"\b(?:SET|UPDATE)\b[^\n]{0,120}\b(?:balance|user_id|card_number)\b",
                        blob,
                        re.I,
                    )
                    accepted = resp.status_code in (200, 201, 204)
                    if accepted or (resp.status_code >= 500 and field_echo):
                        reflected = reflected or ["SQL built from injected fields"]
                    if reflected:
                        self._add_finding(
                            finding_type="MASS_ASSIGNMENT_CARD_LIMITS",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "message": (
                                    "Card limit update accepted and reflected "
                                    "fields the client must not control "
                                    "(balance/card number/limit beyond validation)"
                                ),
                                "injected_fields": sorted(injected),
                                "reflected_values": reflected,
                                "status": resp.status_code,
                            },
                            confidence=0.8,
                        )
                    break

    def check_card_activity_monitoring(self):
        """Whether a freshly created card has any activity/audit trail."""
        if not self._authenticated:
            return
        cards = getattr(self, "_probe_cards", [])
        if not cards:
            return

        entry = cards[0]
        card = entry.get("card") or {}
        card_id = card.get("id") or card.get("card_id")
        if card_id is None:
            return

        endpoint_found = False
        empty = False
        for template in self.CARD_ACTIVITY_TEMPLATES:
            url = urljoin(self.target_url, template.format(id=card_id).lstrip("/"))
            resp, data = self._api_json("GET", url)
            if not resp or resp.status_code != 200:
                continue
            endpoint_found = True
            items = data
            if isinstance(data, dict):
                for key in ("transactions", "activity", "data", "items"):
                    if isinstance(data.get(key), list):
                        items = data[key]
                        break
            empty = not items
            break

        if not endpoint_found or empty:
            self._add_finding(
                finding_type="LACK_OF_CARD_ACTIVITY_MONITORING",
                severity="LOW",
                endpoint=entry.get("url") or self.target_url,
                evidence={
                    "message": (
                        "A newly created card has no activity/audit trail "
                        "(creation, freeze, limit change are not recorded)"
                        if endpoint_found
                        else "No card activity endpoint exists for a created card"
                    ),
                    "card_id": card_id,
                    "activity_endpoint_found": endpoint_found,
                },
                confidence=0.6,
            )

    def check_transaction_verification(self):
        """Whether a card charge needs any verification beyond PAN/CVV.

        The merchant charge API is the transaction surface a card is spent on.
        A charge that succeeds with raw card data and no OTP/3DS/challenge in
        the response shows the target performs no transaction verification.
        """
        if not self._authenticated:
            return

        pan = "4111111111111111"
        cvv = "123"
        expiry = "12/30"
        cards = getattr(self, "_probe_cards", [])
        if cards:
            card = cards[0].get("card") or {}
            pan = self._card_number(card) or pan
            cvv = str(card.get("cvv") or card.get("cvv2") or cvv)
            expiry = str(card.get("expiry_date") or card.get("expiry") or expiry)

        for path in self.MERCHANT_CHARGE_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp, data = self._api_json(
                "POST",
                url,
                json={
                    "amount": 0.01,
                    "currency": "USD",
                    "card_number": pan,
                    "cvv": cvv,
                    "expiry_date": expiry,
                    "merchant_order_id": f"argus-verify-{uuid.uuid4().hex[:8]}",
                    "description": "argus transaction verification probe",
                },
            )
            if resp is None:
                continue
            if resp.status_code not in (200, 201):
                continue
            blob = ((json.dumps(data) if data is not None else "") + (resp.text or "")).lower()
            challenged = any(
                marker in blob
                for marker in ("otp", "3ds", "3-d", "verification_required", "challenge")
            )
            if not challenged:
                self._add_finding(
                    finding_type="NO_TRANSACTION_VERIFICATION",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": (
                            "A card charge was approved from PAN/CVV alone — no "
                            "OTP, 3-D Secure or other transaction verification"
                        ),
                        "raw_card_data_accepted": True,
                        "status": resp.status_code,
                    },
                    confidence=0.75,
                )
            break

    def check_merchant_api(self):
        """Merchant API: key echoed in responses and payment object BOLA."""
        if not self._authenticated:
            return

        email = f"argus-probe-{uuid.uuid4().hex[:8]}@example.com"
        password = f"Argus-{uuid.uuid4().hex[:10]}!"
        merchant_id = None

        for path in self.MERCHANT_REGISTER_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp, data = self._api_json(
                "POST",
                url,
                json={"name": "Argus Probe Merchant", "email": email, "password": password},
            )
            if resp is None or resp.status_code not in (200, 201):
                continue
            blob = (json.dumps(data) if data is not None else "") + (resp.text or "")
            if isinstance(data, dict):
                merchant_id = data.get("merchant_id") or data.get("id")
            leaked = [
                field
                for field in self.MERCHANT_KEY_FIELDS
                if re.search(rf'"{field}"\s*:\s*"[^"]{{6,}}"', blob, re.I)
            ]
            if leaked:
                self._add_finding(
                    finding_type="MERCHANT_KEY_IN_RESPONSE",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": (
                            "Merchant registration response returns credentials "
                            "(API key/secret or password) to the client"
                        ),
                        "leaked_fields": leaked,
                    },
                    confidence=0.9,
                )
            break

        merchant_token = ""
        for path in self.MERCHANT_LOGIN_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp, data = self._api_json(
                "POST", url, json={"email": email, "password": password}
            )
            if resp is None or resp.status_code != 200 or not isinstance(data, dict):
                continue
            blob = json.dumps(data)
            leaked = [
                field
                for field in self.MERCHANT_KEY_FIELDS
                if re.search(rf'"{field}"\s*:\s*"[^"]{{6,}}"', blob, re.I)
            ]
            if leaked:
                self._add_finding(
                    finding_type="MERCHANT_KEY_IN_RESPONSE",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": "Merchant login response returns the API key/secret",
                        "leaked_fields": leaked,
                    },
                    confidence=0.9,
                )
            merchant_id = merchant_id or data.get("merchant_id") or data.get("id")
            merchant_token = (
                data.get("token") or data.get("access_token") or data.get("api_key") or ""
            )
            break

        if not merchant_token:
            return

        # Object-level authorization: ask for other merchants' payments.
        merchant_session = requests.Session()
        merchant_session.headers.update(
            {
                "Authorization": f"Bearer {merchant_token}",
                "Content-Type": "application/json",
                "User-Agent": self.session.headers.get("User-Agent", "Argus-Scanner/1.0"),
            }
        )
        own = str(merchant_id) if merchant_id is not None else ""
        bola_found = False
        for template in self.MERCHANT_PAYMENT_TEMPLATES:
            for other_id in (1, 2, 999):
                if own and str(other_id) == own:
                    continue
                url = urljoin(
                    self.target_url, template.format(id=other_id).lstrip("/")
                )
                try:
                    resp = merchant_session.get(
                        url, timeout=self.timeout, verify=self.verify
                    )
                except requests.RequestException:
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    body = resp.json()
                except (ValueError, json.JSONDecodeError):
                    continue
                text = json.dumps(body)
                if not re.search(r"payment|amount|card", text, re.I):
                    continue
                self._add_finding(
                    finding_type="BOLA",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": (
                            "Merchant token read another merchant's payments — "
                            "object-level authorization missing on the merchant "
                            "payment lookup"
                        ),
                        "merchant_id": own or "unknown",
                        "requested_id": other_id,
                        "response_preview": self._redact_for_llm(text)[:300],
                    },
                    confidence=0.7,
                )
                bola_found = True
                break
            if bola_found:
                break

        # A merchant charge made with raw PAN/CVV and no challenge shows that
        # transaction verification stops at the card fields themselves. The
        # charge is issued with the merchant token and our own probe card.
        cards = getattr(self, "_probe_cards", [])
        if not cards:
            return
        card = cards[0].get("card") or {}
        pan = self._card_number(card)
        if not pan:
            return
        challenge_markers = ("otp", "3ds", "3-d", "verification_required", "challenge")
        for path in self.MERCHANT_CHARGE_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            try:
                resp = merchant_session.post(
                    url,
                    json={
                        "amount": 0.01,
                        "currency": "USD",
                        "card_number": pan,
                        "cvv": str(card.get("cvv") or card.get("cvv2") or "123"),
                        "expiry_date": str(
                            card.get("expiry_date") or card.get("expiry") or "12/30"
                        ),
                        "merchant_order_id": f"argus-verify-{uuid.uuid4().hex[:8]}",
                        "description": "argus transaction verification probe",
                    },
                    timeout=self.timeout,
                    verify=self.verify,
                )
            except requests.RequestException:
                continue
            text = resp.text or ""
            lower = text.lower()
            if any(marker in lower for marker in challenge_markers):
                break
            card_processed = any(
                marker in lower
                for marker in ("card_id", "payment_id", "failure_reason", "approved", "declined")
            )
            if card_processed:
                self._add_finding(
                    finding_type="NO_TRANSACTION_VERIFICATION",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "message": (
                            "A card charge was processed from PAN/CVV alone — no "
                            "OTP, 3-D Secure or other transaction verification"
                        ),
                        "raw_card_data_accepted": True,
                        "status": resp.status_code,
                        "decline_reason": (
                            "failure_reason present" if "failure_reason" in lower else ""
                        ),
                    },
                    confidence=0.8,
                )
            if "debug_info" in lower or "failure_reason" in lower:
                self._add_finding(
                    finding_type="VERBOSE_API_ERROR",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={
                        "message": (
                            "Payment decline response discloses debug data and the "
                            "detailed failure reason to the merchant client"
                        ),
                        "response_preview": self._redact_for_llm(text)[:300],
                    },
                    confidence=0.8,
                )
            break

    def check_token_invalidation(self):
        """Replay a session after logout to test server-side invalidation."""
        if not self._authenticated:
            return

        probe_url = ""
        for path in self.BOLA_IDENTITY_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            # NB: requests.Response is falsy for 4xx/5xx, so compare explicitly.
            if resp is not None and resp.status_code == 200:
                probe_url = url
                break

        token = self.session.headers.get("Authorization", "")
        cookies = list(self.session.cookies)
        if not token and not cookies:
            return

        logout_confirmed = False
        for path in self.LOGOUT_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            try:
                resp = self.session.request(
                    "POST", url, timeout=self.timeout, allow_redirects=True, verify=self.verify
                )
            except requests.RequestException:
                continue
            if resp.status_code < 400:
                logout_confirmed = True
                break
        if not logout_confirmed:
            # No logout/revocation endpoint at all. A stateless JWT without a
            # revocation id (jti) has no server-side mechanism to be
            # invalidated: this is weaker evidence than a replay, so it is
            # reported as a medium-severity gap rather than a confirmed issue.
            raw = token.replace("Bearer", "").strip()
            parts = raw.split(".")
            claims = {}
            if len(parts) == 3:
                try:
                    import base64 as _b64

                    padded = parts[1] + "=" * (-len(parts[1]) % 4)
                    claims = json.loads(_b64.urlsafe_b64decode(padded).decode("utf-8"))
                except Exception:
                    claims = {}
            if claims and "jti" not in claims:
                self._add_finding(
                    finding_type="NO_SERVER_SIDE_TOKEN_INVALIDATION",
                    severity="MEDIUM",
                    endpoint=probe_url or self.target_url,
                    evidence={
                        "message": (
                            "No logout/revocation endpoint was found and the "
                            "bearer JWT carries no revocation identifier (jti) — "
                            "the server has no way to invalidate a token"
                        ),
                        "logout_endpoints_tried": len(self.LOGOUT_PATHS),
                        "jwt_claims": sorted(claims)[:8],
                    },
                    confidence=0.55,
                )
            return

        # Replay the exact credential material captured before logout.
        replay = requests.Session()
        replay.headers.update(
            {"User-Agent": self.session.headers.get("User-Agent", "Argus-Scanner/1.0")}
        )
        if token:
            replay.headers["Authorization"] = token
        for cookie in cookies:
            replay.cookies.set(cookie.name, cookie.value)
        try:
            resp = replay.get(probe_url, timeout=self.timeout, verify=self.verify)
        except requests.RequestException:
            return
        if resp.status_code == 200:
            self._add_finding(
                finding_type="NO_SERVER_SIDE_TOKEN_INVALIDATION",
                severity="HIGH",
                endpoint=probe_url,
                evidence={
                    "message": (
                        "The token/cookie captured before logout still authenticates "
                        "after logout — sessions are not invalidated server-side"
                    ),
                    "replay_status": resp.status_code,
                    "credential_type": "bearer" if token else "cookie",
                },
                confidence=0.85,
            )

    def check_token_in_url(self):
        """Detect JWTs/session tokens placed in query strings."""
        base_response = getattr(self, "_base_response", None)
        texts = [base_response.text or ""] if base_response else []
        texts.extend(self.discovered_urls[:25])
        pattern = re.compile(
            r"[?&](?:token|access_token|jwt|id_token|auth|session)="
            r"(?:eyJ[A-Za-z0-9._-]{10,}|[A-Za-z0-9._-]{16,})",
            re.I,
        )
        for text in texts:
            match = pattern.search(text or "")
            if not match:
                continue
            self._add_finding(
                finding_type="TOKEN_IN_URL",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "message": (
                        "A session token appears in a URL query string — it leaks "
                        "through logs, Referer headers and browser history"
                    ),
                    "snippet": self._redact_for_llm(match.group(0))[:120],
                },
                confidence=0.8,
            )
            return

    def check_predictable_identifiers(self):
        """Detect predictable object IDs via entropy analysis of sequential requests."""
        import math as _math
        from collections import Counter as _Counter

        # Find URLs with numeric ID patterns
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        id_pattern = r"(?:/(\d{3,})(?:\?|/|$))"
        candidate_ids = re.findall(id_pattern, resp.text)
        if not candidate_ids:
            return

        # Make sequential requests and extract new IDs
        all_ids = [int(x) for x in set(candidate_ids)]
        for _ in range(4):
            next_url = self.target_url
            if all_ids:
                next_url = f"{self.target_url}?id={all_ids[-1] + 1}"
            r = self._safe_request("GET", next_url)
            if r:
                new_ids = [int(x) for x in re.findall(id_pattern, r.text)]
                all_ids.extend(new_ids)

        if len(all_ids) < 8:
            return

        # Sort IDs — entropy is computed on gaps between consecutive sorted values
        all_ids = sorted(set(all_ids))

        # Shannon entropy calculation
        counter = _Counter()
        for i in range(len(all_ids) - 1):
            counter[all_ids[i + 1] - all_ids[i]] += 1

        total = sum(counter.values())
        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * _math.log2(p)

        # Low entropy in gaps = sequential/predictable IDs
        if entropy < 2.0 and len(all_ids) >= 8:
            self._add_finding(
                finding_type="PREDICTABLE_IDENTIFIERS",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "sample_ids": sorted(set(all_ids))[:10],
                    "id_gaps": dict(counter.most_common(5)),
                    "entropy": round(entropy, 2),
                    "message": f"Object IDs have low entropy ({entropy:.1f}) — likely sequential or predictable",
                },
                confidence=0.7,
            )

    def check_jwt_algorithm_confusion(self):
        """Check for JWT algorithm confusion vulnerabilities."""
        jwt_pattern = r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        jwts = re.findall(jwt_pattern, resp.text)
        # Check JS files for JWTs
        js_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', resp.text)
        for js_url in js_urls[:5]:
            if not js_url.startswith("http"):
                js_url = urljoin(self.target_url, js_url)
            js_resp = self._safe_request("GET", js_url)
            if js_resp and js_resp.status_code == 200:
                jwts.extend(re.findall(jwt_pattern, js_resp.text))

        jwts = list(set(jwts))[:3]  # Deduplicate, limit to 3
        for jwt_token in jwts:
            finding = test_jwt_alg_none(
                jwt_token=jwt_token,
                target_url=self.target_url,
                request_func=lambda url, headers: self._safe_request(
                    "GET", url, headers=headers
                ),
            )
            if finding:
                self._add_finding(
                    finding_type=finding["type"],
                    severity=finding["severity"],
                    endpoint=finding["endpoint"],
                    evidence=finding["evidence"],
                    confidence=finding["confidence"],
                )
                return

    def check_prototype_pollution(self):
        """Check for prototype pollution by comparing against a baseline.

        A page that merely contains the word "true" is not prototype
        pollution. The old check fired on any 200 whose body contained
        "true" or "isAdmin", so every ordinary page looked vulnerable:
        on www.hisdayspringfamily.org the payload URL returned a body
        byte-identical to the baseline and still produced a finding.

        The payload response now has to show a marker the baseline does not:
        the property the payload sets, as a merged object would render it.
        """
        baseline = self._safe_request("GET", self.target_url)
        if not baseline or baseline.status_code != 200:
            return

        baseline_text = baseline.text or ""
        baseline_markers = self._prototype_markers_in(baseline_text)
        baseline_digest = hashlib.sha256(
            baseline_text.encode("utf-8", errors="ignore")
        ).hexdigest()

        for payload in self.PROTOTYPE_POLLUTION_PAYLOADS:
            test_url = f"{self.target_url}{payload}"
            resp = self._safe_request("GET", test_url)
            if not resp or resp.status_code != 200:
                continue

            body = resp.text or ""
            new_markers = self._prototype_markers_in(body) - baseline_markers
            if body == baseline_text or not new_markers:
                logger.debug(
                    "Prototype pollution payload %s changed nothing observable; "
                    "no differential marker between baseline and payload response",
                    payload,
                )
                continue

            self._add_finding(
                finding_type="PROTOTYPE_POLLUTION",
                severity="MEDIUM",
                endpoint=test_url,
                evidence={
                    "payload": payload,
                    "response_status": resp.status_code,
                    "markers": sorted(new_markers),
                    "baseline_body_sha256": baseline_digest,
                    "payload_body_sha256": hashlib.sha256(
                        body.encode("utf-8", errors="ignore")
                    ).hexdigest(),
                    "message": (
                        "Payload-derived property appears in the response but "
                        "not in the unmodified baseline"
                    ),
                },
                confidence=0.75,
                response=resp,
            )
            break

    @staticmethod
    def _prototype_markers_in(text: str) -> set[str]:
        """Return the prototype-pollution markers present in a body."""
        lowered = " ".join(text.lower().split())
        return {m for m in _PROTOTYPE_POLLUTION_MARKERS if m in lowered}

    def check_cache_poisoning(self):
        """Check for cache poisoning vulnerabilities."""
        resp = self._safe_request(
            "GET", self.target_url, headers=self.CACHE_POISONING_HEADERS
        )
        if not resp:
            return

        # Check if response is cacheable
        cache_control = resp.headers.get("Cache-Control", "")
        expires = resp.headers.get("Expires", "")
        if not cache_control and not expires:
            return

        if "127.0.0.1" in resp.text:
            self._add_finding(
                finding_type="CACHE_POISONING",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "headers_sent": self.CACHE_POISONING_HEADERS,
                    "response_preview": resp.text[:200],
                    "message": "Cacheable response includes poisoned headers",
                },
                confidence=0.7,
            )

    def check_http_request_smuggling(self):
        """Check for HTTP request smuggling (CL.TE and TE.CL).

        L-29: Only 502 Bad Gateway is a reliable indicator of actual
        request smuggling (desync). A 400 Bad Request is the expected
        response for conflicting headers — most servers reject malformed
        requests gracefully. We still flag 500/504 at lower confidence
        but exclude 400 to reduce false positives.
        """
        # CL.TE Test
        cl_te_headers = {"Content-Length": "6", "Transfer-Encoding": "chunked"}
        resp = self._safe_request(
            "POST", self.target_url, headers=cl_te_headers, data="0\r\n\r\n"
        )
        if resp:
            if resp.status_code == 502:
                self._add_finding(
                    finding_type="HTTP_REQUEST_SMUGGLING_CL_TE",
                    severity="HIGH",
                    endpoint=self.target_url,
                    evidence={
                        "technique": "CL.TE",
                        "status_code": resp.status_code,
                        "message": "Likely CL.TE desync — 502 Bad Gateway with conflicting headers",
                    },
                    confidence=0.85,
                )
            elif resp.status_code in (500, 504):
                self._add_finding(
                    finding_type="HTTP_REQUEST_SMUGGLING_CL_TE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "technique": "CL.TE",
                        "status_code": resp.status_code,
                        "message": "Possible CL.TE desync (inconclusive — 500/504 can have other causes)",
                    },
                    confidence=0.4,
                )

        # TE.CL Test
        te_cl_headers = {"Transfer-Encoding": "chunked", "Content-Length": "6"}
        resp = self._safe_request(
            "POST", self.target_url, headers=te_cl_headers, data="0\r\n\r\n"
        )
        if resp:
            if resp.status_code == 502:
                self._add_finding(
                    finding_type="HTTP_REQUEST_SMUGGLING_TE_CL",
                    severity="HIGH",
                    endpoint=self.target_url,
                    evidence={
                        "technique": "TE.CL",
                        "status_code": resp.status_code,
                        "message": "Likely TE.CL desync — 502 Bad Gateway with conflicting headers",
                    },
                    confidence=0.85,
                )
            elif resp.status_code in (500, 504):
                self._add_finding(
                    finding_type="HTTP_REQUEST_SMUGGLING_TE_CL",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "technique": "TE.CL",
                        "status_code": resp.status_code,
                        "message": "Possible TE.CL desync (inconclusive — 500/504 can have other causes)",
                    },
                    confidence=0.4,
                )

        # R-10: TE.TE variant — both headers present with obfuscated
        # Transfer-Encoding. Some backends only parse one header and
        # ignore the other, creating a desync opportunity.
        te_te_headers = {
            "Transfer-Encoding": "chunked",
            "Transfer-encoding": "cow",
        }
        resp = self._safe_request(
            "POST", self.target_url, headers=te_te_headers, data="0\r\n\r\n"
        )
        if resp:
            if resp.status_code == 502:
                self._add_finding(
                    finding_type="HTTP_REQUEST_SMUGGLING_TE_TE",
                    severity="HIGH",
                    endpoint=self.target_url,
                    evidence={
                        "technique": "TE.TE",
                        "status_code": resp.status_code,
                        "message": "Likely TE.TE desync — 502 with obfuscated Transfer-Encoding",
                    },
                    confidence=0.8,
                )
            elif resp.status_code in (500, 504):
                self._add_finding(
                    finding_type="HTTP_REQUEST_SMUGGLING_TE_TE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "technique": "TE.TE",
                        "status_code": resp.status_code,
                        "message": "Possible TE.TE desync (inconclusive)",
                    },
                    confidence=0.35,
                )

    def check_dom_xss(self):
        """Check for DOM-based XSS with source/sink taint heuristic.

        R-09: Instead of just checking for sink presence and payload
        reflection, this now identifies DOM sources (where attacker data
        enters the page) and checks if they flow to dangerous sinks.
        """
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        body = resp.text

        # DOM sources — where attacker-controlled data enters the page
        dom_sources = [
            "document.location",
            "location.href",
            "location.search",
            "location.hash",
            "window.name",
            "document.referrer",
            "document.URL",
            "document.documentURI",
            "location.origin",
            "location.pathname",
        ]
        # DOM sinks — where data is rendered/executed unsafely
        dom_sinks = [
            "document.write",
            "innerHTML",
            "outerHTML",
            "eval(",
            "setTimeout(",
            "setInterval(",
            "document.createElement",
            ".src =",
            ".href =",
            "$.html(",
            "$.append(",
        ]

        found_sources = [s for s in dom_sources if s in body]
        found_sink_actual = [s for s in dom_sinks if s in body]

        # Need both a source AND a sink for a real DOM XSS risk.
        # If neither sources nor sinks found, check for reflection-based DOM XSS.
        if (not found_sources or not found_sink_actual) and not any(
            s in body for s in ["location", "hash", "search"]
        ):
            return

        # Test payloads targeting the specific source→sink path
        llm_payloads = []
        if self.llm_payload_generator and self.llm_payload_generator.is_available():
            llm_payloads = self.llm_payload_generator.generate_sync(
                vuln_class="DOM_XSS",
                param_name="q",
                response_snippet=self._redact_for_llm(body) if resp else "",
                framework_hints=self._tech_hints(resp),
            )

        dom_payloads = [
            "<img src=x onerror=alert(1)>",
            "<script>alert(1)</script>",
            "'-alert(1)-'",
            '"><img src=x onerror=alert(1)>',
        ] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]

        for payload in dom_payloads:
            test_url = f"{self.target_url}?q={payload}"
            test_resp = self._safe_request("GET", test_url)
            if not test_resp or payload not in test_resp.text:
                continue

            # Verify a sink exists in the page with the payload nearby
            test_body = test_resp.text
            has_sink_near_payload = False
            for sink in dom_sinks:
                if sink in test_body:
                    has_sink_near_payload = True
                    break

            self._add_finding(
                finding_type="DOM_XSS",
                severity="HIGH" if has_sink_near_payload else "MEDIUM",
                endpoint=test_url,
                evidence={
                    "payload": payload,
                    "reflected": True,
                    "dom_sources_found": found_sources[:5],
                    "dom_sinks_found": found_sink_actual[:5],
                    "sink_near_payload": has_sink_near_payload,
                    "message": (
                        f"Payload reflected; DOM sources ({', '.join(found_sources[:3])}) "
                        f"and sinks ({', '.join(found_sink_actual[:3])}) both present"
                    ),
                },
                confidence=0.8 if has_sink_near_payload else 0.6,
            )
            break

    def check_openapi_discovery(self):
        """Check for exposed OpenAPI/Swagger specifications."""
        for path in self.OPENAPI_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue

            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type:
                continue

            try:
                spec = resp.json()
                if "openapi" in spec or "swagger" in spec or "paths" in spec:
                    endpoints = list(spec.get("paths", {}).keys())[:10]
                    self._add_finding(
                        finding_type="OPENAPI_SPEC_EXPOSED",
                        severity="MEDIUM",
                        endpoint=url,
                        evidence={
                            "spec_type": "openapi" if "openapi" in spec else "swagger",
                            "endpoints_exposed": endpoints,
                            "spec_preview": json.dumps(spec)[:200],
                        },
                        confidence=0.9,
                    )
                    break
            except json.JSONDecodeError:
                pass

    def differential_analysis(self):
        """
        Compare baseline response against modified requests to detect
        anomalies, parameter pollution, and method override issues.

        Sends variations of the baseline request (method override headers,
        parameter pollution, null byte injection, large content length) and
        flags responses that differ significantly in status code, body length,
        or response time.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running differential analysis")

        # Establish baseline
        baseline = self._safe_request("GET", self.target_url)
        if not baseline:
            return

        baseline_status = baseline.status_code
        baseline_len = len(baseline.text)
        baseline_time = baseline.elapsed.total_seconds()

        # Test cases: method override, parameter pollution, header anomalies
        test_cases = [
            {
                "name": "method_override_get",
                "method": "POST",
                "url": self.target_url,
                "headers": {"X-HTTP-Method-Override": "GET"},
                "data": "",
            },
            {
                "name": "method_override_delete",
                "method": "POST",
                "url": self.target_url,
                "headers": {"X-HTTP-Method-Override": "DELETE"},
                "data": "",
            },
            {
                "name": "parameter_pollution",
                "method": "GET",
                "url": f"{self.target_url}?id=1&id=2&id=3",
                "headers": {},
            },
            {
                "name": "null_byte_injection",
                "method": "GET",
                "url": f"{self.target_url}?file=test.txt%00.jpg",
                "headers": {},
            },
            {
                "name": "large_content_length",
                "method": "POST",
                "url": self.target_url,
                "headers": {"Content-Length": "999999999"},
                "data": "x",
            },
        ]

        for test in test_cases:
            try:
                kwargs = {
                    "headers": test.get("headers", {}),
                }
                if "data" in test:
                    kwargs["data"] = test["data"]

                resp = self._safe_request(test["method"], test["url"], **kwargs)
                if not resp:
                    continue

                status_diff = resp.status_code != baseline_status
                len_diff = abs(len(resp.text) - baseline_len) > 100
                time_diff = abs(resp.elapsed.total_seconds() - baseline_time) > 2

                if status_diff or len_diff or time_diff:
                    self._add_finding(
                        finding_type="DIFFERENTIAL_ANOMALY",
                        severity="MEDIUM",
                        endpoint=test["url"],
                        evidence={
                            "test_name": test["name"],
                            "baseline_status": baseline_status,
                            "modified_status": resp.status_code,
                            "baseline_length": baseline_len,
                            "modified_length": len(resp.text),
                            "baseline_time": baseline_time,
                            "modified_time": resp.elapsed.total_seconds(),
                            "headers_sent": test.get("headers", {}),
                        },
                        confidence=0.6,
                    )
            except Exception as e:
                logger.debug("Differential test failed: %s", e)

    def detect_waf(self):
        """
        Detect Web Application Firewalls (WAF) and identify their vendor type.

        Sends trigger payloads that WAFs typically block, then inspects
        response headers and body for known WAF signatures (Cloudflare,
        AWS WAF, ModSecurity, Akamai, Sucuri, Imperva, F5 BIG-IP).

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running WAF detection")

        # Trigger payloads that WAFs typically block
        trigger_payloads = [
            "' OR 1=1--",
            "<script>alert(1)</script>",
            "../../etc/passwd",
            " UNION SELECT * FROM users--",
        ]

        waf_signatures = {
            "Cloudflare": [
                ("header", "cf-ray"),
                ("header", "cloudflare"),
                ("body", "cloudflare"),
            ],
            "AWS WAF": [
                ("header", "x-amzn-requestid"),
                ("body", "aws"),
            ],
            "ModSecurity": [
                ("body", "mod_security"),
                ("body", "not acceptable"),
                ("status", 406),
            ],
            "Akamai": [
                ("header", "akamai"),
                ("body", "akamaighost"),
            ],
            "Sucuri": [
                ("header", "x-sucuri"),
                ("body", "sucuri"),
            ],
            "Imperva": [
                ("header", "x-iinfo"),
                ("body", "incapsula"),
            ],
            "F5 BIG-IP": [
                ("header", "x-waf-event-info"),
                ("body", "f5"),
            ],
        }

        detected_wafs = set()
        waf_response = None

        for payload in trigger_payloads:
            test_url = f"{self.target_url}?test={payload}"
            resp = self._safe_request("GET", test_url)
            if not resp:
                continue

            # WAF typically blocks with 403, 406, 419, 423
            if resp.status_code in (403, 406, 419, 423, 501):
                waf_response = resp
                break

        if not waf_response:
            # Also check normal response for WAF headers
            resp = self._safe_request("GET", self.target_url)
            if resp:
                waf_response = resp

        if not waf_response:
            return

        # Check signatures
        headers_str = str(waf_response.headers).lower()
        body_str = waf_response.text.lower()

        for waf_name, signatures in waf_signatures.items():
            for sig_type, sig_value in signatures:
                sig_value_lower = str(sig_value).lower()
                matched = (
                    (sig_type == "header" and sig_value_lower in headers_str)
                    or (sig_type == "body" and sig_value_lower in body_str)
                    or (sig_type == "status" and waf_response.status_code == sig_value)
                )
                if matched:
                    detected_wafs.add(waf_name)

        if detected_wafs:
            self._add_finding(
                finding_type="WAF_DETECTED",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "waf_types": list(detected_wafs),
                    "trigger_status": waf_response.status_code,
                    "response_headers": dict(waf_response.headers),
                },
                confidence=0.8,
            )
        elif waf_response.status_code in (403, 406, 419, 423):
            self._add_finding(
                finding_type="WAF_DETECTED",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "waf_types": ["Unknown"],
                    "trigger_status": waf_response.status_code,
                    "message": "Blocking behavior detected but WAF type not identified",
                },
                confidence=0.5,
            )

    def time_based_detection(self):
        """
        Detect time-based vulnerabilities using deliberate timing delays.

        Tests for blind SQL injection (MySQL, PostgreSQL, MSSQL, SQLite,
        Oracle), command injection, and blind XXE by measuring whether
        the response time exceeds a threshold after injecting delay
        payloads.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running time-based vulnerability detection")

        delay_seconds = 5
        threshold = delay_seconds * 0.8  # Allow 80% of delay to account for variance

        # SQL injection time-based payloads
        sqli_payloads = [
            ("mysql", f"' OR SLEEP({delay_seconds})--"),
            ("mysql_alt", f"'; SELECT SLEEP({delay_seconds})--"),
            ("postgres", f"'; SELECT pg_sleep({delay_seconds})--"),
            ("mssql", f"'; WAITFOR DELAY '0:0:{delay_seconds}'--"),
            ("sqlite", f"' AND randomblob({delay_seconds}00000000)--"),
            ("oracle", f"' AND 1=DBMS_PIPE.RECEIVE_MESSAGE('RDS',{delay_seconds})--"),
        ]

        # Command injection time-based payloads
        cmdi_payloads = [
            ("; sleep", f"; sleep {delay_seconds}"),
            ("| sleep", f"| sleep {delay_seconds}"),
            ("&& sleep", f"&& sleep {delay_seconds}"),
            ("`sleep", f"`sleep {delay_seconds}`"),
            ("$(sleep", f"$(sleep {delay_seconds})"),
        ]

        # Test SQL injection
        for db_type, payload in sqli_payloads:
            test_url = f"{self.target_url}?id={payload}"
            start = time.time()
            self._safe_request("GET", test_url)
            elapsed = time.time() - start

            if elapsed >= threshold:
                self._add_finding(
                    finding_type="TIME_BASED_SQL_INJECTION",
                    severity="HIGH",
                    endpoint=test_url,
                    evidence={
                        "db_type_tested": db_type,
                        "payload": payload,
                        "response_time_seconds": elapsed,
                        "threshold_seconds": threshold,
                        "message": f"Response delayed by {elapsed:.1f}s suggests time-based SQL injection",
                    },
                    confidence=0.7,
                )
                break  # Found one, likely enough

        # Test command injection
        for cmd_type, payload in cmdi_payloads:
            test_url = f"{self.target_url}?input={payload}"
            start = time.time()
            self._safe_request("GET", test_url)
            elapsed = time.time() - start

            if elapsed >= threshold:
                self._add_finding(
                    finding_type="TIME_BASED_COMMAND_INJECTION",
                    severity="HIGH",
                    endpoint=test_url,
                    evidence={
                        "payload_type": cmd_type,
                        "payload": payload,
                        "response_time_seconds": elapsed,
                        "threshold_seconds": threshold,
                        "message": f"Response delayed by {elapsed:.1f}s suggests command injection",
                    },
                    confidence=0.7,
                )
                break

        # Blind XXE time-based test
        xxe_payload = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE foo [
          <!ENTITY xxe SYSTEM "http://127.0.0.1:9999/xxe">
        ]>
        <foo>&xxe;</foo>"""

        start = time.time()
        self._safe_request(
            "POST",
            self.target_url,
            data=xxe_payload,
            headers={"Content-Type": "application/xml"},
        )
        elapsed = time.time() - start

        if elapsed >= threshold:
            self._add_finding(
                finding_type="BLIND_XXE",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "payload": xxe_payload[:100],
                    "response_time_seconds": elapsed,
                    "threshold_seconds": threshold,
                    "message": "Long response time may indicate OOB XXE resolution attempt",
                },
                confidence=0.4,
            )

    def ssl_verify(self):
        """
        Verify SSL/TLS certificate and server-side configuration.

        Checks for HTTPS usage, certificate expiry, self-signed certificates,
        weak TLS versions (SSLv3, TLSv1, TLSv1.1), and weak cipher suites.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running SSL/TLS verification")

        import ssl

        parsed = urlparse(self.target_url)
        hostname = parsed.hostname
        port = parsed.port or 443

        if not hostname:
            return

        if parsed.scheme != "https":
            self._add_finding(
                finding_type="NO_HTTPS",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "scheme": parsed.scheme,
                    "message": "Target does not use HTTPS",
                },
                confidence=0.95,
            )
            return

        context = ssl.create_default_context()
        sock = None
        ssock = None

        try:
            sock = socket.create_connection((hostname, port), timeout=self.timeout)
            ssock = context.wrap_socket(sock, server_hostname=hostname)

            try:
                cert = ssock.getpeercert()
            except (ValueError, ssl.SSLError):
                cert = None
            cipher = ssock.cipher()
            version = ssock.version()

            # Check certificate expiry
            if cert:
                not_after = cert.get("notAfter")
                if not_after:
                    expiry = ssl.cert_time_to_seconds(not_after)
                    if expiry < time.time():
                        self._add_finding(
                            finding_type="EXPIRED_SSL_CERTIFICATE",
                            severity="HIGH",
                            endpoint=f"{hostname}:{port}",
                            evidence={
                                "expiry_date": not_after,
                                "subject": cert.get("subject"),
                            },
                            confidence=0.95,
                        )

                # Check if self-signed
                issuer = cert.get("issuer")
                subject = cert.get("subject")
                if issuer == subject:
                    self._add_finding(
                        finding_type="SELF_SIGNED_CERTIFICATE",
                        severity="MEDIUM",
                        endpoint=f"{hostname}:{port}",
                        evidence={
                            "issuer": issuer,
                            "subject": subject,
                        },
                        confidence=0.9,
                    )

            # Check TLS version
            weak_versions = ["SSLv3", "TLSv1", "TLSv1.1"]
            if version in weak_versions:
                self._add_finding(
                    finding_type="WEAK_TLS_VERSION",
                    severity="HIGH",
                    endpoint=f"{hostname}:{port}",
                    evidence={
                        "tls_version": version,
                        "message": f"{version} is deprecated and insecure",
                    },
                    confidence=0.95,
                )

            # Check cipher strength
            if cipher:
                cipher_name = cipher[0]
                weak_ciphers = [
                    "RC4",
                    "DES",
                    "3DES",
                    "MD5",
                    "NULL",
                    "EXPORT",
                    "anon",
                    "CBC",
                ]
                if any(wc in cipher_name for wc in weak_ciphers):
                    self._add_finding(
                        finding_type="WEAK_SSL_CIPHER",
                        severity="HIGH",
                        endpoint=f"{hostname}:{port}",
                        evidence={
                            "cipher": cipher_name,
                            "message": f"Weak cipher detected: {cipher_name}",
                        },
                        confidence=0.85,
                    )

        except ssl.SSLError as e:
            self._add_finding(
                finding_type="SSL_ERROR",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "error": str(e),
                    "message": "SSL/TLS handshake failed",
                },
                confidence=0.8,
            )
        except OSError as e:
            logger.debug("SSL verification socket error: %s", e)
        except Exception as e:
            logger.debug("SSL verification error: %s", e)
        finally:
            if ssock:
                with contextlib.suppress(Exception):
                    ssock.close()
            if sock:
                with contextlib.suppress(Exception):
                    sock.close()

    def response_analysis(self):
        """
        Analyze HTTP responses for information leakage and debug exposure.

        Detects server version headers, framework leaks (X-Powered-By,
        X-AspNet-Version), stack traces, internal IP addresses, email
        addresses, and debug mode indicators in response content.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running response analysis")

        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Server information disclosure
        server_header = resp.headers.get("Server", "")
        powered_by = resp.headers.get("X-Powered-By", "")
        asp_version = resp.headers.get("X-AspNet-Version", "")
        asp_mvc = resp.headers.get("X-AspNetMvc-Version", "")

        if server_header:
            self._add_finding(
                finding_type="SERVER_INFO_DISCLOSURE",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "header": "Server",
                    "value": server_header,
                    "message": "Server software version exposed",
                },
                confidence=0.9,
            )

        if powered_by:
            self._add_finding(
                finding_type="FRAMEWORK_VERSION_LEAK",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "header": "X-Powered-By",
                    "value": powered_by,
                    "message": "Framework version exposed",
                },
                confidence=0.9,
            )

        if asp_version or asp_mvc:
            self._add_finding(
                finding_type="FRAMEWORK_VERSION_LEAK",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "headers": {
                        "X-AspNet-Version": asp_version,
                        "X-AspNetMvc-Version": asp_mvc,
                    },
                    "message": "ASP.NET version information exposed",
                },
                confidence=0.9,
            )

        # Stack trace detection
        stack_patterns = [
            r"Traceback \(most recent call last\)",
            r"at [\w\.]+\.[\w]+\([^)]*\)",
            r"Exception in thread",
            r"Fatal error:",
            r"PHP Stack trace:",
            r"in /[\w/]+ on line \d+",
        ]

        for pattern in stack_patterns:
            match = re.search(pattern, resp.text, re.IGNORECASE)
            if match:
                snippet = resp.text[max(0, match.start() - 100) : match.end() + 200]
                self._add_finding(
                    finding_type="STACK_TRACE_EXPOSURE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "pattern_matched": pattern,
                        "snippet": snippet,
                        "message": "Stack trace or debug information exposed in response",
                    },
                    confidence=0.8,
                )
                break

        # Internal IP disclosure
        internal_ip_pattern = r"(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})"
        internal_ips = re.findall(internal_ip_pattern, resp.text)
        if internal_ips:
            self._add_finding(
                finding_type="INTERNAL_IP_DISCLOSURE",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "internal_ips_found": list(set(internal_ips)),
                    "message": "Internal IP addresses exposed in response",
                },
                confidence=0.8,
            )

        # Email address disclosure
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        emails = re.findall(email_pattern, resp.text)
        if emails:
            self._add_finding(
                finding_type="EMAIL_DISCLOSURE",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "emails_found": list(set(emails))[:10],
                    "count": len(set(emails)),
                    "message": "Email addresses exposed in response",
                },
                confidence=0.7,
            )

        # Debug mode detection
        debug_indicators = [
            "DEBUG = True",
            "debug mode",
            "debug toolbar",
            "flask-debug",
            "django-debug",
        ]
        for indicator in debug_indicators:
            if indicator.lower() in resp.text.lower():
                self._add_finding(
                    finding_type="DEBUG_MODE_ENABLED",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "indicator": indicator,
                        "message": "Debug mode may be enabled",
                    },
                    confidence=0.7,
                )
                break

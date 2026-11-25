"""
Deterministic canonical asset identity for the asset graph (A2).

Agents submit observations; they never invent canonical IDs. This module turns a
raw observed value into one canonical identity per asset type, so the same asset
reported by two tools (or with different case, default ports or trailing slashes)
lands on a single ``graph_assets`` row.

Supported types: ``root_domain``, ``subdomain``, ``ip``, ``service``, ``app`` and
``endpoint``. Parent relationships are computed here rather than in SQL so every
caller derives the same parent chain.
"""

from __future__ import annotations

import ipaddress
import json
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

ROOT_DOMAIN = "root_domain"
SUBDOMAIN = "subdomain"
IP = "ip"
SERVICE = "service"
APP = "app"
ENDPOINT = "endpoint"

ASSET_TYPES = frozenset({ROOT_DOMAIN, SUBDOMAIN, IP, SERVICE, APP, ENDPOINT})

_URL_SCHEMES = {"http": 80, "https": 443, "ws": 80, "wss": 443}
_DEFAULT_SERVICE_PROTOCOL = "tcp"
_MAX_PORT = 65535


class AssetIdentityError(ValueError):
    """An observed value cannot be canonicalized into an asset identity."""


@dataclass(frozen=True)
class ParentIdentity:
    """The parent asset an identity hangs off, if any."""

    asset_type: str
    canonical_key: str


@dataclass(frozen=True)
class CanonicalIdentity:
    """One canonical asset identity derived from a raw observation."""

    asset_type: str
    canonical_key: str
    display_value: str
    parent: ParentIdentity | None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def normalize_hostname(value: str) -> str:
    """
    Normalize a hostname: Unicode NFKC, lower case, no trailing dot, IDNA ASCII.

    Brackets around an IPv6 literal are stripped so ``[::1]`` and ``::1`` are the
    same host.
    """
    if not isinstance(value, str):
        raise AssetIdentityError("hostname must be a string")
    host = unicodedata.normalize("NFKC", value.strip())
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = host.rstrip(".").lower()
    if not host:
        raise AssetIdentityError("hostname is empty")
    if any(ord(char) > 127 for char in host):
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise AssetIdentityError(
                f"hostname {value!r} is not a valid IDNA name"
            ) from exc
    if any(char in host for char in " /?#@\\"):
        raise AssetIdentityError(f"hostname {value!r} contains invalid characters")
    return host


def normalize_ip(value: str) -> str:
    """Return the compressed canonical form of an IPv4/IPv6 address."""
    if not isinstance(value, str):
        raise AssetIdentityError("IP address must be a string")
    candidate = value.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError as exc:
        raise AssetIdentityError(f"{value!r} is not an IP address") from exc


def _canonical_url(value: str) -> tuple[str, str]:
    """
    Canonicalize a URL without losing path/query semantics.

    Lower-cases the scheme and host, strips userinfo, drops default ports and
    normalizes an empty path. Returns ``(canonical_url, host)``.
    """
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    if scheme not in _URL_SCHEMES:
        raise AssetIdentityError(
            f"unsupported URL scheme {scheme or '(none)'!r}; expected one of "
            + ", ".join(sorted(_URL_SCHEMES))
        )
    host = normalize_hostname(parts.hostname or "")
    try:
        port = parts.port
    except ValueError as exc:
        raise AssetIdentityError(f"URL {value!r} has an invalid port") from exc
    if port == _URL_SCHEMES[scheme]:
        port = None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    # A-01 requires trailing-slash variants of one URL to be one identity, so
    # normalize trailing slashes on any path (not just the empty root path).
    path = parts.path.rstrip("/")
    canonical = f"{scheme}://{netloc}{path}"
    if parts.query:
        canonical = f"{canonical}?{parts.query}"
    return canonical, host


def _canonical_service(value: str) -> tuple[str, str]:
    """
    Canonicalize a service identity as ``protocol://host:port``.

    IPv6 hosts must be bracketed (``[2001:db8::1]:443``) and stay bracketed in
    the canonical key. An unbracketed IPv6 address is ambiguous with
    ``host:port`` (``2001:db8::443`` could be a host or a host plus port 443), so
    it is rejected rather than guessed.
    """
    text = value.strip()
    protocol = _DEFAULT_SERVICE_PROTOCOL
    if "://" in text:
        protocol, text = text.split("://", 1)
        protocol = protocol.lower()
    if "/" in text:
        text, protocol = text.rsplit("/", 1)
        protocol = protocol.lower()

    if text.startswith("["):
        closing = text.find("]")
        if closing == -1:
            raise AssetIdentityError(f"service identity {value!r} has an unclosed IPv6 bracket")
        host_text = text[1:closing]
        remainder = text[closing + 1 :]
        if not remainder.startswith(":"):
            raise AssetIdentityError("service identity requires host:port")
        port = remainder[1:]
    else:
        host_text, separator, port = text.rpartition(":")
        if not separator:
            raise AssetIdentityError("service identity requires host:port")
        if ":" in host_text:
            raise AssetIdentityError(
                f"IPv6 service host in {value!r} must be bracketed, e.g. [2001:db8::1]:443"
            )

    host = normalize_hostname(host_text)
    if not port.isdigit():
        raise AssetIdentityError(f"service port {port!r} is not numeric")
    port_number = int(port)
    if not 0 < port_number <= _MAX_PORT:
        raise AssetIdentityError(f"service port {port!r} is out of range")
    if not protocol.isalnum():
        raise AssetIdentityError(f"service protocol {protocol!r} is invalid")
    netloc = f"[{host}]" if ":" in host else host
    return f"{protocol}://{netloc}:{port_number}", host


def root_domain_of(host: str) -> str | None:
    """Best-effort root domain (last two labels) for a normalized hostname."""
    labels = host.split(".")
    if len(labels) < 2:
        return None
    return ".".join(labels[-2:])


def _parent_for_host(host: str) -> ParentIdentity | None:
    if _is_ip(host):
        return ParentIdentity(IP, str(ipaddress.ip_address(host)))
    root = root_domain_of(host)
    if root is None:
        return None
    if root == host:
        return ParentIdentity(ROOT_DOMAIN, host)
    return ParentIdentity(SUBDOMAIN, host)


def canonicalize_asset(asset_type: str, value: str) -> CanonicalIdentity:
    """
    Canonicalize one observed value into a deterministic asset identity.

    Raises:
        AssetIdentityError: when the type is unknown or the value cannot be
            canonicalized (never invent a key from an unusable observation).
    """
    if not isinstance(asset_type, str) or not asset_type.strip():
        raise AssetIdentityError("asset_type is required")
    normalized_type = asset_type.strip().lower()
    if normalized_type not in ASSET_TYPES:
        raise AssetIdentityError(
            f"unknown asset type {asset_type!r}; expected one of "
            + ", ".join(sorted(ASSET_TYPES))
        )
    if not isinstance(value, str) or not value.strip():
        raise AssetIdentityError("observed value is required")

    raw = value.strip()

    if normalized_type == ENDPOINT:
        key, host = _canonical_url(raw)
        return CanonicalIdentity(ENDPOINT, key, key, _parent_for_host(host))

    if normalized_type == IP:
        key = normalize_ip(raw)
        return CanonicalIdentity(IP, key, key, None)

    if normalized_type == SERVICE:
        key, host = _canonical_service(raw)
        return CanonicalIdentity(SERVICE, key, key, _parent_for_host(host))

    if normalized_type == APP:
        if "://" in raw:
            key, host = _canonical_url(raw)
            return CanonicalIdentity(APP, key, key, _parent_for_host(host))
        host = normalize_hostname(raw)
        return CanonicalIdentity(APP, host, host, _parent_for_host(host))

    host = normalize_hostname(raw)
    if _is_ip(host):
        raise AssetIdentityError(f"{normalized_type} cannot be an IP address")
    if normalized_type == ROOT_DOMAIN:
        return CanonicalIdentity(ROOT_DOMAIN, host, host, None)

    root = root_domain_of(host)
    parent = ParentIdentity(ROOT_DOMAIN, root) if root and root != host else None
    return CanonicalIdentity(SUBDOMAIN, host, host, parent)


# ---------------------------------------------------------------------------
# Authorized-scope comparison (A-03)
# ---------------------------------------------------------------------------


def parse_scope(authorized_scope: dict | str | None) -> dict[str, list[str]] | None:
    """
    Parse an engagement ``authorized_scope`` into normalized domain/IP lists.

    Returns ``None`` when no scope was supplied, meaning "nothing to enforce".
    Mirrors the ``domains`` / ``ipRanges`` shape used by
    ``tools/scope_validator.py`` and the engagements table.
    """
    if authorized_scope is None:
        return None
    scope = authorized_scope
    if isinstance(scope, str):
        try:
            scope = json.loads(scope)
        except (TypeError, json.JSONDecodeError):
            scope = {}
    if not isinstance(scope, dict):
        scope = {}
    domains = [str(entry).strip().lower() for entry in scope.get("domains", []) if entry]
    ranges = [str(entry).strip() for entry in scope.get("ipRanges", []) if entry]
    return {"domains": domains, "ipRanges": ranges}


def _host_matches_domains(host: str, domains: list[str]) -> bool:
    """
    Match a host against scope domains with Argus's exact/wildcard semantics.

    Mirrors ``tools/scope_validator.ScopeValidator._matches_domain``: an entry is
    either an exact hostname or ``*.domain`` matching exactly one label. A
    wildcard never matches deeper subdomains and never matches the apex, so the
    graph cannot widen scope beyond what the executor would accept.
    """
    for entry in domains:
        pattern = entry
        if "://" in pattern:
            pattern = urlsplit(pattern).hostname or ""
        pattern = pattern.rstrip(".")
        if not pattern:
            continue
        if host == pattern:
            return True
        if pattern.startswith("*."):
            apex = pattern[2:]
            if host.endswith(f".{apex}"):
                prefix = host[: -(len(apex) + 1)]
                if prefix and "." not in prefix:
                    return True
    return False


def _host_matches_ranges(host: str, ip_ranges: list[str]) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in ip_ranges:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if address.version == network.version and address in network:
            return True
    return False


def _host_for_identity(asset_type: str, canonical_key: str) -> str:
    if asset_type in (ROOT_DOMAIN, SUBDOMAIN, APP) and "://" not in canonical_key:
        return canonical_key
    if asset_type in (ENDPOINT, APP):
        return urlsplit(canonical_key).hostname or ""
    # service keys are protocol://host:port; IPv6 hosts are bracketed, so URL
    # parsing strips the brackets and the port correctly. Older unbracketed
    # keys fall back to splitting the netloc on the last colon.
    netloc = canonical_key.split("://", 1)[-1]
    if netloc.startswith("["):
        return urlsplit(canonical_key).hostname or ""
    return netloc.rsplit(":", 1)[0]


def scope_entries(authorized_scope: dict | str | None) -> list[dict[str, str]]:
    """
    Flatten an authorized scope into comparable approved targets.

    Each entry is ``{"kind": "domain" | "ip_range", "value": ...}`` so coverage
    can report approved targets that were never discovered.
    """
    scope = parse_scope(authorized_scope)
    if scope is None:
        return []
    entries = [{"kind": "domain", "value": domain} for domain in scope["domains"]]
    entries.extend(
        {"kind": "ip_range", "value": ip_range} for ip_range in scope["ipRanges"]
    )
    return entries


def undiscovered_scope_entries(
    discovered_assets: list[dict],
    authorized_scope: dict | str | None,
) -> list[dict[str, str]]:
    """
    Approved scope entries with no matching discovered asset (coverage gaps).

    A gap means the operator approved a target but no tool ever reported anything
    inside it, which is the opposite of an untested discovered asset.
    """
    gaps: list[dict[str, str]] = []
    for entry in scope_entries(authorized_scope):
        matched = False
        for asset in discovered_assets:
            asset_type = asset["asset_type"]
            canonical_key = asset["canonical_key"]
            if entry["kind"] == "domain":
                if asset_type == IP:
                    continue
                host = _host_for_identity(asset_type, canonical_key)
                if host and _host_matches_domains(host, [entry["value"]]):
                    matched = True
                    break
            elif asset_type == IP and _host_matches_ranges(
                canonical_key, [entry["value"]]
            ):
                matched = True
                break
        if not matched:
            gaps.append(dict(entry))
    return gaps


def asset_in_scope(
    asset_type: str,
    canonical_key: str,
    authorized_scope: dict | str | None,
) -> bool:
    """
    Return True when an identity is inside the engagement's authorized scope.

    With no scope supplied there is nothing to enforce, so the answer is True.
    An empty scope (no domains and no IP ranges) is a fail-closed deny.
    """
    scope = parse_scope(authorized_scope)
    if scope is None:
        return True
    domains = scope["domains"]
    ip_ranges = scope["ipRanges"]
    if not domains and not ip_ranges:
        return False

    if asset_type == IP:
        return _host_matches_ranges(canonical_key, ip_ranges)

    host = _host_for_identity(asset_type, canonical_key)
    if not host:
        return False
    if _host_matches_domains(host, domains):
        return True
    return _host_matches_ranges(host, ip_ranges)

"""CVE Finder — NVD/CPE discovery, EPSS/KEV enrichment, applicability and chains.

This is the intelligence layer behind ``tools/vulnerability_knowledge_engine``.
It queries live vulnerability databases and returns real CVE records — never
fabricated identifiers, scores or version ranges.

Pipeline (mirrors the tool's intended execution sequence)::

    products/cve_ids → CPE identification → NVD CVE discovery →
    version-applicability analysis → EPSS/KEV enrichment → chain building

Design notes:

- All HTTP goes through :func:`_request_json`, a single seam the unit tests
  monkeypatch and the live/stub tests exercise for real. Base URLs and the
  NVD API key come from the environment (``NVD_API_BASE``, ``EPSS_API_BASE``,
  ``KEV_CATALOG_URL``, ``NVD_API_KEY``) so the Test-10 stub server can point
  the whole stack at localhost without code changes.
- NVD rate limits (5 req / 30 s without a key, 50 req / 30 s with one) are
  respected with a process-wide throttle; HTTP 429 honours ``Retry-After``
  with bounded retries and exponential backoff. ``CVE_FINDER_NO_THROTTLE=1``
  skips sleeping (unit tests, stub server).
- Results are cached per CVE ID in :mod:`cve_cache` (partial hits supported).
  NVD entries carry a 7-day TTL because NVD records are mutable upstream.
- The API key is never logged.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

import httpx

import cve_cache

logger = logging.getLogger(__name__)

# ── Endpoints and credentials (env-overridable for tests) ──

NVD_API_BASE = os.getenv("NVD_API_BASE", "https://services.nvd.nist.gov/rest/json")
EPSS_API_BASE = os.getenv("EPSS_API_BASE", "https://api.first.org/data/v1")
KEV_CATALOG_URL = os.getenv(
    "KEV_CATALOG_URL",
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
)
NVD_API_KEY = os.getenv("NVD_API_KEY", "")

REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0
_NO_THROTTLE = os.getenv("CVE_FINDER_NO_THROTTLE", "") == "1"

# NVD request spacing: 5 req / 30 s without a key, 50 req / 30 s with one.
_NVD_MIN_INTERVAL_S = 0.7 if NVD_API_KEY else 6.2
_nvd_lock = threading.Lock()
_nvd_last_call = 0.0

CVE_ID_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)

# Vendor/product alias table: well-known shorthand → canonical CPE parts.
# Matching still requires the CPE record itself to name the vendor/product;
# aliases only expand what we search for, never what we accept.
PRODUCT_ALIASES: dict[str, dict[str, str]] = {
    "log4j": {"vendor": "apache", "product": "log4j"},
    "log4j-core": {"vendor": "apache", "product": "log4j"},
    "log4j2": {"vendor": "apache", "product": "log4j"},
    "spring4shell": {"vendor": "vmware", "product": "spring_framework"},
    "spring-framework": {"vendor": "vmware", "product": "spring_framework"},
    "heartbleed": {"vendor": "openssl", "product": "openssl"},
}


# ── HTTP seam ──


def _request_json(
    url: str,
    params: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """GET *url* and return ``(status_code, parsed_json_or_None)``.

    Raises on transport failure or unparseable bodies so callers can
    distinguish failures from empty results. Never logs credentials.
    """
    headers = {"User-Agent": "Argus-Platform/1.0"}
    if NVD_API_KEY and "nvd.nist.gov" in url:
        headers["apiKey"] = NVD_API_KEY
    if extra_headers:
        headers.update(extra_headers)
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.get(url, params=params, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise CveFinderError(f"request to {url} failed: {exc}") from exc
    if response.status_code == 429:
        raise NvdRateLimited(_retry_after_s(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise CveFinderError(f"unparseable response from {url}") from exc
    if not isinstance(data, dict):
        raise CveFinderError(f"unexpected response shape from {url}")
    return response.status_code, data


def _retry_after_s(response: Any) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", "0")))
    except (TypeError, ValueError):
        return 0.0


class CveFinderError(Exception):
    """A source lookup failed (transport, rate limit, malformed data)."""


class NvdRateLimited(CveFinderError):
    """NVD answered HTTP 429. Carries the server's Retry-After hint."""

    def __init__(self, retry_after_s: float = 0.0) -> None:
        super().__init__("NVD rate limit (HTTP 429)")
        self.retry_after_s = retry_after_s


def _throttle_nvd() -> None:
    """Space NVD calls to respect the public rate limit (skippable in tests)."""
    if _NO_THROTTLE:
        return
    global _nvd_last_call
    with _nvd_lock:
        wait = _NVD_MIN_INTERVAL_S - (time.monotonic() - _nvd_last_call)
        if wait > 0:
            time.sleep(wait)
        _nvd_last_call = time.monotonic()


def _nvd_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET one NVD endpoint with retries, backoff and 429 handling."""
    url = f"{NVD_API_BASE}{path}"
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        _throttle_nvd()
        try:
            status, data = _request_json(url, params=params)
        except NvdRateLimited as exc:
            last_error = exc
            delay = min(exc.retry_after_s or BACKOFF_BASE_S * (2**attempt), 30.0)
            logger.warning("NVD rate-limited; retrying in %.1fs", delay)
            if not _NO_THROTTLE:
                time.sleep(delay)
            continue
        except CveFinderError as exc:
            last_error = exc
            if not _NO_THROTTLE:
                time.sleep(BACKOFF_BASE_S * (2**attempt))
            continue
        if status == 429:
            last_error = NvdRateLimited(0.0)
            delay = BACKOFF_BASE_S * (2**attempt)
            logger.warning("NVD rate-limited; retrying in %.1fs", delay)
            if not _NO_THROTTLE:
                time.sleep(delay)
            continue
        if 500 <= status < 600:
            last_error = CveFinderError(f"NVD answered HTTP {status}")
            if not _NO_THROTTLE:
                time.sleep(BACKOFF_BASE_S * (2**attempt))
            continue
        if status != 200 or data is None:
            raise CveFinderError(f"NVD answered HTTP {status} for {path}")
        return data
    raise CveFinderError(f"NVD request failed after {MAX_RETRIES} attempts: {last_error}")


# ── CPE identification ──


def search_cpes(keyword: str, results_per_page: int = 20) -> list[dict[str, Any]]:
    """Search the NVD CPE dictionary. Returns raw ``products`` entries."""
    data = _nvd_get(
        "/cpes/2.0", {"keywordSearch": keyword, "resultsPerPage": results_per_page}
    )
    products = data.get("products", [])
    return [p for p in products if isinstance(p, dict)]


def _cpe_parts(cpe_name: str) -> tuple[str, str, str]:
    """Split a CPE 2.3 name into (part, vendor, product), lowercased."""
    bits = cpe_name.split(":")
    part = bits[2] if len(bits) > 2 else ""
    vendor = bits[3] if len(bits) > 3 else ""
    product = bits[4] if len(bits) > 4 else ""
    return part.lower(), vendor.lower().replace("_", " "), product.lower().replace("_", " ")


def _score_cpe(cpe_name: str, vendor: str, product: str) -> float:
    """How confidently a CPE names the detected vendor/product (0..1)."""
    _, cpe_vendor, cpe_product = _cpe_parts(cpe_name)
    vendor = vendor.lower().replace("_", " ").strip()
    product = product.lower().replace("_", " ").strip()
    score = 0.0
    if cpe_vendor == vendor and vendor:
        score += 0.5
    elif vendor and (vendor in cpe_vendor or cpe_vendor in vendor):
        score += 0.25
    if cpe_product == product and product:
        score += 0.5
    elif product and (product in cpe_product or cpe_product in product):
        score += 0.25
    return score


_CPE_SAFE_CHAR = re.compile(r"[A-Za-z0-9._-]")


def _cpe_escape(value: str) -> str:
    """Escape one component for a CPE 2.3 formatted string."""
    return "".join(
        ch if _CPE_SAFE_CHAR.fullmatch(ch) else "\\" + ch for ch in value
    )


def _cpe_product_line(cpe_name: str) -> str:
    """The CPE name with version and all later fields wildcarded."""
    bits = cpe_name.split(":")
    if len(bits) < 6:
        return cpe_name
    bits[5:] = ["*"] * (len(bits) - 5)
    return ":".join(bits)


def _cpe_pin_version(cpe_name: str, version: str | None) -> str:
    """CPE match string for ``version`` (the product line when None)."""
    line = _cpe_product_line(cpe_name)
    if not version:
        return line
    bits = line.split(":")
    bits[5] = _cpe_escape(version)
    return ":".join(bits)


def identify_cpe(
    vendor: str, product: str, component: str = "", version: str | None = None
) -> dict[str, Any]:
    """Map detected vendor/product/version to an NVD CPE identifier.

    Returns ``{cpe, confidence, candidates, ambiguous}``. The CPE dictionary
    only lists concrete versions (e.g. Log4j 2.0-alpha1), so entries are
    collapsed into product lines and the detected version is pinned onto the
    best line. Trusting the dictionary's version instead would query NVD for
    the wrong release and silently miss CVEs affecting the detected one.
    Never invents a CPE: when nothing matches confidently, ``cpe`` is None
    and the caller must classify applicability as unknown/potential, not
    confirmed.
    """
    alias = PRODUCT_ALIASES.get((product or "").lower().strip())
    search_vendor = alias["vendor"] if alias else (vendor or "")
    search_product = alias["product"] if alias else (product or "")
    if component and not alias:
        search_product = component
    keyword = " ".join(t for t in (search_vendor, search_product) if t).strip()
    if not keyword:
        return {"cpe": None, "confidence": 0.0, "candidates": [], "ambiguous": True}
    try:
        entries = search_cpes(keyword)
    except CveFinderError as exc:
        raise exc
    # Aggregate the dictionary's one-entry-per-version results by product
    # line: alpha/beta/release CPEs of the same product are one candidate, not
    # competing products.
    lines: dict[str, tuple[float, bool]] = {}
    for entry in entries:
        cpe = entry.get("cpe", {})
        name = cpe.get("cpeName", "")
        if not name:
            continue
        line = _cpe_product_line(name)
        deprecated = bool(cpe.get("deprecated", False))
        score = _score_cpe(line, search_vendor, search_product)
        if deprecated:
            score *= 0.5
        previous = lines.get(line)
        if previous is None or score > previous[0] or (not deprecated and previous[1]):
            lines[line] = (score, deprecated)
    ranked = sorted(lines.items(), key=lambda item: item[1][0], reverse=True)
    candidates = [
        {"cpe": line, "confidence": round(score, 2), "deprecated": dep}
        for line, (score, dep) in ranked[:5]
    ]
    if not ranked or ranked[0][1][0] < 0.75:
        return {"cpe": None, "confidence": 0.0, "candidates": candidates, "ambiguous": True}
    top_line, (top_score, _top_deprecated) = ranked[0]
    tied = [
        line
        for line, (score, _dep) in ranked[1:3]
        if abs(score - top_score) < 1e-9 and line != top_line
    ]
    return {
        "cpe": _cpe_pin_version(top_line, version),
        "confidence": round(top_score, 2),
        "candidates": candidates,
        "ambiguous": bool(tied),
    }


# ── NVD CVE parsing ──


def lookup_cve(cve_id: str) -> dict[str, Any] | None:
    """Direct NVD lookup for one CVE ID. None when NVD has no such record."""
    cve_id = cve_id.strip().upper()
    if not CVE_ID_RE.match(cve_id):
        raise CveFinderError(f"not a CVE identifier: {cve_id!r}")
    cached = cve_cache.get_nvd_entry(cve_id)
    if cached is not None:
        return cached
    data = _nvd_get("/cves/2.0", {"cveId": cve_id})
    vulns = data.get("vulnerabilities", [])
    if not vulns:
        return None
    record = parse_cve(vulns[0].get("cve", {}))
    cve_cache.set_nvd_entry(cve_id, record)
    return record


def _cves_for_cpe(cpe_name: str, results_per_page: int) -> list[dict[str, Any]]:
    """One NVD CVE query for a CPE match string."""
    params: dict[str, Any] = {"resultsPerPage": results_per_page}
    if _criteria_version(cpe_name) is None:
        # NVD answers 404 for a wildcard version in ``cpeName``; a virtual
        # match string is the documented way to ask for a partial CPE.
        params["virtualMatchString"] = cpe_name
    else:
        params["cpeName"] = cpe_name
    data = _nvd_get("/cves/2.0", params)
    records = []
    for vuln in data.get("vulnerabilities", []):
        cve = vuln.get("cve", {})
        if cve.get("id"):
            records.append(parse_cve(cve))
    return records


def search_cves_by_cpe(cpe_name: str, results_per_page: int = 50) -> list[dict[str, Any]]:
    """All NVD CVE records applicable to a CPE name.

    A version-pinned CPE is matched by NVD against each record's affected
    version ranges, so the results are already scoped to the detected version.
    If that version is unknown upstream (or has no records), fall back to the
    product line and let local applicability analysis filter by version.
    """
    if _criteria_version(cpe_name) is None:
        return _cves_for_cpe(cpe_name, results_per_page)
    try:
        records = _cves_for_cpe(cpe_name, results_per_page)
    except CveFinderError:
        records = []
    if records:
        return records
    return _cves_for_cpe(_cpe_product_line(cpe_name), results_per_page)


def parse_cve(cve: dict[str, Any]) -> dict[str, Any]:
    """Normalise one NVD ``cve`` object into the Finder's record shape."""
    cve_id = str(cve.get("id", "")).upper()
    descriptions = cve.get("descriptions", []) or []
    description = ""
    for entry in descriptions:
        if isinstance(entry, dict) and entry.get("lang") == "en" and entry.get("value"):
            description = entry["value"]
            break
    if not description and descriptions and isinstance(descriptions[0], dict):
        description = descriptions[0].get("value", "")
    metrics = cve.get("metrics", {}) or {}
    cvss = _pick_cvss(metrics)
    weaknesses = []
    for weakness in cve.get("weaknesses", []) or []:
        for desc in weakness.get("description", []) or []:
            value = desc.get("value", "") if isinstance(desc, dict) else ""
            if value and value not in weaknesses:
                weaknesses.append(value)
    references = []
    for ref in (cve.get("references", []) or [])[:20]:
        if isinstance(ref, dict) and ref.get("url"):
            references.append(
                {"url": ref["url"], "tags": ref.get("tags", []) or []}
            )
    configurations = cve.get("configurations", []) or []
    return {
        "cve_id": cve_id,
        "description": description,
        "cvss": cvss,
        "cwe": weaknesses,
        "published": cve.get("published", ""),
        "last_modified": cve.get("lastModified", ""),
        "references": references,
        "configurations": configurations,
        "source": "nvd",
    }


def _pick_cvss(metrics: dict[str, Any]) -> dict[str, Any]:
    """Prefer CVSS v3.1, then v3.0, v4.0, v2. Missing metrics stay null."""
    for key, version in (
        ("cvssMetricV31", "3.1"),
        ("cvssMetricV30", "3.0"),
        ("cvssMetricV40", "4.0"),
        ("cvssMetricV2", "2.0"),
    ):
        entries = metrics.get(key, []) or []
        if entries and isinstance(entries[0], dict):
            data = entries[0].get("cvssData", {}) or {}
            return {
                "version": version,
                "score": data.get("baseScore"),
                "severity": (data.get("baseSeverity") or "").upper() or None,
                "vector": data.get("vectorString"),
            }
    return {"version": None, "score": None, "severity": None, "vector": None}


# ── Version comparison and applicability ──


def _version_tokens(version: str) -> list[int | str]:
    tokens: list[int | str] = []
    for chunk in re.split(r"[.\-+_~]+", version.strip()):
        if not chunk:
            continue
        tokens.append(int(chunk) if chunk.isdigit() else chunk.lower())
    return tokens


def compare_versions(left: str, right: str) -> int:
    """Compare dotted versions. -1 / 0 / 1. Unknown shapes compare as strings."""
    lt, rt = _version_tokens(left), _version_tokens(right)
    for ltok, rtok in zip(lt, rt, strict=False):
        if type(ltok) is type(rtok):
            if ltok != rtok:
                return -1 if ltok < rtok else 1
        else:
            # Numeric components sort before pre-release-style strings.
            return -1 if isinstance(ltok, int) else 1
    if len(lt) == len(rt):
        return 0
    return -1 if len(lt) < len(rt) else 1


def _in_range(
    detected: str,
    start_incl: str | None,
    start_excl: str | None,
    end_incl: str | None,
    end_excl: str | None,
) -> bool | None:
    """True inside the range, False outside, None when uncomparable."""
    try:
        if start_incl is not None and compare_versions(detected, start_incl) < 0:
            return False
        if start_excl is not None and compare_versions(detected, start_excl) <= 0:
            return False
        if end_incl is not None and compare_versions(detected, end_incl) > 0:
            return False
        if end_excl is not None and compare_versions(detected, end_excl) >= 0:
            return False
    except Exception:
        return None
    return True


def _criteria_version(criteria: str) -> str | None:
    """Exact version pinned in a CPE 2.3 string, or None for wildcards."""
    bits = criteria.split(":")
    if len(bits) < 6:
        return None
    version = bits[5]
    if version in ("*", "-", ""):
        return None
    return version


def _cpe_names_product(criteria: str, vendor: str, product: str) -> bool:
    """Does the CPE criterion name the detected vendor/product?"""
    _, cpe_vendor, cpe_product = _cpe_parts(criteria)
    vendor = vendor.lower().replace("_", " ").strip()
    product = product.lower().replace("_", " ").strip()
    vendor_ok = bool(vendor) and (
        cpe_vendor == vendor or vendor in cpe_vendor or cpe_vendor in vendor
    )
    product_ok = bool(product) and (
        cpe_product == product or product in cpe_product or cpe_product in product
    )
    return bool(vendor_ok and product_ok)


def _eval_match(
    match: dict[str, Any], vendor: str, product: str, version: str | None
) -> tuple[bool | None, list[str]]:
    """Evaluate one NVD ``cpeMatch``. Returns (applies|None, ranges)."""
    if not match.get("vulnerable", False):
        return False, []
    criteria = match.get("criteria", "")
    if criteria and not _cpe_names_product(criteria, vendor, product):
        return False, []
    exact = _criteria_version(criteria)
    ranges: list[str] = []
    for key in (
        "versionStartIncluding",
        "versionStartExcluding",
        "versionEndIncluding",
        "versionEndExcluding",
    ):
        if match.get(key) is not None:
            ranges.append(f"{key}={match[key]}")
    if version is None:
        # Product association exists; version evidence is insufficient.
        return None, ranges
    if exact is not None and not ranges:
        try:
            return (compare_versions(version, exact) == 0), [f"version={exact}"]
        except Exception:
            return None, [f"version={exact}"]
    verdict = _in_range(
        version,
        match.get("versionStartIncluding"),
        match.get("versionStartExcluding"),
        match.get("versionEndIncluding"),
        match.get("versionEndExcluding"),
    )
    if verdict is None and exact is None and not ranges:
        # Vulnerable flag with no version constraints: the whole product line.
        return True, ["unbounded"]
    return verdict, ranges


def _eval_node(
    node: dict[str, Any], vendor: str, product: str, version: str | None
) -> tuple[bool | None, list[str]]:
    """Evaluate one NVD configuration node (AND/OR over children or a match)."""
    negate = bool(node.get("negate", False))

    def _apply(value: bool | None) -> bool | None:
        return (not value) if (negate and value is not None) else value

    children = node.get("children")
    matches = node.get("cpeMatch", []) or []
    if children:
        results = [_eval_node(child, vendor, product, version) for child in children]
        ranges = [r for _, rs in results for r in rs]
        operator = (node.get("operator", "OR") or "OR").upper()
        verdicts = [v for v, _ in results]
        if operator == "AND":
            if any(v is False for v in verdicts):
                return _apply(False), ranges
            if all(v is True for v in verdicts):
                return _apply(True), ranges
            return _apply(None), ranges
        if any(v is True for v in verdicts):
            return _apply(True), ranges
        if all(v is False for v in verdicts):
            return _apply(False), ranges
        return _apply(None), ranges
    verdicts = []
    ranges: list[str] = []
    for match in matches:
        verdict, match_ranges = _eval_match(match, vendor, product, version)
        verdicts.append(verdict)
        ranges.extend(match_ranges)
    operator = (node.get("operator", "OR") or "OR").upper()
    if operator == "AND":
        if any(v is False for v in verdicts):
            return _apply(False), ranges
        if verdicts and all(v is True for v in verdicts):
            return _apply(True), ranges
        return _apply(None), ranges
    if any(v is True for v in verdicts):
        return _apply(True), ranges
    if verdicts and all(v is False for v in verdicts):
        return _apply(False), ranges
    return _apply(None), ranges


def evaluate_applicability(
    record: dict[str, Any],
    vendor: str,
    product: str,
    version: str | None,
    cpe_confidence: float = 0.0,
    cpe_ambiguous: bool = False,
) -> tuple[str, list[str]]:
    """Classify a CVE record against detected product/version evidence.

    ``confirmed_version_match``: reliable CPE identification and an
    affected-version match. ``likely_applicable``: strong evidence with one
    uncertainty (fuzzy CPE or minor version ambiguity). ``potential``:
    product association exists but version applicability is unproven.
    ``not_applicable``: the range excludes the version. ``unknown``: no
    usable configurations or no data at all.
    """
    configurations = record.get("configurations", []) or []
    if not configurations:
        return "unknown", []
    node_verdicts: list[bool | None] = []
    ranges: list[str] = []
    for config in configurations:
        for node in config.get("nodes", []) or []:
            verdict, node_ranges = _eval_node(node, vendor, product, version)
            node_verdicts.append(verdict)
            ranges.extend(node_ranges)
    if any(v is True for v in node_verdicts):
        matched = sorted(set(ranges))
        if cpe_ambiguous or cpe_confidence < 0.75:
            return "likely_applicable", matched
        if version is None:
            return "potential", matched
        return "confirmed_version_match", matched
    if any(v is None for v in node_verdicts):
        if version is None:
            return ("potential" if cpe_confidence >= 0.75 else "unknown"), sorted(
                set(ranges)
            )
        return "likely_applicable", sorted(set(ranges))
    if node_verdicts and all(v is False for v in node_verdicts):
        return "not_applicable", sorted(set(ranges))
    return "unknown", []


# ── EPSS enrichment ──


def fetch_epss(cve_ids: list[str]) -> dict[str, dict[str, Any]]:
    """FIRST EPSS scores with percentile and date, keyed by CVE ID."""
    wanted = sorted({c.strip().upper() for c in cve_ids if c and c.strip()})
    if not wanted:
        return {}
    results: dict[str, dict[str, Any]] = {}
    missing = []
    for cve_id in wanted:
        cached = cve_cache.get_epss_entry(cve_id)
        if cached is not None:
            results[cve_id] = cached
        else:
            missing.append(cve_id)
    if missing:
        try:
            params = {"cve": ",".join(missing)}
            _status, data = _request_json(
                f"{EPSS_API_BASE}/epss", params=params
            )
        except CveFinderError as exc:
            raise exc
        for item in (data or {}).get("data", []) or []:
            cve = str(item.get("cve", "")).upper()
            if not cve or cve not in missing:
                continue
            try:
                record = {
                    "score": float(item.get("epss")),
                    "percentile": float(item.get("percentile")),
                    "date": item.get("date") or "",
                }
            except (TypeError, ValueError):
                continue
            results[cve] = record
            cve_cache.set_epss_entry(cve, record)
    return {cve: results[cve] for cve in wanted if cve in results}


# ── CISA KEV ──


def fetch_kev_catalog() -> dict[str, dict[str, Any]]:
    """CISA Known Exploited Vulnerabilities catalogue keyed by CVE ID."""
    cached = cve_cache.get_kev_catalog()
    if cached is not None:
        return cached
    try:
        _status, data = _request_json(KEV_CATALOG_URL)
    except CveFinderError as exc:
        raise exc
    catalog: dict[str, dict[str, Any]] = {}
    vulns = (data or {}).get("vulnerabilities", []) or []
    if not isinstance(vulns, list):
        raise CveFinderError("unexpected KEV catalogue shape")
    for entry in vulns:
        if not isinstance(entry, dict):
            continue
        cve = str(entry.get("cveID", "")).upper()
        if cve:
            catalog[cve] = entry
    cve_cache.set_kev_catalog(catalog)
    return catalog


def kev_lookup(cve_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """KEV status for one CVE. Unlisted CVEs are explicitly not exploited."""
    cve_id = cve_id.strip().upper()
    if catalog is None:
        catalog = fetch_kev_catalog()
    entry = (catalog or {}).get(cve_id)
    if not entry:
        return {"listed": False}
    return {
        "listed": True,
        "date_added": entry.get("dateAdded", ""),
        "due_date": entry.get("dueDate", ""),
        "required_action": entry.get("requiredAction", ""),
        "notes": entry.get("notes", ""),
    }


# ── Chain building ──


_ROLE_RANK = {"entry": 0, "auth_bypass": 1, "privilege_escalation": 2, "execution": 3, "disclosure": 4}

_ROLE_KEYWORDS: dict[str, list[str]] = {
    "auth_bypass": ["authenticat", "bypass", "authorization", "login", "credential"],
    "privilege_escalation": ["privilege", "escalat", "administrator", "root", "elevation"],
    "execution": ["remote code", "rce", "command injection", "command execution", "arbitrary code"],
    "disclosure": ["disclos", "information exposure", "read arbitrary", "travers", "sensitive"],
}

_ROLE_CWES: dict[str, list[str]] = {
    "auth_bypass": ["CWE-287", "CWE-306", "CWE-639", "CWE-862", "CWE-863", "CWE-640"],
    "privilege_escalation": ["CWE-269", "CWE-250", "CWE-264", "CWE-276", "CWE-732"],
    "execution": ["CWE-78", "CWE-94", "CWE-95", "CWE-77", "CWE-434"],
    "disclosure": ["CWE-200", "CWE-201", "CWE-209", "CWE-22", "CWE-552"],
}


def _cve_roles(record: dict[str, Any]) -> list[str]:
    """Plausible attacker roles for a CVE from CVSS, CWE and description text."""
    roles: list[str] = []
    vector = ((record.get("cvss") or {}).get("vector") or "").upper()
    if "/AV:N" in vector or "NETWORK" in vector:
        roles.append("entry")
    text = f"{record.get('description', '')}".lower()
    cwes = [str(c).upper() for c in (record.get("cwe") or [])]
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(k in text for k in keywords):
            roles.append(role)
    for role, wanted in _ROLE_CWES.items():
        if any(c in wanted for c in cwes) and role not in roles:
            roles.append(role)
    if not roles:
        roles.append("execution" if "RCE" in text.upper() else "disclosure")
    return sorted(set(roles), key=lambda r: _ROLE_RANK.get(r, 9))


def build_chains(vulns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Propose evidence-backed candidate chains, most relevant first.

    A chain needs CVEs on the same asset with complementary roles forming a
    plausible progression (entry → auth bypass → escalation/execution /
    disclosure). Shared severity, vendor or host alone never forms a chain;
    unrelated CVEs are left out and named as excluded.
    """
    by_asset: dict[str, list[dict[str, Any]]] = {}
    for vuln in vulns:
        if vuln.get("applicability") == "not_applicable":
            continue
        asset = str(vuln.get("asset") or vuln.get("product") or "unknown")
        by_asset.setdefault(asset, []).append(vuln)
    chains: list[dict[str, Any]] = []
    for asset, items in by_asset.items():
        if len(items) < 2:
            continue
        ranked = sorted(
            items,
            key=lambda v: (
                min([_ROLE_RANK.get(r, 9) for r in _cve_roles(v)]),
                -(float(((v.get("cvss") or {}).get("score")) or 0.0)),
            ),
        )
        roles_seen: list[str] = []
        chain_members: list[dict[str, Any]] = []
        for vuln in ranked:
            new_roles = [r for r in _cve_roles(vuln) if r not in roles_seen]
            if new_roles and (not chain_members or new_roles[0] != "entry" or len(chain_members) == 0):
                chain_members.append(vuln)
                roles_seen.extend(new_roles)
        # A chain needs progression: entry plus at least one follow-on role,
        # or two distinct non-entry roles. A lone entry CVE is not a chain.
        distinct = [r for r in roles_seen if r != "entry"]
        if "entry" in roles_seen and not distinct:
            continue
        if len({v["cve_id"] for v in chain_members}) < 2:
            continue
        progression = " → ".join(
            f"{v['cve_id']} ({', '.join(_cve_roles(v))})" for v in chain_members
        )
        chains.append(
            {
                "chain_id": f"candidate-{len(chains) + 1}",
                "asset": asset,
                "cves": [v["cve_id"] for v in chain_members],
                "confidence": "candidate",
                "progression": progression,
                "steps": [
                    {
                        "cve_id": v["cve_id"],
                        "provides": ", ".join(_cve_roles(v)),
                        "prerequisite": (
                            "network reachability of the affected service"
                            if "entry" in _cve_roles(v)
                            else f"prior step in this chain ({chain_members[idx - 1]['cve_id']})"
                            if idx > 0
                            else "prior foothold on the asset"
                        ),
                        "why_next": (
                            "initial access: remotely reachable without privileges"
                            if "entry" in _cve_roles(v)
                            else "extends the previous step's access toward the attacker's objective"
                        ),
                        "evidence": (v.get("description") or "")[:300],
                    }
                    for idx, v in enumerate(chain_members)
                ],
                "assumptions_unverified": [
                    "Network path from attacker to the affected service exists.",
                    "Vulnerable code path is reachable with the detected configuration.",
                    "Chaining has NOT been verified by exploitation.",
                ],
                "excluded_cves": sorted(
                    {v["cve_id"] for v in items}
                    - {v["cve_id"] for v in chain_members}
                ),
            }
        )
    chains.sort(
        key=lambda c: -sum(
            float(((v.get("cvss") or {}).get("score")) or 0.0)
            for v in vulns
            if v["cve_id"] in c["cves"]
        )
    )
    return chains


# ── Finder orchestration ──


def _empty_report(target: str) -> dict[str, Any]:
    return {
        "success": True,
        "target": target,
        "lookup_status": {"nvd": "not_attempted", "epss": "not_attempted", "cisa_kev": "not_attempted"},
        "discovered_products": [],
        "vulnerabilities": [],
        "chains": [],
        "summary": "No products or CVE identifiers were supplied; nothing to look up.",
    }


class CveFinder:
    """Runs the full CVE discovery pipeline for detected products / CVE IDs."""

    def find(
        self,
        target: str,
        products: list[dict[str, Any]] | None = None,
        cve_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        products = [p for p in (products or []) if isinstance(p, dict)]
        wanted_ids = sorted(
            {
                c.strip().upper()
                for c in (cve_ids or [])
                if isinstance(c, str) and CVE_ID_RE.match(c.strip())
            }
        )
        if not products and not wanted_ids:
            return _empty_report(target)

        lookup_status = {"nvd": "success", "epss": "success", "cisa_kev": "success"}
        discovered: list[dict[str, Any]] = []
        records: dict[str, dict[str, Any]] = {}
        asset_of: dict[str, str] = {}

        # Step B — CPE identification per detected product.
        cpe_of: dict[int, dict[str, Any]] = {}
        nvd_failed = False
        for idx, product in enumerate(products):
            vendor = str(product.get("vendor", "") or "")
            name = str(product.get("product", "") or "")
            component = str(product.get("component", "") or "")
            if not (vendor or name):
                discovered.append(
                    {
                        "vendor": vendor,
                        "product": name,
                        "component": component,
                        "detected_version": product.get("version"),
                        "cpe": None,
                        "applicability": "unknown",
                        "evidence_source": product.get("evidence_source", "technology_fingerprint"),
                        "note": "insufficient vendor/product evidence to search NVD",
                    }
                )
                continue
            try:
                identification = identify_cpe(
                    vendor, name, component, _clean_version(product.get("version"))
                )
            except CveFinderError:
                nvd_failed = True
                identification = {"cpe": None, "confidence": 0.0, "candidates": [], "ambiguous": True}
            cpe_of[idx] = identification
            discovered.append(
                {
                    "vendor": vendor,
                    "product": name,
                    "component": component,
                    "detected_version": product.get("version"),
                    "cpe": identification["cpe"],
                    "cpe_confidence": identification["confidence"],
                    "cpe_ambiguous": identification["ambiguous"],
                    "applicability": "unknown",
                    "evidence_source": product.get("evidence_source", "technology_fingerprint"),
                }
            )

        # Step C — CVE discovery: CPE search plus direct ID lookups.
        origin_idx: dict[str, int] = {}
        for idx, product in enumerate(products):
            identification = cpe_of.get(idx)
            if not identification or not identification["cpe"]:
                continue
            try:
                found = search_cves_by_cpe(identification["cpe"])
            except CveFinderError:
                nvd_failed = True
                continue
            for record in found:
                cve_id = record.get("cve_id", "")
                if not cve_id:
                    continue
                records[cve_id] = record
                asset_of.setdefault(
                    cve_id,
                    str(product.get("product") or product.get("component") or "unknown"),
                )
                origin_idx.setdefault(cve_id, idx)
                cve_cache.set_nvd_entry(cve_id, record)

        for cve_id in wanted_ids:
            if cve_id in records:
                continue
            try:
                record = lookup_cve(cve_id)
            except CveFinderError:
                nvd_failed = True
                continue
            if record is None:
                continue
            records[cve_id] = record
            asset_of.setdefault(cve_id, "direct_lookup")

        if nvd_failed and not records:
            lookup_status["nvd"] = "failed"
        elif nvd_failed:
            lookup_status["nvd"] = "partial"

        # Applicability per product × CVE (version matching is critical).
        vulnerabilities: list[dict[str, Any]] = []
        for cve_id, record in records.items():
            best = ("unknown", [])
            best_product: dict[str, Any] | None = None
            # The product whose CPE discovered the CVE is evaluated first so
            # applicability ties attribute the CVE to its own asset instead
            # of whichever product happens to sort first.
            ordered = sorted(
                enumerate(products), key=lambda pair: 0 if pair[0] == origin_idx.get(cve_id) else 1
            )
            for idx, product in ordered:
                _ident = cpe_of.get(idx, {})
                applicability, ranges = evaluate_applicability(
                    record,
                    str(product.get("vendor", "") or ""),
                    str(product.get("product", "") or product.get("component", "") or ""),
                    _clean_version(product.get("version")),
                    cpe_confidence=float(_ident.get("confidence", 0.0)),
                    cpe_ambiguous=bool(_ident.get("ambiguous", False)),
                )
                rank = {"confirmed_version_match": 0, "likely_applicable": 1, "potential": 2, "unknown": 3, "not_applicable": 4}
                if best_product is None or rank[applicability] < rank[best[0]]:
                    best = (applicability, ranges)
                    best_product = product
            if best_product is None:
                # Direct ID lookup without product context: applicability unknown.
                applicability, ranges = "unknown", []
                asset = asset_of.get(cve_id, "direct_lookup")
            else:
                applicability, ranges = best
                asset = str(
                    best_product.get("product") or best_product.get("component") or "unknown"
                )
            vulnerabilities.append(
                {
                    "cve_id": cve_id,
                    "description": record.get("description", ""),
                    "cvss": record.get("cvss", {}),
                    "cwe": record.get("cwe", []),
                    "published": record.get("published", ""),
                    "last_modified": record.get("last_modified", ""),
                    "references": record.get("references", []),
                    "affected_versions": ranges,
                    "fixed_versions": [],
                    "applicability": applicability,
                    "verification_status": "not_exploit_verified",
                    "asset": asset,
                    "sources": ["nvd"],
                }
            )

        # Mark per-product best applicability for the summary.
        for entry, product in zip(discovered, products, strict=False):
            idx_products = [i for i, p in enumerate(products) if p is product]
            if not idx_products:
                continue
            related = [
                v
                for v in vulnerabilities
                if v["asset"] == str(product.get("product") or product.get("component") or "unknown")
            ]
            order = {"confirmed_version_match": 0, "likely_applicable": 1, "potential": 2, "unknown": 3, "not_applicable": 4}
            if related:
                entry["applicability"] = sorted(related, key=lambda v: order[v["applicability"]])[0]["applicability"]

        # Step D — enrichment (EPSS + KEV). Failures degrade, never abort.
        try:
            epss = fetch_epss(list(records))
            for vuln in vulnerabilities:
                entry = epss.get(vuln["cve_id"])
                vuln["epss"] = entry or {"score": None, "percentile": None, "date": None}
                if entry:
                    vuln["sources"].append("epss")
        except CveFinderError:
            lookup_status["epss"] = "failed"
            for vuln in vulnerabilities:
                vuln["epss"] = {"score": None, "percentile": None, "date": None}
        try:
            catalog = fetch_kev_catalog()
            for vuln in vulnerabilities:
                kev = kev_lookup(vuln["cve_id"], catalog)
                vuln["cisa_kev"] = kev
                if kev.get("listed"):
                    vuln["sources"].append("cisa_kev")
        except CveFinderError:
            lookup_status["cisa_kev"] = "failed"
            for vuln in vulnerabilities:
                vuln["cisa_kev"] = {"listed": False, "unavailable": True}

        # Step E — candidate chains.
        chains = build_chains(vulnerabilities)

        applicable = sum(
            1 for v in vulnerabilities if v["applicability"] in ("confirmed_version_match", "likely_applicable")
        )
        summary = (
            f"Discovered {len(vulnerabilities)} CVE(s) across {len(discovered)} product(s); "
            f"{applicable} applicable to the detected versions; {len(chains)} candidate chain(s)."
        )
        failed = [k for k, v in lookup_status.items() if v in ("failed", "partial")]
        if failed:
            summary += f" Degraded sources: {', '.join(failed)}."
        return {
            "success": True,
            "target": target,
            "lookup_status": lookup_status,
            "discovered_products": discovered,
            "vulnerabilities": sorted(
                vulnerabilities,
                key=lambda v: -(float((v.get("cvss") or {}).get("score") or 0.0)),
            ),
            "chains": chains,
            "summary": summary,
        }


def _clean_version(version: Any) -> str | None:
    if version is None:
        return None
    text = str(version).strip()
    if not text or text.lower() in ("unknown", "n/a", "na", "*", "-"):
        return None
    return text

"""
Reconnaissance execution logic extracted from Orchestrator.
"""

from __future__ import annotations

import contextlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from config.constants import (
    DEFAULT_AGGRESSIVENESS,
)
from streaming import emit_finding_rt, emit_finding, emit_tool_start
from utils.logging_utils import ScanLogger

from .utils import get_wordlist_path

if TYPE_CHECKING:
    from models.recon_context import ReconContext

logger = logging.getLogger(__name__)


def execute_recon_tools(
    ctx,
    target: str,
    budget: dict,
    aggressiveness: str = DEFAULT_AGGRESSIVENESS,
) -> tuple[list[dict], object]:
    """
    Execute reconnaissance tools against target.

    Args:
        ctx: ToolContext or Orchestrator (provides tool_runner, parser, normalizer)
        target: Target URL
        budget: Budget configuration
        aggressiveness: Scan aggressiveness level (default, high, extreme)

    Returns:
        Tuple of (list of normalized findings, ReconContext)
    """
    # Lazily get a ToolContext-aware wrapper
    if not hasattr(ctx, "publish_activity"):
        from tools.context import ToolContext

        ctx = ToolContext.from_orchestrator(ctx)

    slog = ScanLogger("recon_pipeline", engagement_id=getattr(ctx, 'engagement_id', ''))
    slog.phase_header("EXECUTE RECON TOOLS", target=target, aggressiveness=aggressiveness)
    all_findings = []

    # Guard against None/empty target
    if not target:
        logger.warning(
            f"[execute_recon_tools] No valid target for engagement {ctx.engagement_id}, skipping recon"
        )
        from models.recon_context import ReconContext

        return [], ReconContext(target_url=target or "")

    from urllib.parse import urlparse
    parsed_target = urlparse(target)
    target_domain = parsed_target.hostname or target.replace("https://", "").replace("http://", "").split("/")[0]

    # Aggressiveness config
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS
    katana_depth = {"default": "3", "high": "5", "extreme": "7"}.get(agg, "3")
    naabu_ports = {"default": "-top-ports", "high": "-top-ports", "extreme": "-p-"}.get(
        agg, "-top-ports"
    )
    naabu_port_val = {"default": "1000", "high": "10000", "extreme": "1-65535"}.get(
        agg, "1000"
    )
    amass_mode = {
        "default": ["enum", "-d"],
        "high": ["enum", "-d", "-brute", "-active"],
        "extreme": ["enum", "-d", "-brute", "-w",
                    os.path.join(os.path.dirname(os.path.dirname(__file__)), "wordlists", "common.txt")],
    }.get(agg, ["enum", "-d"])

    def _emit(
        tool: str, activity: str, status: str, items: int = None, details: str = None
    ):
        ctx.publish_activity(
            tool=tool,
            activity=activity,
            status=status,
            items=items,
            details=details,
        )

    # Execute httpx for endpoint discovery
    slog.tool_start("httpx", [target])
    _emit("httpx", "Discovering live endpoints and probing HTTP services", "started")
    try:
        emit_tool_start(ctx.engagement_id, "httpx", ["-u", target, "-json", "-silent"])
        httpx_result = ctx.tool_runner.run(
            "httpx", ["-u", target, "-json", "-silent"], timeout=30
        )
        parsed_count = 0
        if httpx_result.success:
            parsed = ctx.parser.parse("httpx", httpx_result.stdout)
            for p in parsed:
                normalized = ctx._normalize_finding(p, "httpx")
                if normalized:
                    # emit_finding_rt is imported from streaming
                    all_findings.append(normalized)
                    parsed_count += 1
        slog.tool_complete("httpx", success=True, findings=parsed_count)
        _emit(
            "httpx", "Live endpoint discovery complete", "completed", items=parsed_count
        )
    except Exception as e:
        slog.tool_complete("httpx", success=False)
        _emit("httpx", f"Live endpoint discovery failed: {str(e)}", "failed")
        logger.warning(f"httpx failed: {e}")

    # Phase 2: Execute remaining recon tools in parallel
    ffuf_wordlist_map = {
        "default": get_wordlist_path("common.txt"),
        "high": get_wordlist_path("extended.txt"),
        "extreme": get_wordlist_path("comprehensive.txt"),
    }
    ffuf_wordlist = str(ffuf_wordlist_map.get(agg, get_wordlist_path("common.txt")))
    ffuf_cmd = ["-u", f"{target}/FUZZ", "-w", ffuf_wordlist, "-json"]
    if agg == "high":
        ffuf_cmd.extend(["-t", "50"])
    elif agg == "extreme":
        ffuf_cmd.extend(["-t", "100", "-mc", "all"])

    amass_cmd = amass_mode + [target_domain, "-json"]
    amass_timeout = (
        120 if agg == "default" else 180 if agg == "high" else 240
    )

    naabu_cmd = ["-host", target_domain, "-json"]
    if naabu_ports == "-p-":
        naabu_cmd.append("-p-")
    else:
        naabu_cmd.extend(["-top-ports", naabu_port_val])
    naabu_timeout = (
        60 if agg == "default" else 90 if agg == "high" else 120
    )

    def _run_recon_tool(ctx, tool_name, args, timeout, all_findings, start_msg=None):
        try:
            # Emit start event when tool actually begins (not before pool submits)
            if start_msg:
                _emit(tool_name, start_msg, "started")
            emit_tool_start(ctx.engagement_id, tool_name, args)
            result = ctx.tool_runner.run(tool_name, args, timeout=timeout)
            parsed_count = 0
            if result and result.success:
                parsed = ctx.parser.parse(tool_name, result.stdout)
                for p in parsed:
                    normalized = ctx._normalize_finding(p, tool_name)
                    if normalized:
                        # Emit in real-time as each finding is discovered
                        emit_finding_rt(ctx.engagement_id, normalized, tool_name)
                        # Note: list.append is thread-safe under GIL
                        all_findings.append(normalized)
                        parsed_count += 1
            return tool_name, bool(result and result.success), parsed_count, None
        except Exception as e:
            logger.warning(f"Recon tool {tool_name} failed: {e}")
            return tool_name, False, 0, str(e)

    amass_start_msg = (
        f"Enumerating subdomains for {target_domain} (passive)"
        if agg == "default"
        else f"Enumerating subdomains for {target_domain} (active + passive)"
        if agg == "high"
        else f"Enumerating subdomains for {target_domain} (brute force + all sources)"
    )
    naabu_start_msg = (
        f"Probing open ports on {target_domain} (top 1000)"
        if agg == "default"
        else f"Probing open ports on {target_domain} (top 10,000)"
        if agg == "high"
        else f"Probing open ports on {target_domain} (full range 1-65535)"
    )

    recon_tools = {
        "katana": {
            "args": ["-u", target, "-jsonl", "-silent", "-d", katana_depth],
            "timeout": 90,
            "start_msg": f"Crawling application routes and links up to depth {katana_depth}",
            "success_msg": "Web crawling complete \u2014 mapped application surface",
        },
        "ffuf": {
            "args": ffuf_cmd,
            "timeout": 60,
            "start_msg": f"Fuzzing directories ({agg} mode)",
            "success_msg": "Directory fuzzing complete",
        },
        "amass": {
            "args": amass_cmd,
            "timeout": amass_timeout,
            "start_msg": amass_start_msg,
            "success_msg": "Subdomain enumeration complete \u2014 found {{}} subdomains",
        },
        "subfinder": {
            "args": ["-d", target_domain, "-silent"],
            "timeout": 30,
            "start_msg": f"Enumerating subdomains via passive sources ({target_domain})",
            "success_msg": "Subdomain enumeration complete \u2014 found {{}} subdomains",
        },
        "alterx": {
            "args": ["-d", target_domain, "-silent"],
            "timeout": 30,
            "start_msg": f"Generating subdomain permutations for {target_domain}",
            "success_msg": "Permutation generation complete \u2014 generated {{}} variants",
        },
        "naabu": {
            "args": naabu_cmd,
            "timeout": naabu_timeout,
            "start_msg": naabu_start_msg,
            "success_msg": "Port scan complete \u2014 found {{}} open ports",
        },
        "whatweb": {
            "args": ["--format=json", target],
            "timeout": 30,
            "start_msg": "Fingerprinting web technologies and server stack",
            "success_msg": "Technology fingerprinting complete",
        },
        "nikto": {
            "args": ["-h", target, "-Format", "csv"],
            "timeout": 90,
            "start_msg": "Scanning web server for misconfigurations and known issues",
            "success_msg": "Web server scan complete",
        },
        "gau": {
            "args": [target, "--json"],
            "timeout": 60,
            "start_msg": "Fetching known URLs from passive archives (gau)",
            "success_msg": "Passive URL discovery complete",
        },
        "waybackurls": {
            "args": [target],
            "timeout": 45,
            "start_msg": "Retrieving historical URLs from Wayback Machine",
            "success_msg": "Historical URL retrieval complete",
        },
        "gospider": {
            "args": ["-s", target, "--json", "--depth=2", "--concurrent=5"],
            "timeout": 90,
            "start_msg": "Spidering website with gospider for endpoints",
            "success_msg": "Gospider crawling complete — discovered {{}} endpoints",
        },
    }

    # Budget enforcement: limit number of recon tools if budget specifies a cap
    max_tools = budget.get("max_recon_tools", len(recon_tools)) if isinstance(budget, dict) else len(recon_tools)
    if max_tools < len(recon_tools):
        logger.info("Budget limits recon tools to %d (from %d available)", max_tools, len(recon_tools))
    selected_tools = dict(list(recon_tools.items())[:max_tools])

    slog.info(f"Launching {len(selected_tools)} parallel recon tools (budget allows {max_tools})")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_run_recon_tool, ctx, name, cfg["args"], cfg["timeout"], all_findings, cfg.get("start_msg")): name
            for name, cfg in selected_tools.items()
        }
        try:
            for future in as_completed(futures, timeout=300):
                tool_name, success, parsed_count, error = future.result(timeout=15)
                if success:
                    slog.tool_complete(tool_name, success=True, findings=parsed_count)
                    success_msg = recon_tools[tool_name]["success_msg"]
                    formatted_msg = success_msg.replace("{{}}", str(parsed_count)) if "{{}}" in success_msg else success_msg
                    _emit(tool_name, formatted_msg, "completed", items=parsed_count)
                else:
                    slog.tool_complete(tool_name, success=False)
                    _emit(tool_name, f"{tool_name} failed: {error}" if error else f"{tool_name} failed", "failed")
        except TimeoutError:
            logger.warning("Recon tool batch timed out after 300s — some tools may not have completed")
            slog.warn("Recon tool batch timed out after 300s")
            # Cancel remaining futures
            for future in futures:
                future.cancel()

    recon_context = summarize_recon_findings(target, all_findings)

    # ── Load target profile for cross-scan learning ──
    try:
        from urllib.parse import urlparse

        from database.repositories.target_profile_repository import (
            TargetProfileRepository,
        )

        # Resolve org_id from ctx or scan_ctx
        _org_id = None
        _db_conn = None
        if hasattr(ctx, "org_id"):
            _org_id = ctx.org_id
        if hasattr(ctx, "db_connection_string"):
            _db_conn = ctx.db_connection_string
        # Fallback: try getting org_id from orchestrator
        if not _org_id and hasattr(ctx, "_get_org_id"):
            with contextlib.suppress(Exception):
                _org_id = ctx._get_org_id()

        domain = urlparse(target).netloc
        if _org_id and domain:
            profile_repo = TargetProfileRepository(_db_conn)
            existing_profile = profile_repo.get_profile(_org_id, domain)
            if existing_profile:
                recon_context.target_profile = existing_profile
                logger.info(
                    "Loaded target profile for %s (%d prior scans)",
                    domain,
                    existing_profile.get("total_scans", 0),
                )
    except Exception as e:
        logger.warning("Could not load target profile (non-fatal): %s", e)

    slog.info(f"Recon pipeline complete: {len(all_findings)} total findings")
    return all_findings, recon_context


def _probe_login_pages(
    target: str,
    auth_endpoints: list[str],
    timeout: int = 10,
) -> tuple[list[str], bool]:
    """Actively probe discovered auth endpoints to verify they host login forms.

    Makes HTTP GET requests to each candidate endpoint and checks for
    HTML login form indicators (password fields, form tags with auth keywords).

    Args:
        target: Base target URL
        auth_endpoints: List of candidate paths discovered via URL keyword matching
        timeout: HTTP request timeout in seconds

    Returns:
        Tuple of (verified_auth_endpoints, has_login_form)
    """
    import requests
    from urllib.parse import urljoin

    verified: list[str] = []
    has_login_form = False

    for path in auth_endpoints:
        url = urljoin(target.rstrip("/") + "/", path.lstrip("/"))
        try:
            resp = requests.get(url, timeout=timeout, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ArgusRecon/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            })
            if resp.status_code != 200:
                continue

            body = resp.text.lower()
            # Look for HTML form with password field — strongest signal
            has_password = 'type="password"' in body or "type='password'" in body
            has_form = "<form" in body
            has_auth_keywords = any(kw in body for kw in
                                    ("login", "signin", "sign in", "log in"))

            if has_password or (has_form and has_auth_keywords):
                verified.append(url)
                has_login_form = True
        except requests.RequestException:
            logger.debug("Login probe failed for %s", url)
            continue

    return verified, has_login_form


def summarize_recon_findings(target: str, findings: list[dict]) -> ReconContext:
    """
    Convert raw recon findings list into ReconContext.

    Called at end of execute_recon_tools() before returning.
    Actively probes discovered auth endpoints to verify login pages.

    Args:
        target: Target URL
        findings: List of normalized finding dicts

    Returns:
        Populated ReconContext
    """
    from models.recon_context import ReconContext

    if not findings:
        return ReconContext(target_url=target)

    live_endpoints = [
        f.get("endpoint", "") for f in findings if f.get("source_tool") == "httpx"
    ]
    subdomains = [
        f.get("endpoint", "")
        for f in findings
        if f.get("source_tool") in ("amass", "subfinder")
    ]
    open_ports = [
        f.get("evidence", {}) for f in findings if f.get("source_tool") == "naabu"
    ]
    tech_stack = [
        str(t)
        for f in findings
        if f.get("source_tool") == "whatweb"
        for t in (f.get("evidence", {}) if isinstance(f.get("evidence"), dict) else {}).get("plugins", {})
    ]
    crawled_paths = [
        f.get("endpoint", "") for f in findings if f.get("source_tool") in ("katana", "ffuf")
    ][:50]
    param_urls = [
        f.get("endpoint", "")
        for f in findings
        if "?" in f.get("endpoint", "")
        and f.get("source_tool") in ("gau", "waybackurls")
    ]

    auth_kw = ("login", "signin", "auth", "oauth", "sso", "password", "reset")
    api_kw = ("/api/", "/v1/", "/v2/", "/graphql", "/rest/")
    upload_kw = ("upload", "file", "attach", "media")

    all_paths = [f.get("endpoint", "").lower() for f in findings]

    # Keyword-based auth endpoint discovery (passive)
    keyword_auth_endpoints = [
        p for p in crawled_paths if any(k in p.lower() for k in auth_kw)
    ]
    keyword_has_login = any(any(k in p for k in auth_kw) for p in all_paths)

    # Active probe: verify discovered auth endpoints host real login forms
    # This is what makes Argus different — it doesn't just guess, it verifies
    verified_endpoints, verified_has_login = _probe_login_pages(
        target, keyword_auth_endpoints
    )

    # Prefer verified endpoints; fall back to keyword-based if probing fails
    auth_endpoints = verified_endpoints if verified_endpoints else keyword_auth_endpoints
    has_login_page = verified_has_login if verified_endpoints else keyword_has_login

    return ReconContext(
        target_url=target,
        live_endpoints=list(set(live_endpoints))[:100],
        subdomains=list(set(subdomains))[:50],
        open_ports=open_ports[:20],
        tech_stack=list(set(tech_stack))[:20],
        crawled_paths=crawled_paths,
        parameter_bearing_urls=param_urls[:30],
        auth_endpoints=auth_endpoints,
        api_endpoints=[p for p in crawled_paths if any(k in p.lower() for k in api_kw)],
        findings_count=len(findings),
        has_login_page=has_login_page,
        has_api=any(any(k in p for k in api_kw) for p in all_paths),
        has_file_upload=any(any(k in p for k in upload_kw) for p in all_paths),
    )

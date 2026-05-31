"""
Scan execution logic extracted from Orchestrator.
"""

import asyncio
import ipaddress
import json
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

from config.constants import (
    DEFAULT_AGGRESSIVENESS,
    RATE_LIMIT_DELAY_MS,
    SSL_TIMEOUT,
    TOOL_TIMEOUT_DEFAULT,
    TOOL_TIMEOUT_LONG,
)
from streaming import (
    clear_engagement_rt_fingerprints,
    emit_finding_rt,
    emit_tool_complete,
    emit_tool_start,
)
from tools.web_scanner import WebScanner
from utils.logging_utils import ScanLogger

# Lazy import for RateLimitRepository to avoid circular dependencies
_RATE_LIMIT_REPO = None


def _get_rate_limit_repo():
    """Lazy-loaded RateLimitRepository singleton for logging rate limit events."""
    global _RATE_LIMIT_REPO
    if _RATE_LIMIT_REPO is None:
        try:
            from database.repositories.rate_limit_repository import RateLimitRepository
            # IMPORTANT: Pass None so RateLimitRepository uses db_cursor()
            # (connection pool). Passing a connection string as db_connection
            # would crash on self.db.cursor() since strings have no cursor().
            _RATE_LIMIT_REPO = RateLimitRepository(db_connection=None)
        except ImportError:
            pass
    return _RATE_LIMIT_REPO

from .utils import get_nuclei_templates_path

# Module-level flag to avoid repeated import inside the per-target loop
try:
    from feature_flags import is_enabled as _feature_enabled
except ImportError:
    def _feature_enabled(name, default=False):
        return False

logger = logging.getLogger(__name__)

def _should_run_tool(tool_name: str, recon_context=None, tech_stack: list[str] | None = None, target: str = "") -> bool:
    """Check if a tool should run based on requires gate.

    Accepts either a ReconContext or raw tech_stack/target params.
    Returns True if tool should run, False if gate not satisfied.

    For the gate check we build a context that includes all ReconContext
    attributes (not just a hardcoded subset), so new recon_signals added
    to tool definitions are automatically supported.
    """
    from tool_definitions import TOOLS, evaluate_gate

    tool_def = TOOLS.get(tool_name)
    if not tool_def or not tool_def.requires:
        return True  # no gate → always run

    # Start with tech_stack and target_url
    gate_ctx = {
        "tech_stack": tech_stack or [],
        "target_url": target,
    }
    # Dynamically copy ReconContext dataclass fields only (not methods)
    if recon_context is not None:
        if hasattr(recon_context, "__dataclass_fields__"):
            for attr in recon_context.__dataclass_fields__:
                gate_ctx[attr] = getattr(recon_context, attr)
        else:
            for attr in dir(recon_context):
                if not attr.startswith("_") and not callable(getattr(recon_context, attr)):
                    gate_ctx[attr] = getattr(recon_context, attr)
    # Ensure boolean signals default to False
    for signal in tool_def.requires.recon_signals or []:
        if signal not in gate_ctx:
            gate_ctx[signal] = False

    ctx = SimpleNamespace(**gate_ctx)
    return evaluate_gate(tool_name, ctx)

NUCLEI_SEVERITY_BY_AGGRESSIVENESS = {
    'default': 'medium,high,critical',
    'high': 'low,medium,high,critical',
    'extreme': 'info,low,medium,high,critical',
}

TECH_TAG_MAP = {
    'wordpress': ['wordpress', 'wp'],
    'php': ['php'],
    'apache': ['apache'],
    'nginx': ['nginx'],
    'java': ['java', 'spring', 'tomcat'],
    'node': ['nodejs', 'express'],
    'react': ['javascript', 'react', 'reactjs'],
    'angular': ['javascript', 'angular'],
    'vue': ['javascript', 'vue'],
    'django': ['python', 'django'],
    'flask': ['python', 'flask'],
    'mysql': ['mysql'],
    'postgresql': ['postgresql'],
    'redis': ['redis'],
}

ALWAYS_INCLUDE_TAGS = ['cve', 'rce', 'sqli', 'xss', 'ssrf', 'lfi',
                       'exposed-panel', 'default-login', 'misconfig', 'takeover']


def _build_nuclei_tags(tech_stack, agg='default') -> list[str]:
    tags = set(ALWAYS_INCLUDE_TAGS)
    if agg == 'extreme':
        tags.add('fuzz')
    if tech_stack:
        for tech in tech_stack:
            tech_lower = tech.lower()
            for key, mapped_tags in TECH_TAG_MAP.items():
                # Match if the tech name directly corresponds to a key,
                # or if any mapped tag appears in the tech name.
                # Checks both directions to prevent false positives like
                # matching "java" key against "javascript" tech.
                if tech_lower == key or any(tag in tech_lower for tag in mapped_tags):
                    tags.update(mapped_tags)
    return ['-tags', ','.join(sorted(tags))]


def _is_reachable(target: str) -> bool:
    # Use urlparse for reliable hostname extraction (handles IPv6, userinfo, etc.)
    from urllib.parse import urlparse
    try:
        parsed = urlparse(target)
        hostname = parsed.hostname or target
    except Exception:
        hostname = target.replace('https://', '').replace('http://', '').split('/')[0].split(':')[0]

    try:
        ip = ipaddress.ip_address(hostname)
        # Block private / link-local / loopback IPs to prevent internal network scanning
        # Includes IPv4 private (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16),
        # IPv6 unique local (fc00::/7), IPv6 link-local (fe80::/10), loopback, etc.
        # M-01: ipaddress.is_private also covers IPv6 unique-local on Python 3.9+,
        # and is_link_local covers fe80::/10. Check ipv4_mapped addresses too.
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            logger.warning(f'Target {target} resolves to private IP {ip} — skipping')
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            mapped = ipaddress.ip_address(ip.ipv4_mapped)
            if mapped.is_private or mapped.is_loopback or mapped.is_link_local:
                logger.warning(f'Target {target} resolves to IPv4-mapped private IP {ip} — skipping')
                return False
        return True
    except ValueError:
        pass
    if hostname in ('localhost', '127.0.0.1', '::1'):
        logger.warning(f'Target {target} resolves to loopback — skipping')
        return False
    if hostname.startswith('169.254.'):
        logger.warning(f'Target {target} is link-local — skipping')
        return False
    try:
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        # Validate resolved IPs to prevent DNS rebinding
        for _family, _typ, _proto, _cn, sockaddr in addrinfo:
            resolved_ip = sockaddr[0]
            try:
                addr = ipaddress.ip_address(resolved_ip)
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    logger.warning(
                        f'Target {target} resolved to {resolved_ip} (private/internal) — '
                        f'blocking to prevent DNS rebinding SSRF'
                    )
                    return False
            except ValueError:
                pass
        return True
    except socket.gaierror as e:
        if e.errno in (-2, -3):
            logger.warning(f'DNS: {hostname} not found — skipping')
            return False
        return True
    except Exception as e:
        logger.warning(f"DNS resolution for {hostname} failed with unexpected error — assuming NOT reachable: {e}")
        return False


# ---------------------------------------------------------------------------
# Thread-based async runner (H-04)
# Uses a dedicated daemon thread with a persistent event loop to safely call
# async code from synchronous functions without creating new event loops
# (which crashes with "asyncio.run() cannot be called from a running loop").
# ---------------------------------------------------------------------------
_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_LOOP_LOCK = threading.Lock()


def _get_async_loop() -> asyncio.AbstractEventLoop:
    """Get or create the persistent async event loop running in a daemon thread."""
    global _ASYNC_LOOP
    if _ASYNC_LOOP is None or _ASYNC_LOOP.is_closed():
        with _ASYNC_LOOP_LOCK:
            if _ASYNC_LOOP is None or _ASYNC_LOOP.is_closed():
                loop = asyncio.new_event_loop()
                t = threading.Thread(target=loop.run_forever, daemon=True, name="async-worker")
                t.start()
                _ASYNC_LOOP = loop
    return _ASYNC_LOOP


def _run_async(coro) -> any:
    """Run a coroutine on the persistent background event loop from a sync context."""
    loop = _get_async_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result()


# Per-engagement in-memory dedup to prevent emitting duplicate findings during
# streaming across concurrent engagements (H-v4-05). Previously a single module-
# level set was used, causing findings from one engagement to be silently
# suppressed in another engagement scanning the same target.
_emitted_fingerprints: dict[str, set[str]] = {}
_emitted_fingerprints_lock = threading.Lock()

# L-19: Register atexit cleanup to prevent memory leaks if the worker
# process crashes mid-scan without reaching the cleanup code.
import atexit as _atexit


def _cleanup_emitted_fingerprints():
    with _emitted_fingerprints_lock:
        _emitted_fingerprints.clear()

_atexit.register(_cleanup_emitted_fingerprints)


def _get_fingerprint_set(engagement_id: str) -> set[str]:
    """Get or create a per-engagement fingerprint dedup set."""
    with _emitted_fingerprints_lock:
        if engagement_id not in _emitted_fingerprints:
            _emitted_fingerprints[engagement_id] = set()
        return _emitted_fingerprints[engagement_id]

_streaming_tools: dict[str, dict] = {
    "dalfox": {"flag": "--json", "json_lines": True},
    "sqlmap": {"flag": "--output-format=json", "json_lines": False, "batch_json": True},
}


def _parse_line_buffer(ctx, tool_name, line_buffer, all_findings):
    """Parse accumulated JSON output from a streaming tool (e.g. sqlmap batch JSON)."""
    accumulated = "\n".join(line_buffer).strip()
    if not accumulated:
        return
    start = accumulated.find("{")
    end = accumulated.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = accumulated[start:end + 1]
    else:
        json_str = accumulated
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.log(5, f"{tool_name} accumulated output is not valid JSON")
        return
    items = data if isinstance(data, list) else [data]
    for item in items:
        if isinstance(item, dict):
            normalized = ctx._normalize_finding(item, tool_name)
            if normalized:
                fp = f"{normalized.get('type')}|{normalized.get('endpoint')}|{normalized.get('source_tool', tool_name)}"
                fps = _get_fingerprint_set(ctx.engagement_id)
                if fp in fps:
                    continue
                fps.add(fp)
                emit_finding_rt(ctx.engagement_id, normalized, tool_name)
                all_findings.append(normalized)


def _run_scan_tool(ctx, tool_name: str, args: list, timeout: int, all_findings: list,
                   on_line: callable | None = None,
                   line_buffer: list | None = None) -> tuple[str, bool, str | None]:
    """Thread-safe wrapper for running a scan tool.

    Findings are emitted in real-time via emit_finding_rt as each tool
    parses them, so analysts can start triaging critical findings while
    other tools are still running.

    If on_line is provided, uses run_streaming for real-time line processing.
    line_buffer is used for batch-JSON tools (sqlmap) that emit JSON at the end.
    """
    success = False
    try:
        emit_tool_start(ctx.engagement_id, tool_name, args)
        if on_line:
            result = ctx.tool_runner.run_streaming(tool_name, args, timeout, on_line)
            if line_buffer is not None and any(line_buffer):
                _parse_line_buffer(ctx, tool_name, line_buffer, all_findings)
            success = result.success
            return tool_name, success, result.stdout if success else None
        else:
            result = ctx.tool_runner.run(tool_name, args, timeout=timeout)
            if result.success and result.stdout:
                parsed = ctx.parser.parse(tool_name, result.stdout)
                for p in parsed:
                    normalized = ctx._normalize_finding(p, tool_name)
                    if normalized:
                        fp = f"{normalized.get('type')}|{normalized.get('endpoint')}|{normalized.get('source_tool', tool_name)}"
                        fps = _get_fingerprint_set(ctx.engagement_id)
                        if fp in fps:
                            continue
                        fps.add(fp)
                        emit_finding_rt(ctx.engagement_id, normalized, tool_name)
                        all_findings.append(normalized)
                success = True
            return tool_name, success, result.stdout if success else None
    except Exception as e:
        logger.warning(f"{tool_name} failed: {e}")
        return tool_name, False, None
    finally:
        emit_tool_complete(ctx.engagement_id, tool_name, success=success)


def execute_scan_tools(
    ctx, targets: list[str], budget: dict, aggressiveness: str = DEFAULT_AGGRESSIVENESS,
    auth_config: dict | None = None, dual_auth_config: dict | None = None,
    tech_stack: list[str] | None = None,
    skip_tools: set | None = None,
    recon_context=None,
) -> list[dict]:
    """
    Execute scanning tools against targets.

    Args:
        ctx: ToolContext or Orchestrator (provides tool_runner, parser, normalizer)
        targets: List of target URLs
        budget: Budget configuration
        aggressiveness: Scan aggressiveness level (default, high, extreme)
        auth_config: Optional authentication configuration for scanning
        tech_stack: Detected technology stack (triggers browser scanner for SPAs)

    Returns:
        List of findings
    """
    # Lazily get a ToolContext-aware wrapper
    if not hasattr(ctx, "publish_activity"):
        from tools.context import ToolContext

        ctx = ToolContext.from_orchestrator(ctx)

    slog = ScanLogger("scan_pipeline", engagement_id=getattr(ctx, 'engagement_id', ''))
    slog.phase_header("EXECUTE SCAN TOOLS", targets=f"{len(targets)} target(s)", aggressiveness=aggressiveness)
    # Clear per-engagement dedup fingerprints to prevent unbounded memory growth
    # across multiple execute_scan_tools invocations and cross-engagement pollution (H-v4-05).
    engagement_id = getattr(ctx, 'engagement_id', '')
    with _emitted_fingerprints_lock:
        _emitted_fingerprints.pop(engagement_id, None)
    all_findings = []
    # M-v5-04: Track temp output files for cleanup to prevent disk exhaustion.
    _temp_outputs: list[str] = []
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS
    _skip = set(skip_tools or [])

    # Guard against None targets list
    if not targets:
        logger.warning("execute_scan_tools called with empty/None targets list")
        slog.warn("No targets provided")
        return all_findings

    # Phase 0: Scope validation — filter targets before any tool execution.
    # This ensures the deterministic path enforces scope even when the agent
    # path is not active (previously scope was only checked in LLM agent path).
    engagement_id = getattr(ctx, 'engagement_id', '')
    if engagement_id and True:
        try:
            from tools.scope_validator import validate_target_scope
            scoped_targets = []
            blocked_targets = []
            for t in targets:
                if validate_target_scope(t, engagement_id):
                    scoped_targets.append(t)
                else:
                    blocked_targets.append(t)
                    slog.warn(f"Target {t} is out of scope — skipping")
            if blocked_targets:
                logger.warning(
                    "Scope filter blocked %d of %d targets for engagement %s",
                    len(blocked_targets), len(targets), engagement_id,
                )
            targets = scoped_targets
        except Exception as e:
            # L-06: Fail-closed — when scope validation is broken, do NOT
            # scan all targets. An error here likely means the scope DB is
            # unreachable or the validator is misconfigured, and scanning
            # without scope enforcement is a security risk.
            logger.error(
                "Scope validation FAILED (error): %s — aborting scan "
                "to prevent out-of-scope requests (L-06 fail-closed)",
                e,
            )
            slog.warn(f"Scope validation error — scan aborted: {e}")
            targets = []
    if not targets:
        slog.warn("All targets filtered by scope — nothing to scan")
        return all_findings

    # Auto-update nuclei templates once before scanning (not per-target)
    if _feature_enabled("nuclei_templates_auto_update"):
        try:
            from tools.update_nuclei_templates import (
                update_nuclei_templates as _update_templates,
            )
            _update_templates(timeout=120)
        except Exception as e:
            logger.warning(f"Nuclei template update failed (scan continues): {e}")

    # Cache nuclei templates path once before the loop
    nuclei_templates = get_nuclei_templates_path()
    templates_exist = nuclei_templates.exists() and any(
        nuclei_templates.rglob("*.yaml")
    )

    # Hoisted callback for streaming nuclei output (defined once, not per-target)
    def _on_nuclei_line(line: str):
        """Callback for streaming nuclei output.

        Findings are emitted in real-time as nuclei streams them,
        giving analysts visibility into each finding as it's discovered.

        Dedup: fingerprints by type+endpoint to prevent duplicate emissions
        when nuclei reports the same finding across multiple templates.
        """
        line = line.strip()
        if not line:
            return
        if not line.startswith("{"):
            return  # skip non-JSON progress lines
        try:
            finding = json.loads(line)
        except json.JSONDecodeError:
            logger.log(5, f"Nuclei skipped malformed JSON: {line[:200]}")
            return
        try:
            from parsers.schemas.nuclei_schema import validate_nuclei_finding
            validated = validate_nuclei_finding(finding)
            if validated:
                normalized = ctx._normalize_finding(validated, "nuclei")
                if normalized:
                    # In-flight dedup: check fingerprint before emitting
                    fp = f"{normalized.get('type')}|{normalized.get('endpoint')}|{normalized.get('source_tool', 'nuclei')}"
                    fps = _get_fingerprint_set(ctx.engagement_id)
                    if fp in fps:
                        return
                    fps.add(fp)
                    # Emit in real-time as nuclei streams findings
                    emit_finding_rt(ctx.engagement_id, normalized, "nuclei")
                    all_findings.append(normalized)
        except Exception as e:
            logger.warning(f"Nuclei streaming: failed to process line ({type(e).__name__}): {str(e)[:200]}")

    # Factory for per-tool streaming callbacks (captures ctx, all_findings via closure)
    def _make_on_tool_line(tool_name, json_lines=True, line_buffer=None):
        _json_acc = ""
        def on_tool_line(line: str) -> bool:
            nonlocal _json_acc
            line = line.strip()
            if not line:
                return True
            if json_lines:
                if _json_acc:
                    _json_acc += line
                elif line.startswith("{"):
                    _json_acc = line
                else:
                    return True
                try:
                    finding = json.loads(_json_acc)
                    _json_acc = ""
                except json.JSONDecodeError:
                    return True
                normalized = ctx._normalize_finding(finding, tool_name)
                if normalized:
                    fp = f"{normalized.get('type')}|{normalized.get('endpoint')}|{normalized.get('source_tool', tool_name)}"
                    fps = _get_fingerprint_set(ctx.engagement_id)
                    if fp in fps:
                        return True
                    fps.add(fp)
                    emit_finding_rt(ctx.engagement_id, normalized, tool_name)
                    all_findings.append(normalized)
            else:
                if line_buffer is not None:
                    line_buffer.append(line)
            return True
        return on_tool_line

    for target_idx, target in enumerate(targets):
        # Skip None/empty targets
        if not target:
            continue

        # Skip if target is unreachable (DNS NXDOMAIN/SERVFAIL only)
        if not _is_reachable(target):
            slog.info(f"Target {target} unreachable, skipping")
            continue

        slog.target_start(target, index=target_idx+1, total=len(targets))

        # Phase 1: arjun (parameter discovery) — must run first for injection tools
        if "arjun" not in _skip:
            try:
                import hashlib
                _target_slug = hashlib.md5(target.encode(), usedforsecurity=False).hexdigest()[:8]
                sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
                if sandbox:
                    sandbox.mkdir(parents=True, exist_ok=True)
                    arjun_out = str(sandbox / "tmp" / f"arjun_{_target_slug}.json")
                else:
                    import os
                    import tempfile
                    arjun_out = os.path.join(tempfile.gettempdir(), f"arjun_{_target_slug}.json")
                    _temp_outputs.append(arjun_out)
                arjun_threads = "20" if agg == "default" else "50" if agg == "high" else "100"
                arjun_timeout = TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG
                _run_scan_tool(ctx, "arjun",
                    ["-u", target, "-m", "GET", "-o", arjun_out, "-t", arjun_threads],
                    arjun_timeout, all_findings)
            except Exception as e:
                logger.warning(f"arjun failed for {target}: {e}")

        # Phase 1.5: WAF detection — run before vulnerability scanners
        if "wafw00f" not in _skip:
            try:
                waf_timeout = 120
                slog.tool_start("wafw00f", [target])
                waf_result = ctx.tool_runner.run("wafw00f", [target, "-a"], timeout=waf_timeout)
                if waf_result.success and waf_result.stdout:
                    logger.info("WAF detection results for %s: %s", target, waf_result.stdout[:500])
                    waf_finding = {
                        "type": "WAF_DETECTED",
                        "severity": "info",
                        "endpoint": target,
                        "evidence": {"raw_output": waf_result.stdout.strip()},
                        "source_tool": "wafw00f",
                    }
                    normalized = ctx._normalize_finding(waf_finding, "wafw00f")
                    if normalized:
                        emit_finding_rt(ctx.engagement_id, normalized, "wafw00f")
                        all_findings.append(normalized)
                slog.tool_complete("wafw00f", success=waf_result.success)
            except Exception as e:
                slog.tool_complete("wafw00f", success=False)
                logger.debug(f"wafw00f failed for {target}: {e}")

        # Phase 2: all vulnerability scanners run simultaneously
        scan_jobs = []

        # Budget enforcement: limit scan tools per target if budget specifies a cap
        max_tools = int(budget.get("max_scan_tools", 0)) if isinstance(budget, dict) else 0
        _tool_count = 0
        def _budget_exceeded():
            return max_tools > 0 and _tool_count >= max_tools

        # Build and run nuclei command with streaming (real-time findings)
        # L-18: Nuclei counts toward the budget like all other tools.
        if "nuclei" not in _skip and not _budget_exceeded():
            _tool_count += 1
            nuclei_cmd = ["-u", target, "-jsonl", "-silent"]
            if templates_exist:
                nuclei_cmd.extend(["-t", str(nuclei_templates)])
            nuclei_timeout = TOOL_TIMEOUT_LONG
            severity = NUCLEI_SEVERITY_BY_AGGRESSIVENESS.get(agg, NUCLEI_SEVERITY_BY_AGGRESSIVENESS['default'])
            nuclei_cmd.extend(["-severity", severity])
            nuclei_cmd.extend(_build_nuclei_tags(tech_stack, agg))
            if agg == "high":
                nuclei_timeout = 600
            elif agg == "extreme":
                nuclei_timeout = 1200

            try:
                emit_tool_start(ctx.engagement_id, "nuclei", nuclei_cmd)
                ctx.tool_runner.run_streaming("nuclei", nuclei_cmd, nuclei_timeout, _on_nuclei_line)
                emit_tool_complete(ctx.engagement_id, "nuclei", True, 0,
                                    finding_count=len([f for f in all_findings if f.get("source_tool") == "nuclei"]))
            except Exception as e:
                emit_tool_complete(ctx.engagement_id, "nuclei", False, 0)
                logger.warning(f"nuclei streaming failed for {target}: {e}")

        # Build dalfox command
        if "dalfox" not in _skip and not _budget_exceeded():
            _tool_count += 1
            dalfox_cmd = ["url", target, "--json"]
            dalfox_timeout = TOOL_TIMEOUT_LONG
            if agg == "high":
                dalfox_cmd.append("-b")
                dalfox_timeout = 600
            elif agg == "extreme":
                dalfox_cmd.extend(["-b", "--deep-dom"])
                dalfox_timeout = 1200
            scan_jobs.append(("dalfox", dalfox_cmd, dalfox_timeout))

        # Build sqlmap command
        if "sqlmap" not in _skip and not _budget_exceeded():
            _tool_count += 1
            import hashlib
            _target_slug = hashlib.md5(target.encode(), usedforsecurity=False).hexdigest()[:8]
            sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
            if sandbox:
                sandbox.mkdir(parents=True, exist_ok=True)
                sqlmap_out = str(sandbox / "tmp" / f"sqlmap_{_target_slug}.json")
            else:
                import os
                import tempfile
                sqlmap_out = os.path.join(tempfile.gettempdir(), f"sqlmap_{_target_slug}.json")
                _temp_outputs.append(sqlmap_out)
            sqlmap_cmd = ["-u", target, "--output-format=json", "--json-output", sqlmap_out]
            sqlmap_timeout = TOOL_TIMEOUT_LONG
            if agg == "high":
                sqlmap_cmd.extend(["--level", "3", "--risk", "2"])
                sqlmap_timeout = 600
            elif agg == "extreme":
                sqlmap_cmd.extend(["--level", "5", "--risk", "3", "--all"])
                sqlmap_timeout = 1800
            scan_jobs.append(("sqlmap", sqlmap_cmd, sqlmap_timeout))

        # Build jwt_tool command
        if "jwt_tool" not in _skip and not _budget_exceeded() and _should_run_tool("jwt_tool", recon_context=recon_context, tech_stack=tech_stack):
            _tool_count += 1
            scan_jobs.append(("jwt_tool", ["-u", target, "-C", "-d"], 120))

        # Build commix command
        if "commix" not in _skip and not _budget_exceeded() and _should_run_tool("commix", recon_context=recon_context, tech_stack=tech_stack):
            import hashlib
            _target_slug = hashlib.md5(target.encode(), usedforsecurity=False).hexdigest()[:8]
            sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
            if sandbox:
                sandbox.mkdir(parents=True, exist_ok=True)
                commix_out = str(sandbox / "tmp" / f"commix_{_target_slug}.json")
            else:
                import os
                import tempfile
                commix_out = os.path.join(tempfile.gettempdir(), f"commix_{_target_slug}.json")
                _temp_outputs.append(commix_out)
            scan_jobs.append(("commix",
                ["--url", target, "--batch", "--json-output", commix_out],
                TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG))

        # Build testssl command
        if "testssl" not in _skip and not _budget_exceeded() and _should_run_tool("testssl", target=target):
            import hashlib
            _target_slug = hashlib.md5(target.encode(), usedforsecurity=False).hexdigest()[:8]
            sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
            if sandbox:
                sandbox.mkdir(parents=True, exist_ok=True)
                testssl_out = str(sandbox / "tmp" / f"testssl_{_target_slug}.json")
            else:
                import os
                import tempfile
                testssl_out = os.path.join(tempfile.gettempdir(), f"testssl_{_target_slug}.json")
                _temp_outputs.append(testssl_out)
            scan_jobs.append(("testssl",
                ["--jsonfile", testssl_out, target],
                TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG))

        # Log any rate limit events detected during scanning
        rate_limit_repo = _get_rate_limit_repo()

        # Run all Phase 2 tools in parallel
        slog.info(f"Phase 2: Running {len(scan_jobs)} vulnerability scanners in parallel")
        if scan_jobs:
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {}
                for name, args, timeout in scan_jobs:
                    config = _streaming_tools.get(name)
                    if config:
                        line_buffer = [] if config.get("batch_json") else None
                        on_line = _make_on_tool_line(
                            name,
                            json_lines=config["json_lines"],
                            line_buffer=line_buffer,
                        )
                        future = pool.submit(
                            _run_scan_tool, ctx, name, args, timeout, all_findings,
                            on_line=on_line, line_buffer=line_buffer,
                        )
                    else:
                        future = pool.submit(
                            _run_scan_tool, ctx, name, args, timeout, all_findings,
                        )
                    futures[future] = name
                try:
                    for future in as_completed(futures, timeout=max(TOOL_TIMEOUT_LONG + 60, 900)):
                        tool_name = futures[future]
                        try:
                            future.result(timeout=30)
                        except Exception as e:
                            err_str = str(e).lower()
                            if rate_limit_repo and any(kw in err_str for kw in ["429", "rate limit", "too many requests"]):
                                try:
                                    rate_limit_repo.create_event(
                                        domain=target,
                                        event_type="tool_rate_limited",
                                        status_code=429,
                                        current_rps=0.0,
                                    )
                                except Exception as rl_err:
                                    logger.debug(f"Failed to log rate limit event: {rl_err}")
                            logger.warning(f"Scan tool {tool_name} error: {e}")
                except TimeoutError:
                    logger.warning("Scan tool batch timed out — some tools may not have completed")

        # Authenticate session if auth_config is provided
        authenticated_session = None
        if auth_config:
            try:
                from tools.auth_manager import AuthManager
                auth_manager = AuthManager(auth_config)
                authenticated_session = auth_manager.authenticate(target)
                logger.info(f"Authentication successful for {target}")
            except Exception as e:
                logger.warning(f"Authentication failed for {target}: {e}")

        # ── Real-time finding streamer ──
        # Normalizes and emits findings inline as each scanner discovers them,
        # rather than waiting for the tool to complete. This lets analysts start
        # triaging critical findings during active scanning.
        def _stream_finding(eng_id, finding, tool):
            normalized = ctx._normalize_finding(finding, tool)
            if normalized:
                fingerprint = f"{normalized.get('type')}|{normalized.get('endpoint')}|{normalized.get('source_tool', tool)}"
                fps = _get_fingerprint_set(eng_id)
                if fingerprint in fps:
                    return
                fps.add(fingerprint)
                emit_finding_rt(eng_id, normalized, tool)
                all_findings.append(normalized)

        # Execute comprehensive web scanner
        slog.tool_start("web_scanner", [target])
        try:
            web_scanner = WebScanner(
                timeout=SSL_TIMEOUT,
                rate_limit=RATE_LIMIT_DELAY_MS / 1000.0,
                llm_payload_generator=ctx.llm_payload_generator,
                session=authenticated_session,
                tech_stack=tech_stack,
                engagement_id=ctx.engagement_id,
                emit_finding_callback=_stream_finding,
            )
            emit_tool_start(ctx.engagement_id, "web_scanner", [target])
            web_findings = web_scanner.scan(target)

            # Log any rate limit findings detected by the web scanner
            if rate_limit_repo:
                for wf in web_findings:
                    wf_type = (wf.get("type") or "").upper()
                    if "RATE_LIMIT" in wf_type:
                        try:
                            rate_limit_repo.create_event(
                                domain=target,
                                event_type="web_scanner_rate_limit",
                                status_code=429,
                                current_rps=0.0,
                            )
                        except Exception as rl_err:
                            logger.debug(f"Failed to log rate limit event: {rl_err}")

            slog.tool_complete("web_scanner", success=True, findings=len(web_findings))
            # Findings already emitted inline via _stream_finding callback.
            # Batch loop below catches any that the callback missed (edge case).
            for wf in web_findings:
                normalized = ctx._normalize_finding(wf, "web_scanner")
                if normalized:
                    dedup_key = (normalized.get("type"), normalized.get("endpoint"))
                    if not any(
                        f.get("type") == dedup_key[0] and f.get("endpoint") == dedup_key[1]
                        for f in all_findings
                    ):
                        emit_finding_rt(ctx.engagement_id, normalized, "web_scanner")
                        all_findings.append(normalized)
        except Exception as e:
            slog.tool_complete("web_scanner", success=False)
            logger.warning(f"WebScanner failed for {target}: {e}")

        # DualAuthScanner — cross-account BOLA/BOPLA testing when dual_auth_config is provided
        if dual_auth_config is not None and auth_config is not None:
            slog.tool_start("dual_auth_scanner", [target])
            try:
                from tools.dual_auth_scanner import DualAuthScanner
                dual_scanner = DualAuthScanner(
                    auth_config_a=auth_config,
                    auth_config_b=dual_auth_config,
                    timeout=SSL_TIMEOUT,
                    rate_limit=RATE_LIMIT_DELAY_MS / 1000.0,
                    engagement_id=ctx.engagement_id,
                    emit_finding_callback=_stream_finding,
                )
                emit_tool_start(ctx.engagement_id, "dual_auth_scanner", [target])
                dual_findings = dual_scanner.scan(target)
                slog.tool_complete("dual_auth_scanner", success=True, findings=len(dual_findings))
                # Findings already emitted inline via _stream_finding callback
                # Collect any remaining that weren't streamed (backward compat)
                for df in dual_findings:
                    normalized = ctx._normalize_finding(df, "dual_auth_scanner")
                    if normalized:
                        # Dedup: only add if not already in all_findings (streamed inline)
                        dedup_key = (normalized.get("type"), normalized.get("endpoint"))
                        if not any(
                            f.get("type") == dedup_key[0] and f.get("endpoint") == dedup_key[1]
                            for f in all_findings
                        ):
                            emit_finding_rt(ctx.engagement_id, normalized, "dual_auth_scanner")
                            all_findings.append(normalized)
                emit_tool_complete(ctx.engagement_id, "dual_auth_scanner", True, 0,
                                    finding_count=len(dual_findings))
                logger.info(f"DualAuthScanner complete: {len(dual_findings)} findings for {target}")
            except Exception as e:
                slog.tool_complete("dual_auth_scanner", success=False)
                logger.warning(f"DualAuthScanner failed for {target}: {e}")

        # AIVulnScanner — prompt injection and AI information disclosure
        slog.tool_start("ai_vuln_scanner", [target])
        try:
            from tools.ai_vuln_scanner import AIVulnScanner
            ai_scanner = AIVulnScanner(
                timeout=SSL_TIMEOUT * 2,  # AI endpoints may be slower
                rate_limit=RATE_LIMIT_DELAY_MS / 1000.0,
                session=authenticated_session,
                engagement_id=ctx.engagement_id,
                emit_finding_callback=_stream_finding,
            )
            emit_tool_start(ctx.engagement_id, "ai_vuln_scanner", [target])
            ai_findings = ai_scanner.scan(target)
            slog.tool_complete("ai_vuln_scanner", success=True, findings=len(ai_findings))
            # Findings already emitted inline via _stream_finding callback
            # Collect any remaining that weren't streamed (backward compat)
            # L-05: Use fingerprint set for consistent dedup with other tools
            for af in ai_findings:
                normalized = ctx._normalize_finding(af, "ai_vuln_scanner")
                if normalized:
                    fp = f"{normalized.get('type')}|{normalized.get('endpoint')}|ai_vuln_scanner"
                    fps = _get_fingerprint_set(ctx.engagement_id)
                    if fp in fps:
                        continue
                    fps.add(fp)
                    emit_finding_rt(ctx.engagement_id, normalized, "ai_vuln_scanner")
                    all_findings.append(normalized)
            emit_tool_complete(ctx.engagement_id, "ai_vuln_scanner", True, 0,
                                finding_count=len(ai_findings))
            if ai_findings:
                logger.info(f"AIVulnScanner complete: {len(ai_findings)} findings for {target}")
        except Exception as e:
            slog.tool_complete("ai_vuln_scanner", success=False)
            logger.warning(f"AIVulnScanner failed for {target}: {e}")

        # WebSocketScanner — WebSocket security testing (origin validation, auth, injection, rate limiting)
        if _feature_enabled("WS_SCANNER", default=False):
            slog.tool_start("websocket_scanner", [target])
            try:
                from tools.websocket_scanner import WebSocketScanner
                ws_findings = []

                # Discover WebSocket URLs from the target page
                ws_urls = []
                try:
                    ws_urls = _run_async(WebSocketScanner.discover_websocket_urls(target))
                except Exception as disc_err:
                    logger.debug(f"WebSocket URL discovery failed for {target}: {disc_err}")

                if ws_urls:
                    slog.info(f"Discovered {len(ws_urls)} WebSocket URL(s) for {target}: {ws_urls}")
                    for ws_url in ws_urls:
                        try:
                            scanner = WebSocketScanner(timeout=SSL_TIMEOUT)
                            result = _run_async(scanner.scan(ws_url))
                            ws_findings.extend(result)
                        except RuntimeError as ws_err:
                            # Missing dependency (websockets or httpx) — skip gracefully
                            if "is required" in str(ws_err):
                                slog.info(f"WebSocket scanning skipped (missing dependency): {ws_err}")
                                break
                            logger.debug(f"WebSocket scan failed for {ws_url}: {ws_err}")
                        except Exception as ws_err:
                            logger.debug(f"WebSocket scan failed for {ws_url}: {ws_err}")
                else:
                    slog.info(f"No WebSocket URLs discovered for {target}")

                slog.tool_complete("websocket_scanner", success=True, findings=len(ws_findings))
                # L-04: Use fingerprint set for consistent dedup with other tools
                for wf in ws_findings:
                    normalized = ctx._normalize_finding(wf, "websocket_scanner")
                    if normalized:
                        fp = f"{normalized.get('type')}|{normalized.get('endpoint')}|websocket_scanner"
                        fps = _get_fingerprint_set(ctx.engagement_id)
                        if fp in fps:
                            continue
                        fps.add(fp)
                        emit_finding_rt(ctx.engagement_id, normalized, "websocket_scanner")
                        all_findings.append(normalized)
                emit_tool_complete(ctx.engagement_id, "websocket_scanner", True, 0,
                                   finding_count=len(ws_findings))
                if ws_findings:
                    logger.info(f"WebSocketScanner complete: {len(ws_findings)} findings for {target}")
            except Exception as e:
                slog.tool_complete("websocket_scanner", success=False)
                logger.warning(f"WebSocketScanner failed for {target}: {e}")

        slog.target_complete(target, findings=len(all_findings))

    # Clean up per-engagement RT fingerprints to prevent unbounded memory growth
    eng_id = getattr(ctx, 'engagement_id', '')
    if eng_id:
        clear_engagement_rt_fingerprints(eng_id)
        # Also clean up the in-memory dedup set to prevent leaks on crash
        with _emitted_fingerprints_lock:
            _emitted_fingerprints.pop(eng_id, None)

    # M-v5-04: Clean up temporary tool output files to prevent disk exhaustion.
    # These files are created by tools like arjun, sqlmap, commix, testssl when
    # no sandbox directory is available. Files in the sandbox are cleaned up by
    # the Orchestrator's atexit handler (M-v4-06).
    import os as _os
    for _tmp_path in _temp_outputs:
        try:
            if _os.path.exists(_tmp_path):
                _os.remove(_tmp_path)
                logger.debug("Cleaned up temp file: %s", _tmp_path)
        except Exception:
            logger.debug("Failed to clean up temp file: %s", _tmp_path)

    slog.info(f"Scan pipeline complete: {len(all_findings)} total findings across {len(targets)} targets")
    return all_findings

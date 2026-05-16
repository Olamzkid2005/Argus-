"""
Scan execution logic extracted from Orchestrator.
"""

import ipaddress
import json
import logging
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

from config.constants import (
    DEFAULT_AGGRESSIVENESS,
    RATE_LIMIT_DELAY_MS,
    SSL_TIMEOUT,
    TOOL_TIMEOUT_DEFAULT,
    TOOL_TIMEOUT_LONG,
)
from streaming import emit_tool_complete, emit_tool_start
from tools.web_scanner import WebScanner
from utils.logging_utils import ScanLogger

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
            for key, mapped_tags in TECH_TAG_MAP.items():
                if key in tech.lower():
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
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            logger.warning(f'Target {target} resolves to private IP {ip} — skipping')
            return False
        return True
    except ValueError:
        pass
    if hostname in ('localhost', '127.0.0.1', '::1'):
        logger.warning(f'Target {target} resolves to loopback — skipping')
        return False
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo(hostname, None)
        return True
    except socket.gaierror as e:
        if e.errno in (-2, -3):
            logger.warning(f'DNS: {hostname} not found — skipping')
            return False
        return True
    except Exception as e:
        logger.warning(f"DNS resolution for {hostname} failed with unexpected error — assuming reachable: {e}")
        return True


def _run_scan_tool(ctx, tool_name: str, args: list, timeout: int, all_findings: list) -> tuple[str, bool, str | None]:
    """Thread-safe wrapper for running a scan tool."""
    try:
        emit_tool_start(ctx.engagement_id, tool_name, args)
        result = ctx.tool_runner.run(tool_name, args, timeout=timeout)
        if result.success and result.stdout:
            parsed = ctx.parser.parse(tool_name, result.stdout)
            for p in parsed:
                normalized = ctx._normalize_finding(p, tool_name)
                if normalized:
                    all_findings.append(normalized)
        return tool_name, True, result.stdout
    except Exception as e:
        logger.warning(f"{tool_name} failed: {e}")
        return tool_name, False, None


def execute_scan_tools(
    ctx, targets: list[str], budget: dict, aggressiveness: str = DEFAULT_AGGRESSIVENESS,
    auth_config: dict | None = None, dual_auth_config: dict | None = None,
    tech_stack: list[str] | None = None,
    skip_tools: set | None = None,
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
    all_findings = []
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS
    _skip = set(skip_tools or [])

    # Guard against None targets list
    if not targets:
        logger.warning("execute_scan_tools called with empty/None targets list")
        slog.warn("No targets provided")
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
        """Callback for streaming nuclei output."""
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
                    all_findings.append(normalized)
        except Exception as e:
            logger.debug(f"Nuclei streaming: failed to process line ({type(e).__name__}): {str(e)[:200]}")

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
                sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
                if sandbox:
                    arjun_out = str(sandbox / "tmp" / "arjun.json")
                else:
                    import os
                    import tempfile
                    arjun_out = os.path.join(tempfile.gettempdir(), "arjun.json")
                arjun_threads = "20" if agg == "default" else "50" if agg == "high" else "100"
                arjun_timeout = TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG
                _run_scan_tool(ctx, "arjun",
                    ["-u", target, "-m", "GET", "-o", arjun_out, "-t", arjun_threads],
                    arjun_timeout, all_findings)
            except Exception as e:
                logger.warning(f"arjun failed for {target}: {e}")

        # Phase 2: all vulnerability scanners run simultaneously
        scan_jobs = []

        # Build and run nuclei command with streaming (real-time findings)
        if "nuclei" not in _skip:
            nuclei_cmd = ["-u", target, "-jsonl-export", "-", "-silent"]
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
            except Exception as e:
                logger.warning(f"nuclei streaming failed for {target}: {e}")

        # Build dalfox command
        if "dalfox" not in _skip:
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
        if "sqlmap" not in _skip:
            sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
            if sandbox:
                sqlmap_out = str(sandbox / "tmp" / "sqlmap.json")
            else:
                import os
                import tempfile
                sqlmap_out = os.path.join(tempfile.gettempdir(), "sqlmap.json")
            sqlmap_cmd = ["-u", target, "--json-output", sqlmap_out]
            sqlmap_timeout = TOOL_TIMEOUT_LONG
            if agg == "high":
                sqlmap_cmd.extend(["--level", "3", "--risk", "2"])
                sqlmap_timeout = 600
            elif agg == "extreme":
                sqlmap_cmd.extend(["--level", "5", "--risk", "3", "--all"])
                sqlmap_timeout = 1800
            scan_jobs.append(("sqlmap", sqlmap_cmd, sqlmap_timeout))

        # Build jwt_tool command
        if "jwt_tool" not in _skip and _should_run_tool("jwt_tool", tech_stack=tech_stack):
            scan_jobs.append(("jwt_tool", ["-u", target, "-C", "-d"], 120))

        # Build commix command
        if "commix" not in _skip and _should_run_tool("commix", tech_stack=tech_stack):
            sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
            if sandbox:
                commix_out = str(sandbox / "tmp" / "commix.json")
            else:
                import os
                import tempfile
                commix_out = os.path.join(tempfile.gettempdir(), "commix.json")
            scan_jobs.append(("commix",
                ["--url", target, "--batch", "--json-output", commix_out],
                TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG))

        # Build testssl command
        if "testssl" not in _skip and _should_run_tool("testssl", target=target):
            sandbox = ctx.tool_runner.sandbox_dir if hasattr(ctx.tool_runner, 'sandbox_dir') and ctx.tool_runner.sandbox_dir else None
            if sandbox:
                testssl_out = str(sandbox / "tmp" / "testssl.json")
            else:
                import os
                import tempfile
                testssl_out = os.path.join(tempfile.gettempdir(), "testssl.json")
            scan_jobs.append(("testssl",
                ["--jsonfile", testssl_out, target],
                TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG))

        # Run all Phase 2 tools in parallel
        if scan_jobs:
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {
                    pool.submit(_run_scan_tool, ctx, name, args, timeout, all_findings): name
                    for name, args, timeout in scan_jobs
                }
                try:
                    for future in as_completed(futures, timeout=max(TOOL_TIMEOUT_LONG + 60, 900)):
                        try:
                            future.result(timeout=30)
                        except Exception as e:
                            logger.warning(f"Scan tool {futures[future]} error: {e}")
                except TimeoutError:
                    logger.warning("Scan tool batch timed out — some tools may not have completed")

        slog.info(f"Phase 2: Running {len(scan_jobs)} vulnerability scanners in parallel")

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
            )
            emit_tool_start(ctx.engagement_id, "web_scanner", [target])
            web_findings = web_scanner.scan(target)

            slog.tool_complete("web_scanner", success=True, findings=len(web_findings))
            for wf in web_findings:
                normalized = ctx._normalize_finding(wf, "web_scanner")
                if normalized:
                    all_findings.append(normalized)
        except Exception as e:
            slog.tool_complete("web_scanner", success=False)
            logger.warning(f"WebScanner failed for {target}: {e}")

        # DualAuthScanner — cross-account BOLA/BOPLA testing when dual_auth_config is provided
        if dual_auth_config and auth_config:
            slog.tool_start("dual_auth_scanner", [target])
            try:
                from tools.dual_auth_scanner import DualAuthScanner
                dual_scanner = DualAuthScanner(
                    auth_config_a=auth_config,
                    auth_config_b=dual_auth_config,
                    timeout=SSL_TIMEOUT,
                    rate_limit=RATE_LIMIT_DELAY_MS / 1000.0,
                    engagement_id=ctx.engagement_id,
                )
                emit_tool_start(ctx.engagement_id, "dual_auth_scanner", [target])
                dual_findings = dual_scanner.scan(target)
                slog.tool_complete("dual_auth_scanner", success=True, findings=len(dual_findings))
                for df in dual_findings:
                    normalized = ctx._normalize_finding(df, "dual_auth_scanner")
                    if normalized:
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
            )
            emit_tool_start(ctx.engagement_id, "ai_vuln_scanner", [target])
            ai_findings = ai_scanner.scan(target)
            slog.tool_complete("ai_vuln_scanner", success=True, findings=len(ai_findings))
            for af in ai_findings:
                normalized = ctx._normalize_finding(af, "ai_vuln_scanner")
                if normalized:
                    all_findings.append(normalized)
            emit_tool_complete(ctx.engagement_id, "ai_vuln_scanner", True, 0,
                                finding_count=len(ai_findings))
            if ai_findings:
                logger.info(f"AIVulnScanner complete: {len(ai_findings)} findings for {target}")
        except Exception as e:
            slog.tool_complete("ai_vuln_scanner", success=False)
            logger.warning(f"AIVulnScanner failed for {target}: {e}")

        slog.target_complete(target, findings=len(all_findings))

    slog.info(f"Scan pipeline complete: {len(all_findings)} total findings across {len(targets)} targets")
    return all_findings

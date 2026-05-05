"""
Scan execution logic extracted from Orchestrator.
"""

import logging
import socket

from config.constants import (
    DEFAULT_AGGRESSIVENESS,
    RATE_LIMIT_DELAY_MS,
    SSL_TIMEOUT,
    TOOL_TIMEOUT_DEFAULT,
    TOOL_TIMEOUT_LONG,
)
from streaming import emit_tool_start
from tools.web_scanner import WebScanner

from .utils import get_nuclei_templates_path

logger = logging.getLogger(__name__)

NUCLEI_SEVERITY_BY_AGGRESSIVENESS = {
    'default': 'medium,high,critical',
    'high': 'low,medium,high,critical',
    'extreme': 'info,low,medium,high,critical',
}


def execute_scan_tools(
    ctx, targets: list[str], budget: dict, aggressiveness: str = DEFAULT_AGGRESSIVENESS,
    auth_config: dict | None = None, tech_stack: list[str] | None = None,
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

    all_findings = []
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS
    _skip = set(skip_tools or [])

    for target in targets:
        # Skip None/empty targets
        if not target:
            continue

        # Pre-resolve target to fail fast if DNS is broken
        hostname = target.replace("https://", "").replace("http://", "").split("/")[0]
        try:
            original_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5)
            try:
                socket.getaddrinfo(hostname, None)
            finally:
                socket.setdefaulttimeout(original_timeout)
        except socket.gaierror as e:
            logger.warning(
                f"DNS resolution failed for {hostname}: {e}. Skipping target."
            )
            continue

        # Auto-update nuclei templates if feature flag is enabled
        try:
            from feature_flags import is_enabled
            if is_enabled("nuclei_templates_auto_update"):
                from tools.update_nuclei_templates import update_nuclei_templates as _update_templates
                _update_templates(timeout=120)
        except Exception:
            pass  # Non-blocking — scan proceeds even if update fails

        # Get local nuclei templates path
        nuclei_templates = get_nuclei_templates_path()
        templates_exist = nuclei_templates.exists() and any(
            nuclei_templates.rglob("*.yaml")
        )

        # Execute Nuclei for vulnerability scanning
        try:
            nuclei_cmd = ["-u", target, "-jsonl-export", "-", "-silent"]

            # Use local templates if available
            if templates_exist:
                nuclei_cmd.extend(["-t", str(nuclei_templates)])
                logger.info(f"Using local nuclei templates from {nuclei_templates}")
            else:
                logger.warning(
                    "Nuclei templates not found. Scan will use default template download."
                )

            if "nuclei" in _skip: raise Exception("__skip__")
            nuclei_timeout = TOOL_TIMEOUT_LONG
            severity = NUCLEI_SEVERITY_BY_AGGRESSIVENESS.get(agg, NUCLEI_SEVERITY_BY_AGGRESSIVENESS['default'])
            nuclei_cmd.extend(["-severity", severity])
            if agg == "high":
                nuclei_timeout = 600
            elif agg == "extreme":
                nuclei_cmd.extend(["-tags", "fuzz"])
                nuclei_timeout = 1200
            emit_tool_start(ctx.engagement_id, "nuclei", nuclei_cmd)
            nuclei_result = ctx.tool_runner.run(
                "nuclei", nuclei_cmd, timeout=nuclei_timeout
            )
            # Debug: log nuclei result
            logger.warning(
                f"NUCLEI RESULT for {target}: success={nuclei_result.success}, returncode={nuclei_result.returncode}, stdout_len={len(nuclei_result.stdout)}, stderr={nuclei_result.stderr[:200]}"
            )

            if nuclei_result.success:
                stdout = nuclei_result.stdout
                parsed = ctx.parser.parse("nuclei", stdout)
                logger.warning(
                    f"NUCLEI PARSED: {len(parsed)} findings from {len(stdout)} bytes of output"
                )
                for p in parsed:
                    normalized = ctx._normalize_finding(p, "nuclei")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping nuclei (already ran via agent)")
            else:
                logger.warning(f"nuclei failed for {target}: {e}")

        # Execute dalfox for XSS
        try:
            dalfox_cmd = ["url", target, "--json"]
            if "dalfox" in _skip: raise Exception("__skip__")
            dalfox_timeout = TOOL_TIMEOUT_LONG
            if agg == "high":
                dalfox_cmd.append("-b")
                dalfox_timeout = 600
            elif agg == "extreme":
                dalfox_cmd.extend(["-b", "--deep-dom"])
                dalfox_timeout = 1200
            emit_tool_start(ctx.engagement_id, "dalfox", dalfox_cmd)
            dalfox_result = ctx.tool_runner.run(
                "dalfox", dalfox_cmd, timeout=dalfox_timeout
            )
            if dalfox_result.success:
                parsed = ctx.parser.parse("dalfox", dalfox_result.stdout)
                for p in parsed:
                    normalized = ctx._normalize_finding(p, "dalfox")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping dalfox (already ran via agent)")
            else:
                logger.warning(f"dalfox failed for {target}: {e}")

        # Execute sqlmap for SQL injection
        try:
            sqlmap_out = str(ctx.tool_runner.sandbox_dir / "tmp" / "sqlmap.json")
            sqlmap_cmd = ["-u", target, "--batch", "--json-output", sqlmap_out]
            if "sqlmap" in _skip: raise Exception("__skip__")
            sqlmap_timeout = TOOL_TIMEOUT_LONG
            if agg == "high":
                sqlmap_cmd.extend(["--level", "3", "--risk", "2"])
                sqlmap_timeout = 600
            elif agg == "extreme":
                sqlmap_cmd.extend(["--level", "5", "--risk", "3", "--all"])
                sqlmap_timeout = 1800
            emit_tool_start(ctx.engagement_id, "sqlmap", sqlmap_cmd)
            sqlmap_result = ctx.tool_runner.run(
                "sqlmap", sqlmap_cmd, timeout=sqlmap_timeout
            )
            if sqlmap_result.success:
                try:
                    with open(sqlmap_out) as f:
                        sqlmap_output = f.read()
                    parsed = ctx.parser.parse("sqlmap", sqlmap_output)
                except Exception:
                    parsed = []

                for p in parsed:
                    normalized = ctx._normalize_finding(p, "sqlmap")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping sqlmap (already ran via agent)")
            else:
                logger.warning(f"sqlmap failed for {target}: {e}")

        # Execute arjun for parameter discovery
        try:
            arjun_out = str(ctx.tool_runner.sandbox_dir / "tmp" / "arjun.json")
            if "arjun" in _skip: raise Exception("__skip__")
            arjun_threads = (
                "20" if agg == "default" else "50" if agg == "high" else "100"
            )
            arjun_timeout = (
                TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG
            )
            emit_tool_start(
                ctx.engagement_id,
                "arjun",
                ["-u", target, "-m", "GET", "-o", arjun_out, "-t", arjun_threads],
            )
            arjun_result = ctx.tool_runner.run(
                "arjun",
                ["-u", target, "-m", "GET", "-o", arjun_out, "-t", arjun_threads],
                timeout=arjun_timeout,
            )
            if arjun_result.success:
                try:
                    with open(arjun_out) as f:
                        arjun_output = f.read()
                    parsed = ctx.parser.parse("arjun", arjun_output)
                except Exception:
                    parsed = []

                for p in parsed:
                    normalized = ctx._normalize_finding(p, "arjun")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping arjun (already ran via agent)")
            else:
                logger.warning(f"arjun failed for {target}: {e}")

        # Execute jwt_tool for JWT vulnerability testing
        try:
            if "jwt_tool" in _skip: raise Exception("__skip__")
            emit_tool_start(ctx.engagement_id, "jwt_tool", ["-u", target, "-C", "-d"])
            jwt_result = ctx.tool_runner.run(
                "jwt_tool", ["-u", target, "-C", "-d"], timeout=120
            )
            if jwt_result.success:
                parsed = ctx.parser.parse("jwt_tool", jwt_result.stdout)
                for p in parsed:
                    normalized = ctx._normalize_finding(p, "jwt_tool")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping jwt_tool (already ran via agent)")
            else:
                logger.warning(f"jwt_tool failed for {target}: {e}")

        # Execute commix for command injection testing
        try:
            if "commix" in _skip: raise Exception("__skip__")
            commix_out = str(ctx.tool_runner.sandbox_dir / "tmp" / "commix.json")
            emit_tool_start(
                ctx.engagement_id,
                "commix",
                ["--url", target, "--batch", "--json-output", commix_out],
            )
            commix_result = ctx.tool_runner.run(
                "commix",
                ["--url", target, "--batch", "--json-output", commix_out],
                timeout=TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG,
            )
            if commix_result.success:
                try:
                    with open(commix_out) as f:
                        commix_output = f.read()
                    parsed = ctx.parser.parse("commix", commix_output)
                except Exception:
                    parsed = []

                for p in parsed:
                    normalized = ctx._normalize_finding(p, "commix")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping commix (already ran via agent)")
            else:
                logger.warning(f"commix failed for {target}: {e}")

        # Execute testssl for TLS vulnerability scanning
        try:
            if "testssl" in _skip: raise Exception("__skip__")
            testssl_out = str(ctx.tool_runner.sandbox_dir / "tmp" / "testssl.json")
            emit_tool_start(
                ctx.engagement_id,
                "testssl",
                ["--jsonfile", testssl_out, target],
            )
            testssl_result = ctx.tool_runner.run(
                "testssl",
                ["--jsonfile", testssl_out, target],
                timeout=TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG,
            )
            if testssl_result.success:
                try:
                    with open(testssl_out) as f:
                        testssl_output = f.read()
                    parsed = ctx.parser.parse("testssl", testssl_output)
                except Exception:
                    parsed = []

                for p in parsed:
                    normalized = ctx._normalize_finding(p, "testssl")
                    if normalized:
                        all_findings.append(normalized)
        except Exception as e:
            if "__skip__" in str(e):
                logger.info(f"Skipping testssl (already ran via agent)")
            else:
                logger.warning(f"testssl failed for {target}: {e}")

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
        try:
            web_scanner = WebScanner(
                timeout=SSL_TIMEOUT,
                rate_limit=RATE_LIMIT_DELAY_MS / 1000.0,
                llm_payload_generator=ctx.llm_payload_generator,
                session=authenticated_session,
                tech_stack=tech_stack,
            )
            emit_tool_start(ctx.engagement_id, "web_scanner", [target])
            web_findings = web_scanner.scan(target)

            for wf in web_findings:
                normalized = ctx._normalize_finding(wf, "web_scanner")
                if normalized:
                    all_findings.append(normalized)
        except Exception as e:
            logger.warning(f"WebScanner failed for {target}: {e}")

        # Browser-based SPA scanner (optional, triggered by tech_stack)
        if tech_stack:
            try:
                from tools.browser_scanner import is_spa_target, scan as browser_scan
                if is_spa_target(tech_stack):
                    emit_tool_start(ctx.engagement_id, "browser_scanner", [target])
                    logger.info(f"SPA detected — running browser scanner for {target}")
                    browser_findings = browser_scan(target)
                    for bf in browser_findings:
                        normalized = ctx._normalize_finding(bf, "browser_scanner")
                        if normalized:
                            all_findings.append(normalized)
                else:
                    logger.debug(f"No SPA framework in tech_stack, skipping browser scanner")
            except ImportError:
                logger.debug("Playwright not available, skipping browser scanner")
            except Exception as e:
                logger.warning(f"Browser scanner failed for {target}: {e}")

    return all_findings

"""
Reconnaissance execution logic extracted from Orchestrator.
"""
import logging
import socket
from typing import Dict, List

from config.constants import (
    DEFAULT_AGGRESSIVENESS,
    TOOL_TIMEOUT_DEFAULT,
    TOOL_TIMEOUT_LONG,
    TOOL_TIMEOUT_SHORT,
)
from streaming import emit_tool_start

from .utils import get_wordlist_path

logger = logging.getLogger(__name__)


def execute_recon_tools(orchestrator, target: str, budget: Dict, aggressiveness: str = DEFAULT_AGGRESSIVENESS) -> List[Dict]:
    """
    Execute reconnaissance tools against target.

    Args:
        orchestrator: Orchestrator instance (for tool_runner, parser, normalizer, ws_publisher, etc.)
        target: Target URL
        budget: Budget configuration
        aggressiveness: Scan aggressiveness level (default, high, extreme)

    Returns:
        List of findings
    """
    all_findings = []

    # Guard against None/empty target
    if not target:
        logger.warning(f"[execute_recon_tools] No valid target for engagement {orchestrator.engagement_id}, skipping recon")
        return []

    target_domain = target.replace("https://", "").replace("http://", "").split("/")[0]

    # Aggressiveness config
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS
    katana_depth = {"default": "3", "high": "5", "extreme": "7"}.get(agg, "3")
    naabu_ports = {"default": "-top-ports", "high": "-top-ports", "extreme": "-p-"}.get(agg, "-top-ports")
    naabu_port_val = {"default": "1000", "high": "10000", "extreme": "1-65535"}.get(agg, "1000")
    amass_mode = {"default": ["enum", "-d"], "high": ["enum", "-d"], "extreme": ["enum", "-d", "-brute", "-w"]}.get(agg, ["enum", "-d"])

    def _emit(tool: str, activity: str, status: str, items: int = None, details: str = None):
        orchestrator.ws_publisher.publish_scanner_activity(
            engagement_id=orchestrator.engagement_id,
            tool_name=tool,
            activity=activity,
            status=status,
            target=target_domain,
            items_found=items,
            details=details,
        )

    # Execute httpx for endpoint discovery
    _emit("httpx", "Discovering live endpoints and probing HTTP services", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "httpx", ["-u", target, "-json", "-silent"])
        httpx_result = orchestrator.tool_runner.run(
            "httpx",
            ["-u", target, "-json", "-silent"],
            timeout=TOOL_TIMEOUT_SHORT
        )
        parsed_count = 0
        if httpx_result.get("success"):
            parsed = orchestrator.parser.parse("httpx", httpx_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "httpx")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("httpx", "Live endpoint discovery complete", "completed", items=parsed_count)
    except Exception as e:
        _emit("httpx", f"Live endpoint discovery failed: {str(e)}", "failed")
        logger.warning(f"httpx failed: {e}")

    # Execute katana for web crawling
    _emit("katana", f"Crawling application routes and links up to depth {katana_depth}", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "katana", ["-u", target, "-jsonl", "-silent", "-d", katana_depth])
        katana_result = orchestrator.tool_runner.run(
            "katana",
            ["-u", target, "-jsonl", "-silent", "-d", katana_depth],
            timeout=TOOL_TIMEOUT_DEFAULT if agg == "extreme" else 120
        )
        parsed_count = 0
        if katana_result.get("success"):
            parsed = orchestrator.parser.parse("katana", katana_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "katana")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("katana", "Web crawling complete — mapped application surface", "completed", items=parsed_count)
    except Exception as e:
        _emit("katana", f"Web crawling failed: {str(e)}", "failed")
        logger.warning(f"katana failed: {e}")

    # Execute ffuf for fuzzing/directory discovery
    _emit("ffuf", f"Fuzzing directories ({agg} mode)", "started")
    try:
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
        emit_tool_start(orchestrator.engagement_id, "ffuf", ffuf_cmd)
        ffuf_result = orchestrator.tool_runner.run(
            "ffuf",
            ffuf_cmd,
            timeout=TOOL_TIMEOUT_LONG if agg == "extreme" else TOOL_TIMEOUT_DEFAULT
        )
        parsed_count = 0
        if ffuf_result.get("success"):
            parsed = orchestrator.parser.parse("ffuf", ffuf_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "ffuf")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("ffuf", "Directory fuzzing complete", "completed", items=parsed_count)
    except Exception as e:
        _emit("ffuf", f"Directory fuzzing failed: {str(e)}", "failed")
        logger.warning(f"ffuf failed: {e}")

    # Execute amass for subdomain enumeration
    amass_desc = "passive" if agg == "default" else "active + passive" if agg == "high" else "brute force + all sources"
    _emit("amass", f"Enumerating subdomains for {target_domain} ({amass_desc})", "started")
    try:
        amass_cmd = amass_mode + [target_domain, "-json"]
        amass_timeout = TOOL_TIMEOUT_LONG if agg == "default" else 600 if agg == "high" else 1200
        emit_tool_start(orchestrator.engagement_id, "amass", amass_cmd)
        amass_result = orchestrator.tool_runner.run(
            "amass",
            amass_cmd,
            timeout=amass_timeout
        )
        parsed_count = 0
        if amass_result.get("success"):
            parsed = orchestrator.parser.parse("amass", amass_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "amass")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("amass", f"Subdomain enumeration complete — found {parsed_count} subdomains", "completed", items=parsed_count)
    except Exception as e:
        _emit("amass", f"Subdomain enumeration failed: {str(e)}", "failed")
        logger.warning(f"amass failed: {e}")

    # Execute subfinder for additional subdomain enumeration (passive)
    _emit("subfinder", f"Enumerating subdomains via passive sources ({target_domain})", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "subfinder", ["-d", target_domain, "-silent"])
        subfinder_result = orchestrator.tool_runner.run(
            "subfinder",
            ["-d", target_domain, "-silent"],
            timeout=TOOL_TIMEOUT_SHORT
        )
        parsed_count = 0
        if subfinder_result.get("success"):
            parsed = orchestrator.parser.parse("subfinder", subfinder_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "subfinder")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("subfinder", f"Subdomain enumeration complete — found {parsed_count} subdomains", "completed", items=parsed_count)
    except Exception as e:
        _emit("subfinder", f"Subdomain enumeration failed: {str(e)}", "failed")
        logger.warning(f"subfinder failed: {e}")

    # Execute alterx for subdomain permutation generation
    _emit("alterx", f"Generating subdomain permutations for {target_domain}", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "alterx", ["-d", target_domain, "-silent"])
        alterx_result = orchestrator.tool_runner.run(
            "alterx",
            ["-d", target_domain, "-silent"],
            timeout=120
        )
        parsed_count = 0
        if alterx_result.get("success"):
            parsed = orchestrator.parser.parse("alterx", alterx_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "alterx")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("alterx", f"Permutation generation complete — generated {parsed_count} variants", "completed", items=parsed_count)
    except Exception as e:
        _emit("alterx", f"Permutation generation failed: {str(e)}", "failed")
        logger.warning(f"alterx failed: {e}")

    # Execute naabu for port scanning
    port_desc = "top 1000" if agg == "default" else "top 10,000" if agg == "high" else "full range 1-65535"
    _emit("naabu", f"Probing open ports on {target_domain} ({port_desc})", "started")
    try:
        naabu_cmd = ["-host", target_domain, "-json"]
        if naabu_ports == "-p-":
            naabu_cmd.append("-p-")
        else:
            naabu_cmd.extend(["-top-ports", naabu_port_val])
        naabu_timeout = 120 if agg == "default" else TOOL_TIMEOUT_LONG if agg == "high" else 900
        emit_tool_start(orchestrator.engagement_id, "naabu", naabu_cmd)
        naabu_result = orchestrator.tool_runner.run(
            "naabu",
            naabu_cmd,
            timeout=naabu_timeout
        )
        parsed_count = 0
        if naabu_result.get("success"):
            parsed = orchestrator.parser.parse("naabu", naabu_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "naabu")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("naabu", f"Port scan complete — found {parsed_count} open ports", "completed", items=parsed_count)
    except Exception as e:
        _emit("naabu", f"Port scan failed: {str(e)}", "failed")
        logger.warning(f"naabu failed: {e}")

    # Execute whatweb for technology fingerprinting
    _emit("whatweb", "Fingerprinting web technologies and server stack", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "whatweb", ["--format=json", target])
        whatweb_result = orchestrator.tool_runner.run(
            "whatweb",
            ["--format=json", target],
            timeout=120
        )
        parsed_count = 0
        if whatweb_result.get("success"):
            parsed = orchestrator.parser.parse("whatweb", whatweb_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "whatweb")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("whatweb", "Technology fingerprinting complete", "completed", items=parsed_count)
    except Exception as e:
        _emit("whatweb", f"Technology fingerprinting failed: {str(e)}", "failed")
        logger.warning(f"whatweb failed: {e}")

    # Execute nikto for web server scanning
    _emit("nikto", "Scanning web server for misconfigurations and known issues", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "nikto", ["-h", target, "-Format", "csv"])
        nikto_result = orchestrator.tool_runner.run(
            "nikto",
            ["-h", target, "-Format", "csv"],
            timeout=TOOL_TIMEOUT_LONG
        )
        parsed_count = 0
        if nikto_result.get("success"):
            parsed = orchestrator.parser.parse("nikto", nikto_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "nikto")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("nikto", "Web server scan complete", "completed", items=parsed_count)
    except Exception as e:
        _emit("nikto", f"Web server scan failed: {str(e)}", "failed")
        logger.warning(f"nikto failed: {e}")

    # Execute gau for known URLs
    _emit("gau", "Fetching known URLs from passive archives (gau)", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "gau", [target, "--json"])
        gau_result = orchestrator.tool_runner.run(
            "gau",
            [target, "--json"],
            timeout=TOOL_TIMEOUT_DEFAULT
        )
        parsed_count = 0
        if gau_result.get("success"):
            parsed = orchestrator.parser.parse("gau", gau_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "gau")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("gau", "Passive URL discovery complete", "completed", items=parsed_count)
    except Exception as e:
        _emit("gau", f"Passive URL discovery failed: {str(e)}", "failed")
        logger.warning(f"gau failed: {e}")

    # Execute waybackurls for historical URLs
    _emit("waybackurls", "Retrieving historical URLs from Wayback Machine", "started")
    try:
        emit_tool_start(orchestrator.engagement_id, "waybackurls", [target])
        wayback_result = orchestrator.tool_runner.run(
            "waybackurls",
            [target],
            timeout=120
        )
        parsed_count = 0
        if wayback_result.get("success"):
            parsed = orchestrator.parser.parse("waybackurls", wayback_result.get("stdout", ""))
            for p in parsed:
                normalized = orchestrator._normalize_finding(p, "waybackurls")
                if normalized:
                    all_findings.append(normalized)
                    parsed_count += 1
        _emit("waybackurls", "Historical URL retrieval complete", "completed", items=parsed_count)
    except Exception as e:
        _emit("waybackurls", f"Historical URL retrieval failed: {str(e)}", "failed")
        logger.warning(f"waybackurls failed: {e}")

    return all_findings

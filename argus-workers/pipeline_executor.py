"""
Pipeline Executor — numbered-step tool execution with explicit error handling.

Refactors the repetitive try/except pattern in orchestrator.py's
_execute_recon_tools and _execute_scan_tools into a reusable service
with numbered steps, specific ErrorCodes, and Result returns.

Each tool execution follows a numbered recipe:
  1. Emit start event
  2. Run tool via ToolRunner
  3. Check success — skip if failed
  4. Parse output
  5. Normalize findings
  6. Emit completion event
  7. Return findings or typed error

Usage:
    executor = PipelineExecutor(tool_runner, parser, normalizer, ws_publisher)
    results = await executor.execute_recon_tools(
        target="https://example.com",
        engagement_id="...",
        aggressiveness="default",
    )
    for result in results:
        if is_ok(result):
            findings.extend(result.value)
        else:
            logger.error(f"Step failed: {result.error}")

Stolen from: Shannon's numbered-step service pattern (AgentExecutionService.execute)
Plus: Shannon's Result<T,E> type for explicit error propagation.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any

from error_classifier import (
    ErrorCode,
    tag_error,
)
from feature_flags import is_enabled
from tools.models import ToolResult

logger = logging.getLogger(__name__)

# Tools that can run in parallel (longest-running, independent)
PARALLEL_RECON_TOOLS = {"httpx", "katana", "amass", "subfinder"}
PARALLEL_SCAN_TOOLS = {"nuclei", "dalfox"}

# ── Step result ──

class StepResult:
    """Result of a single numbered step execution."""

    def __init__(
        self,
        step_number: int,
        tool_name: str,
        success: bool,
        findings: list[dict[str, Any]] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
        error_code: ErrorCode | None = None,
    ):
        self.step_number = step_number
        self.tool_name = tool_name
        self.success = success
        self.findings = findings or []
        self.error = error
        self.duration_ms = duration_ms
        self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step_number,
            "tool": self.tool_name,
            "success": self.success,
            "findings_count": len(self.findings),
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_code": self.error_code.value if self.error_code else None,
        }


# ── Pipeline Executor ──

class PipelineExecutor:
    """Executes tool pipelines with numbered-step pattern.

    Each tool in a phase is executed as a numbered step with:
    - Its own try/except block
    - Specific ErrorCode on failure
    - Structured StepResult output
    - Consistent event emission
    """

    def __init__(
        self,
        tool_runner: Any,
        parser: Any,
        normalizer: Any,
        ws_publisher: Any,
        finding_repo: Any = None,
    ):
        self.tool_runner = tool_runner
        self.parser = parser
        self.normalizer = normalizer
        self.ws_publisher = ws_publisher
        self.finding_repo = finding_repo

    # ═══════════════════════════════════════════════════════════════
    # Phase executors — numbered-step orchestration
    # ═══════════════════════════════════════════════════════════════

    def execute_recon_tools(
        self,
        target: str,
        engagement_id: str,
        aggressiveness: str = "default",
    ) -> list[StepResult]:
        """Execute reconnaissance tools as numbered steps.

        Steps:
        1. httpx — live endpoint discovery
        2. katana — web crawling
        3. ffuf — directory fuzzing
        4. amass — subdomain enumeration
        4b. subfinder — passive subdomain enumeration
        4c. alterx — subdomain permutation generation
        5. naabu — port scanning
        6. whatweb — technology fingerprinting
        7. nikto — web server scanning
        8. gau — passive URL discovery
        9. waybackurls — historical URL retrieval

        Args:
            target: Target URL
            engagement_id: Engagement ID for event emission
            aggressiveness: Scan aggressiveness (default, high, extreme)

        Returns:
            List of StepResult objects (one per tool)
        """
        results: list[StepResult] = []
        target_domain = target.replace("https://", "").replace("http://", "").split("/")[0]
        agg = aggressiveness or "default"
        katana_depth = {"default": "3", "high": "5", "extreme": "7"}.get(agg, "3")

        # ── Parallel tools (httpx, katana, amass, subfinder) ──
        if is_enabled("PARALLEL_EXECUTION"):
            results.extend(self._execute_tools_parallel([
                ("httpx", lambda: self._exec_httpx(target, engagement_id, target_domain)),
                ("katana", lambda: self._exec_katana(target, engagement_id, target_domain, katana_depth)),
                ("amass", lambda: self._exec_amass(target_domain, engagement_id, agg)),
                ("subfinder", lambda: self._exec_subfinder(target_domain, engagement_id, agg)),
            ]))
        else:
            results.append(self._exec_httpx(target, engagement_id, target_domain))
            results.append(self._exec_katana(target, engagement_id, target_domain, katana_depth))
            results.append(self._exec_amass(target_domain, engagement_id, agg))
            results.append(self._exec_subfinder(target_domain, engagement_id, agg))

        # ── Sequential tools ──
        results.append(self._exec_ffuf(target, engagement_id, target_domain, agg))
        results.append(self._exec_alterx(target_domain, engagement_id, agg))
        results.append(self._exec_naabu(target_domain, engagement_id, agg))
        results.append(self._exec_whatweb(target, engagement_id, target_domain))
        results.append(self._exec_nikto(target, engagement_id, target_domain))
        results.append(self._exec_gau(target, engagement_id, target_domain))
        results.append(self._exec_waybackurls(target, engagement_id, target_domain))

        return results

    def execute_scan_tools(
        self,
        target: str,
        engagement_id: str,
        aggressiveness: str = "default",
    ) -> list[StepResult]:
        """Execute scanning tools as numbered steps.

        Steps:
        1. nuclei — vulnerability scanning
        2. dalfox — XSS scanning
        3. sqlmap — SQL injection
        4. arjun — parameter discovery
        5. jwt_tool — JWT testing
        6. commix — command injection
        7. testssl — TLS/SSL testing

        Args:
            target: Target URL
            engagement_id: Engagement ID for event emission
            aggressiveness: Scan aggressiveness (default, high, extreme)

        Returns:
            List of StepResult objects (one per tool)
        """
        results: list[StepResult] = []
        agg = aggressiveness or "default"

        # ── Parallel tools (nuclei, dalfox) ──
        if is_enabled("PARALLEL_EXECUTION"):
            results.extend(self._execute_tools_parallel([
                ("nuclei", lambda: self._exec_nuclei(target, engagement_id, agg)),
                ("dalfox", lambda: self._exec_dalfox(target, engagement_id, agg)),
            ]))
        else:
            results.append(self._exec_nuclei(target, engagement_id, agg))
            results.append(self._exec_dalfox(target, engagement_id, agg))

        # ── Sequential tools ──
        results.append(self._exec_sqlmap(target, engagement_id, agg))
        results.append(self._exec_arjun(target, engagement_id, agg))
        results.append(self._exec_jwt_tool(target, engagement_id))
        results.append(self._exec_commix(target, engagement_id, agg))
        results.append(self._exec_testssl(target, engagement_id, agg))

        return results

    # ═══════════════════════════════════════════════════════════════
    # Individual step implementations — each is a numbered step
    # ═══════════════════════════════════════════════════════════════

    def _exec_httpx(self, target: str, engagement_id: str, domain: str) -> StepResult:
        """Step 1: httpx — live endpoint discovery."""
        step = 1
        tool = "httpx"
        start = time.time()

        try:
            self._emit(engagement_id, tool, "Discovering live endpoints", "started", domain)
            result = self._run_tool(tool, ["-u", target, "-json", "-silent"])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Live endpoint discovery complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            err_code = ErrorCode.TOOL_EXECUTION_FAILED
            tag_error(e, err_code, f"httpx failed: {e}")
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=err_code, duration_ms=self._ms(start))

    def _exec_katana(self, target: str, engagement_id: str, domain: str, depth: str) -> StepResult:
        """Step 2: katana — web crawling."""
        step = 2
        tool = "katana"
        start = time.time()

        try:
            self._emit(engagement_id, tool, f"Crawling (depth {depth})", "started", domain)
            result = self._run_tool(tool, ["-u", target, "-jsonl", "-silent", "-d", depth])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Web crawling complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_ffuf(self, target: str, engagement_id: str, domain: str, agg: str) -> StepResult:
        """Step 3: ffuf — directory fuzzing."""
        step = 3
        tool = "ffuf"
        start = time.time()

        try:
            from orchestrator import get_wordlist_path
            self._emit(engagement_id, tool, f"Fuzzing directories ({agg} mode)", "started", domain)
            wordlist_map = {
                "default": str(get_wordlist_path("common.txt")),
                "high": str(get_wordlist_path("extended.txt")),
                "extreme": str(get_wordlist_path("comprehensive.txt")),
            }
            wordlist = wordlist_map.get(agg, str(get_wordlist_path("common.txt")))
            cmd = ["-u", f"{target}/FUZZ", "-w", wordlist, "-json"]
            if agg == "high":
                cmd.extend(["-t", "50"])
            elif agg == "extreme":
                cmd.extend(["-t", "100", "-mc", "all"])
            result = self._run_tool(tool, cmd)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Directory fuzzing complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_amass(self, domain: str, engagement_id: str, agg: str) -> StepResult:
        """Step 4: amass — subdomain enumeration."""
        step = 4
        tool = "amass"
        start = time.time()

        try:
            desc = "passive" if agg == "default" else "active" if agg == "high" else "brute force"
            self._emit(engagement_id, tool, f"Enumerating subdomains ({desc})", "started", domain)
            amass_mode = {"default": ["enum", "-d"], "high": ["enum", "-d"], "extreme": ["enum", "-d", "-brute", "-w"]}
            cmd = amass_mode.get(agg, ["enum", "-d"]) + [domain, "-json"]
            timeout = 600 if agg == "default" else 1200 if agg == "extreme" else 300
            result = self._run_tool(tool, cmd, timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Subdomain enumeration complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_subfinder(self, domain: str, engagement_id: str, agg: str) -> StepResult:
        """Step 4b: subfinder — passive subdomain enumeration."""
        step = 4
        tool = "subfinder"
        start = time.time()

        try:
            desc = "passive" if agg == "default" else "all sources" if agg == "high" else "all sources + aggressive"
            self._emit(engagement_id, tool, f"Enumerating subdomains ({desc})", "started", domain)
            cmd = ["-d", domain, "-silent"]
            if agg in ("high", "extreme"):
                cmd.append("-all")
            timeout = 300 if agg == "default" else 600
            result = self._run_tool(tool, cmd, timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Subdomain enumeration complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_alterx(self, domain: str, engagement_id: str, agg: str) -> StepResult:
        """Step 4c: alterx — subdomain permutation generation."""
        step = 4
        tool = "alterx"
        start = time.time()

        try:
            self._emit(engagement_id, tool, "Generating subdomain permutations", "started", domain)
            result = self._run_tool(tool, ["-d", domain, "-silent"], timeout=120)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Permutation generation complete — generated {count} variants", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_naabu(self, domain: str, engagement_id: str, agg: str) -> StepResult:
        """Step 5: naabu — port scanning."""
        step = 5
        tool = "naabu"
        start = time.time()

        try:
            port_desc = "top 1000" if agg == "default" else "top 10,000" if agg == "high" else "full range"
            self._emit(engagement_id, tool, f"Probing open ports ({port_desc})", "started", domain)
            cmd = ["-host", domain, "-json"]
            if agg == "extreme":
                cmd.append("-p-")
            else:
                port_val = "1000" if agg == "default" else "10000"
                cmd.extend(["-top-ports", port_val])
            timeout = 120 if agg == "default" else 600 if agg == "high" else 900
            result = self._run_tool(tool, cmd, timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Port scan complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_whatweb(self, target: str, engagement_id: str, domain: str) -> StepResult:
        """Step 6: whatweb — technology fingerprinting."""
        step = 6
        tool = "whatweb"
        start = time.time()

        try:
            self._emit(engagement_id, tool, "Fingerprinting technologies", "started", domain)
            result = self._run_tool(tool, ["--format=json", target])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Technology fingerprinting complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_nikto(self, target: str, engagement_id: str, domain: str) -> StepResult:
        """Step 7: nikto — web server scanning."""
        step = 7
        tool = "nikto"
        start = time.time()

        try:
            self._emit(engagement_id, tool, "Scanning web server", "started", domain)
            result = self._run_tool(tool, ["-h", target, "-Format", "csv"])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Web server scan complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_gau(self, target: str, engagement_id: str, domain: str) -> StepResult:
        """Step 8: gau — passive URL discovery."""
        step = 8
        tool = "gau"
        start = time.time()

        try:
            self._emit(engagement_id, tool, "Fetching known URLs (gau)", "started", domain)
            result = self._run_tool(tool, ["--json", target])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Passive URL discovery complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_waybackurls(self, target: str, engagement_id: str, domain: str) -> StepResult:
        """Step 9: waybackurls — historical URLs."""
        step = 9
        tool = "waybackurls"
        start = time.time()

        try:
            self._emit(engagement_id, tool, "Retrieving historical URLs", "started", domain)
            result = self._run_tool(tool, [target])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, "Historical URL retrieval complete", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_nuclei(self, target: str, engagement_id: str, agg: str) -> StepResult:
        """Step 1 (scan): nuclei — vulnerability scanning."""
        step = 1
        tool = "nuclei"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Scanning for vulnerabilities", "started", domain)
            cmd = ["-u", target, "-jsonl", "-", "-silent"]
            timeout = 600
            if agg == "high":
                cmd.extend(["-severity", "low,medium,high,critical"])
                timeout = 600
            elif agg == "extreme":
                cmd.extend(["-severity", "info,low,medium,high,critical", "-tags", "fuzz"])
                timeout = 1200
            result = self._run_tool(tool, cmd, timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Nuclei scan complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_dalfox(self, target: str, engagement_id: str, agg: str) -> StepResult:
        """Step 2 (scan): dalfox — XSS scanning."""
        step = 2
        tool = "dalfox"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Scanning for XSS vulnerabilities", "started", domain)
            cmd = [target, "--json"]
            timeout = 600
            if agg == "high":
                cmd.append("-b")
            elif agg == "extreme":
                cmd.extend(["-b", "--deep-dom"])
                timeout = 1200
            result = self._run_tool(tool, cmd, timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"XSS scan complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_sqlmap(self, target: str, engagement_id: str, agg: str) -> StepResult:
        """Step 3 (scan): sqlmap — SQL injection."""
        step = 3
        tool = "sqlmap"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Testing for SQL injection", "started", domain)
            cmd = ["-u", target, "--batch"]
            timeout = 600
            if agg == "high":
                cmd.extend(["--level", "3", "--risk", "2"])
            elif agg == "extreme":
                cmd.extend(["--level", "5", "--risk", "3", "--all"])
                timeout = 1800
            result = self._run_tool(tool, cmd, timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"SQL injection scan complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_arjun(self, target: str, engagement_id: str, agg: str) -> StepResult:
        """Step 4 (scan): arjun — parameter discovery."""
        step = 4
        tool = "arjun"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Discovering HTTP parameters", "started", domain)
            threads = "20" if agg == "default" else "50" if agg == "high" else "100"
            timeout = 300 if agg == "default" else 600
            result = self._run_tool(tool, ["-u", target, "-m", "GET", "-t", threads], timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Parameter discovery complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_jwt_tool(self, target: str, engagement_id: str) -> StepResult:
        """Step 5 (scan): jwt_tool — JWT testing."""
        step = 5
        tool = "jwt_tool"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Testing JWT security", "started", domain)
            result = self._run_tool(tool, ["-u", target, "-C", "-d"])
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"JWT testing complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_commix(self, target: str, engagement_id: str, agg: str) -> StepResult:
        """Step 6 (scan): commix — command injection."""
        step = 6
        tool = "commix"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Testing for command injection", "started", domain)
            timeout = 300 if agg == "default" else 600
            result = self._run_tool(tool, ["--url", target, "--batch"], timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"Command injection testing complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    def _exec_testssl(self, target: str, engagement_id: str, agg: str) -> StepResult:
        """Step 7 (scan): testssl — TLS/SSL testing."""
        step = 7
        tool = "testssl"
        start = time.time()
        domain = target.replace("https://", "").replace("http://", "").split("/")[0]

        try:
            self._emit(engagement_id, tool, "Testing TLS/SSL configuration", "started", domain)
            timeout = 300 if agg == "default" else 600
            result = self._run_tool(tool, [target], timeout=timeout)
            findings = self._parse_and_normalize(result, tool)
            count = len(findings)
            self._emit(engagement_id, tool, f"TLS/SSL testing complete — found {count}", "completed", domain, count)
            return StepResult(step, tool, True, findings, duration_ms=self._ms(start))
        except Exception as e:
            self._emit(engagement_id, tool, f"Failed: {e}", "failed", domain)
            return StepResult(step, tool, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED, duration_ms=self._ms(start))

    # ═══════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════

    def _execute_tools_parallel(self, tools: list[tuple[str, callable]]) -> list[StepResult]:
        """Run independent _exec_* methods concurrently using ThreadPoolExecutor.

        Falls back to sequential execution when PARALLEL_EXECUTION feature flag is disabled.

        Args:
            tools: List of (name, zero-arg-callable) tuples, each wrapping an _exec_* call
                   with captured arguments.

        Returns:
            List of StepResult objects (one per tool)
        """
        if not is_enabled("PARALLEL_EXECUTION"):
            return [fn() for _, fn in tools]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_map = {executor.submit(fn): name for name, fn in tools}
            results = []
            try:
                for future in concurrent.futures.as_completed(future_map, timeout=600):
                    name = future_map[future]
                    try:
                        results.append(future.result())
                    except Exception as e:
                        logger.error(f"Parallel tool {name} failed: {e}")
                        results.append(StepResult(0, name, False, error=str(e), error_code=ErrorCode.TOOL_EXECUTION_FAILED))
            except concurrent.futures.TimeoutError:
                logger.error("Parallel execution timed out after 600s — cancelling remaining futures")
                for future in future_map:
                    future.cancel()
        return results

    def _run_tool(self, tool_name: str, args: list[str], timeout: int | None = None) -> ToolResult:
        """Run a tool and return its result."""
        from config.constants import TOOL_TIMEOUT_DEFAULT
        return self.tool_runner.run(
            tool_name,
            args,
            timeout=timeout or TOOL_TIMEOUT_DEFAULT,
        )

    def _parse_and_normalize(self, result: ToolResult, tool: str) -> list[dict[str, Any]]:
        """Parse and normalize tool output into findings."""
        findings = []
        if result.success:
            stdout = result.stdout
            if stdout:
                parsed = self.parser.parse(tool, stdout)
                for p in parsed:
                    normalized = self._normalize(p, tool)
                    if normalized:
                        findings.append(normalized)
        return findings

    def _normalize(self, raw: dict[str, Any], tool: str) -> dict[str, Any] | None:
        """Normalize a raw finding."""
        try:
            finding = self.normalizer.normalize(raw, tool)
            return {
                "type": finding.type,
                "severity": finding.severity.value if hasattr(finding.severity, "value") else finding.severity,
                "endpoint": finding.endpoint,
                "evidence": finding.evidence,
                "confidence": finding.confidence,
                "source_tool": tool,
            }
        except Exception as e:
            logger.warning(f"Failed to normalize finding from {tool}: {e}")
            return None

    def _emit(self, engagement_id: str, tool: str, activity: str, status: str,
              domain: str = "", items: int | None = None):
        """Emit a scanner activity event."""
        self.ws_publisher.publish_scanner_activity(
            engagement_id=engagement_id,
            tool_name=tool,
            activity=activity,
            status=status,
            target=domain,
            items_found=items,
        )

    @staticmethod
    def _ms(start: float) -> int:
        """Calculate milliseconds since start time."""
        return int((time.time() - start) * 1000)

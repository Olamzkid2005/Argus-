"""
Tool Runner - Executes security tools safely in sandboxed environment

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 20.4, 21.1, 21.2, 22.1
"""
import subprocess
import os
import sys
import site
import tempfile
from typing import Dict, List, Optional, Set
from pathlib import Path
import time

from tracing import get_trace_id, StructuredLogger, ExecutionSpan
from database.repositories.tool_metrics_repository import ToolMetricsRepository
from tools.circuit_breaker import CircuitBreaker, CircuitOpenError, ToolCircuitBreakerManager


class SecurityException(Exception):
    """Raised when dangerous payload is detected"""
    pass


class ToolRunner:
    """
    Executes security tools with safety validation and sandboxing.
    MVP implementation uses subprocess with locked environment.
    """
    
    # Dangerous patterns that should be blocked
    DANGEROUS_PATTERNS = [
        "rm -rf",
        "rm -fr",
        "rm -r",
        "DROP TABLE",
        "DROP DATABASE",
        "DELETE FROM",
        "TRUNCATE",
        "; rm",
        "| rm",
        "&& rm",
        "$(rm",
        "`rm",
        ">/dev/",
        "curl",
        "wget",
        "nc ",
        "netcat",
        "/etc/passwd",
        "/etc/shadow",
        "mkfs",
        "dd if=",
        ":(){ :|:& };:",  # Fork bomb
    ]
    
    def __init__(self, sandbox_dir: Optional[str] = None, connection_string: str = None,
                 failure_threshold: int = 3, cooldown_seconds: int = 300,
                 engagement_id: str = None):
        """
        Initialize Tool Runner

        Args:
            sandbox_dir: Directory for tool execution (default: temp directory)
            connection_string: Database connection string for logging
            failure_threshold: Failures before circuit breaker opens (default: 3)
            cooldown_seconds: Circuit breaker cooldown (default: 300 = 5 min)
            engagement_id: Optional engagement ID for org-scoped metrics
        """
        self.engagement_id = engagement_id
        if sandbox_dir:
            self.sandbox_dir = Path(sandbox_dir)
            self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.sandbox_dir = Path(tempfile.mkdtemp(prefix="argus_sandbox_"))

        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)

        # Initialize metrics repository
        self.metrics_repo = ToolMetricsRepository(self.connection_string) if self.connection_string else None

        # Initialize per-tool circuit breakers for resilience
        self._circuit_breaker_mgr = ToolCircuitBreakerManager()
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
    
    def is_dangerous(self, tool: str, args: List[str]) -> bool:
        """
        Check if tool execution contains dangerous patterns
        
        Args:
            tool: Tool name/path
            args: Tool arguments
            
        Returns:
            True if dangerous pattern detected, False otherwise
        """
        # Check tool name against blocked tools (exact match only)
        BLOCKED_TOOLS = {"curl", "wget", "nc", "netcat"}
        if tool in BLOCKED_TOOLS:
            return True
        
        # Check args and full command for dangerous patterns
        # Patterns like "rm -rf" include the tool name, so we check both
        # the args alone and the combined command
        args_str = " ".join(args)
        full_command = f"{tool} {args_str}"
        for pattern in self.DANGEROUS_PATTERNS:
            pattern_lower = pattern.lower()
            if pattern_lower in args_str.lower() or pattern_lower in full_command.lower():
                return True
        
        return False
    
    def _locked_env(self, tool: str = "") -> Dict[str, str]:
        """
        Build the subprocess environment portably.

        PYTHONPATH is assembled from the live interpreter — never hardcoded paths.
        This survives Python upgrades and other machines.
        
        Args:
            tool: Tool name to determine if proxy should be stripped
        """
        venv_bin = str(Path(sys.executable).parent)

        # --- PYTHONPATH assembly ---
        python_paths: List[str] = []

        # 1. System / venv site-packages
        try:
            python_paths.extend(p for p in site.getsitepackages() if os.path.isdir(p))
        except AttributeError:
            pass  # getsitepackages() absent in some venv builds

        # 2. User site-packages (~/.local/lib/... or ~/Library/Python/...)
        user_site = site.getusersitepackages()
        if user_site and os.path.isdir(user_site):
            python_paths.append(user_site)

        # 3. Running interpreter's sys.path (catches editable installs, .pth files)
        python_paths.extend(p for p in sys.path if p and os.path.isdir(p))

        # Deduplicate while preserving order
        seen: Set[str] = set()
        unique_paths: List[str] = []
        for p in python_paths:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)

        # Tools that must NOT inherit proxy settings (they need full network access)
        no_proxy_tools = {"nuclei", "dalfox", "sqlmap", "httpx", "nikto", "nmap", "curl", "testssl", "arjun", "jwt_tool", "commix"}

        env = {
            "PATH": f"{venv_bin}:/Users/mac/go/bin:/usr/local/bin:/usr/bin:/bin",
            # Pass through HOME so tools (gitleaks, nmap, git, nuclei) can find
            # ~/.config/ and other user-level configuration. Do NOT override it.
            "HOME": os.environ.get("HOME", "/root"),
            "TMPDIR": str(self.sandbox_dir / "tmp"),
            "PYTHONPATH": os.pathsep.join(unique_paths),
            "PYTHONDONTWRITEBYTECODE": "1",
            # Suppress semgrep telemetry / version-check latency
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
        }
        
        # For web scanning tools, strip proxy so they can reach the internet
        # Semgrep will get proxy settings from parent environment (for validation fallback)
        if tool in no_proxy_tools:
            # Explicitly unset proxy vars - subprocess inherits parent env unless overridden
            env["HTTP_PROXY"] = ""
            env["HTTPS_PROXY"] = ""
            env["http_proxy"] = ""
            env["https_proxy"] = ""
            env["no_proxy"] = "*"  # belt-and-suspenders
        
        return env
    
    def _validate_tool_name(self, tool: str) -> str:
        """Validate tool name does not contain path traversal or shell metacharacters."""
        if not tool or "/" in tool or "\\" in tool or ".." in tool:
            raise SecurityException(
                f"Invalid tool name blocked (path traversal): {tool!r}"
            )
        return tool

    def _resolve_tool_path(self, tool: str) -> str:
        """
        Resolve the full path to a tool binary by checking common locations
        and the current environment PATH.
        
        Args:
            tool: Tool name (e.g., 'nuclei', 'httpx')
            
        Returns:
            Full path to the tool binary, or the tool name if not found
        """
        self._validate_tool_name(tool)
        import shutil
        
        # Build a comprehensive PATH that includes venv/bin and ~/go/bin
        # so tools installed via pip or go install are always findable
        venv_bin = str(Path(sys.executable).parent)
        go_bin = os.path.expanduser("~/go/bin")
        # Also check the project's explicit venv bin (in case system python is used)
        project_venv_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "venv", "bin"))
        extra_paths = [venv_bin, project_venv_bin, go_bin, "/usr/local/bin", "/opt/homebrew/bin"]
        
        current_path = os.environ.get("PATH", "")
        for p in extra_paths:
            if p not in current_path:
                current_path = f"{p}:{current_path}"
        
        # Search the augmented PATH
        resolved = shutil.which(tool, path=current_path)
        if resolved:
            return resolved
        
        # Direct file check as final fallback
        for d in extra_paths:
            candidate = os.path.join(d, tool)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return tool

    def run(
        self,
        tool: str,
        args: List[str],
        timeout: int = 180
    ) -> Dict:
        """
        Execute tool with safety validation
        
        Args:
            tool: Tool name/path to execute
            args: List of arguments
            timeout: Timeout in seconds (default: 60)
            
        Returns:
            Dictionary with stdout, stderr, returncode, tool
            
        Raises:
            SecurityException: If dangerous payload detected
            subprocess.TimeoutExpired: If execution times out
        """
        # Safety check
        if self.is_dangerous(tool, args):
            raise SecurityException(
                f"Blocked dangerous payload: {tool} {' '.join(args)}"
            )
        
        # Create temp directory if it doesn't exist
        tmp_dir = self.sandbox_dir / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        
        # Record start time
        start_time = time.time()
        
        # Execute with span tracing
        with self.span_recorder.span(ExecutionSpan.SPAN_TOOL_EXECUTION, {"tool": tool}):
            # Get env with tool-specific proxy settings
            env = self._locked_env(tool)
            
            # Resolve tool binary path for tools not in locked PATH
            tool_path = self._resolve_tool_path(tool)
            
            try:
                # Execute with locked environment
                result = subprocess.run(
                    [tool_path] + args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.sandbox_dir),
                    env=env
                )
                
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Determine success
                # Tool-specific exit codes that mean "findings present, not an error"
                FINDINGS_EXIT_CODES = {
                    "semgrep":  {1},
                    "bandit":   {1},
                    "gitleaks": {1},
                    "dalfox":   {1},
                }
                success = (result.returncode == 0 or 
                          result.returncode in FINDINGS_EXIT_CODES.get(tool, set()))
                
                # Record tool metrics (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=success,
                            engagement_id=self.engagement_id
                        )
                    except Exception as metric_error:
                        # Don't fail execution if metrics recording fails
                        print(f"Warning: Failed to record tool metric: {metric_error}")
                
                # Log tool execution
                try:
                    self.logger.log_tool_executed(
                        tool_name=tool,
                        arguments=args,
                        duration_ms=duration_ms,
                        success=success,
                        return_code=result.returncode
                    )
                except Exception as log_err:
                    logger.warning("Failed to log tool execution: %s", log_err)
                
                return {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "tool": tool,
                    "success": success,
                    "duration_ms": duration_ms,
                    "timeout": False,
                    "error": None,
                    "trace_id": get_trace_id(),
                }
                
            except subprocess.TimeoutExpired:
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Record tool metrics for timeout (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=False,
                            engagement_id=self.engagement_id
                        )
                    except Exception as metric_error:
                        print(f"Warning: Failed to record tool metric: {metric_error}")
                
                # Log timeout
                self.logger.log_tool_executed(
                    tool_name=tool,
                    arguments=args,
                    duration_ms=duration_ms,
                    success=False,
                    return_code=-1
                )
                
                return {
                    "stdout": "",
                    "stderr": f"Tool execution timed out after {timeout} seconds",
                    "returncode": -1,
                    "tool": tool,
                    "success": False,
                    "duration_ms": duration_ms,
                    "timeout": True,
                    "error": None,
                    "trace_id": get_trace_id(),
                }
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Record tool metrics for error (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=False,
                            engagement_id=self.engagement_id
                        )
                    except Exception as metric_error:
                        print(f"Warning: Failed to record tool metric: {metric_error}")
                
                # Log error
                self.logger.log_tool_executed(
                    tool_name=tool,
                    arguments=args,
                    duration_ms=duration_ms,
                    success=False,
                    return_code=-1
                )
                
                return {
                    "stdout": "",
                    "stderr": str(e),
                    "returncode": -1,
                    "tool": tool,
                    "success": False,
                    "duration_ms": duration_ms,
                    "timeout": False,
                    "error": str(e),
                    "trace_id": get_trace_id(),
                }
    
    def run_nuclei(
        self,
        target: str,
        templates_path: Optional[str] = None,
        severity: Optional[str] = None,
        tags: Optional[str] = None,
        timeout: int = 600,
    ) -> Dict:
        """
        Execute Nuclei with optional template path and filters
        
        Args:
            target: Target URL or host
            templates_path: Path to custom Nuclei templates directory
            severity: Comma-separated severity levels (info,low,medium,high,critical)
            tags: Comma-separated tags to filter templates
            timeout: Execution timeout in seconds
            
        Returns:
            Tool execution result dictionary
        """
        args = ["-u", target, "-json", "-silent"]
        
        if templates_path:
            args.extend(["-t", templates_path])
        
        if severity:
            args.extend(["-severity", severity])
        
        if tags:
            args.extend(["-tags", tags])
        
        return self.run("nuclei", args, timeout=timeout)
    
    def run_naabu(
        self,
        target: str,
        top_ports: Optional[str] = None,
        port_range: Optional[str] = None,
        timeout: int = 300,
    ) -> Dict:
        """
        Execute Naabu port scanner
        
        Args:
            target: Target host or IP
            top_ports: Number of top ports to scan (e.g., "1000")
            port_range: Specific port range (e.g., "1-65535")
            timeout: Execution timeout in seconds
            
        Returns:
            Tool execution result dictionary
        """
        args = ["-host", target, "-json"]
        
        if port_range:
            args.extend(["-p", port_range])
        elif top_ports:
            args.extend(["-top-ports", top_ports])
        
        return self.run("naabu", args, timeout=timeout)
    
    def run_gospider(
        self,
        target: str,
        depth: int = 3,
        timeout: int = 300,
    ) -> Dict:
        """
        Execute Gospider for JavaScript file and endpoint discovery
        
        Args:
            target: Target URL
            depth: Crawling depth
            timeout: Execution timeout in seconds
            
        Returns:
            Tool execution result dictionary
        """
        args = ["-s", target, "-q", "-j", "-d", str(depth)]
        return self.run("gospider", args, timeout=timeout)
    
    def run_wpscan(
        self,
        target: str,
        api_token: Optional[str] = None,
        enumerate_options: Optional[List[str]] = None,
        timeout: int = 600,
    ) -> Dict:
        """
        Execute WPScan for WordPress security scanning
        
        Args:
            target: Target WordPress URL
            api_token: WPScan API token for vulnerability database access
            enumerate_options: List of enumeration options (e.g., ["p", "t", "u"])
            timeout: Execution timeout in seconds
            
        Returns:
            Tool execution result dictionary
        """
        args = ["--url", target, "-f", "json", "--no-banner"]
        
        if api_token:
            args.extend(["--api-token", api_token])
        
        if enumerate_options:
            for opt in enumerate_options:
                args.extend(["--enumerate", opt])
        
        return self.run("wpscan", args, timeout=timeout)
    
    def cleanup(self):
        """Clean up sandbox directory"""
        import shutil
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)

    def is_tool_available(self, tool: str) -> bool:
        """
        Check if a tool is currently available (circuit not open).

        Args:
            tool: Tool name to check

        Returns:
            True if tool can be called, False if circuit is open
        """
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        return breaker.is_available()

    def get_circuit_state(self, tool: str = "") -> str:
        """Get the current circuit breaker state for a tool."""
        if tool:
            breaker = self._circuit_breaker_mgr.get_breaker(
                tool, self._failure_threshold, self._cooldown_seconds
            )
            return breaker.state.value
        return "unknown"

    def record_tool_success(self, tool: str):
        """Record successful tool execution."""
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        breaker.record_success()

    def record_tool_failure(self, tool: str):
        """Record failed tool execution."""
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        breaker.record_failure()

    def run_with_circuit_breaker(
        self,
        tool: str,
        args: List[str],
        timeout: int = 180
    ) -> Dict:
        """
        Execute tool with circuit breaker protection.

        If the circuit is open, raises CircuitOpenError.

        Args:
            tool: Tool name/path to execute
            args: List of arguments
            timeout: Timeout in seconds

        Returns:
            Dictionary with stdout, stderr, returncode, tool

        Raises:
            CircuitOpenError: If circuit breaker is open
            SecurityException: If dangerous payload detected
        """
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        if not breaker.is_available():
            raise CircuitOpenError(
                f"Circuit breaker is OPEN for tool '{tool}'. "
                f"Wait {breaker._time_until_retry():.0f}s before retry."
            )

        try:
            result = self.run(tool, args, timeout)
            breaker.record_success()
            return result
        except SecurityException:
            # Safety successes should not count as failures
            raise
        except Exception as e:
            breaker.record_failure()
            raise

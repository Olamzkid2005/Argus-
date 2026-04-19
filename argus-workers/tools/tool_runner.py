"""
Tool Runner - Executes security tools safely in sandboxed environment

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 20.4, 21.1, 21.2, 22.1
"""
import subprocess
import os
import tempfile
from typing import Dict, List, Optional
from pathlib import Path
import time

from tracing import get_trace_id, StructuredLogger, ExecutionSpan
from database.repositories.tool_metrics_repository import ToolMetricsRepository


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
    
    def __init__(self, sandbox_dir: Optional[str] = None, connection_string: str = None):
        """
        Initialize Tool Runner
        
        Args:
            sandbox_dir: Directory for tool execution (default: temp directory)
            connection_string: Database connection string for logging
        """
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
    
    def is_dangerous(self, tool: str, args: List[str]) -> bool:
        """
        Check if tool execution contains dangerous patterns
        
        Args:
            tool: Tool name/path
            args: Tool arguments
            
        Returns:
            True if dangerous pattern detected, False otherwise
        """
        # Combine tool and args into single string for pattern matching
        command_str = f"{tool} {' '.join(args)}"
        
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.lower() in command_str.lower():
                return True
        
        return False
    
    def _locked_env(self) -> Dict[str, str]:
        """
        Return minimal locked environment variables
        
        Returns:
            Dictionary of environment variables
        """
        # Include venv bin path for installed tools (semgrep, etc.)
        venv_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "venv", "bin")
        return {
            "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.sandbox_dir),
            "TMPDIR": str(self.sandbox_dir / "tmp"),
            "LANG": "en_US.UTF-8",
        }
    
    def run(
        self,
        tool: str,
        args: List[str],
        timeout: int = 60
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
            try:
                # Execute with locked environment
                result = subprocess.run(
                    [tool] + args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.sandbox_dir),
                    env=self._locked_env()
                )
                
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Determine success
                success = result.returncode == 0
                
                # Record tool metrics (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=success
                        )
                    except Exception as metric_error:
                        # Don't fail execution if metrics recording fails
                        print(f"Warning: Failed to record tool metric: {metric_error}")
                
                # Log tool execution
                self.logger.log_tool_executed(
                    tool_name=tool,
                    arguments=args,
                    duration_ms=duration_ms,
                    success=success,
                    return_code=result.returncode
                )
                
                return {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "tool": tool,
                    "success": success,
                    "duration_ms": duration_ms,
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
                            success=False
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
                    "timeout": True,
                    "duration_ms": duration_ms,
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
                            success=False
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
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "trace_id": get_trace_id(),
                }
    
    def cleanup(self):
        """Clean up sandbox directory"""
        import shutil
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)

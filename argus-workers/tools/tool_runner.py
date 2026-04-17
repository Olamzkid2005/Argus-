"""
Tool Runner - Executes security tools safely in sandboxed environment
"""
import subprocess
import os
import tempfile
from typing import Dict, List, Optional
from pathlib import Path


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
    
    def __init__(self, sandbox_dir: Optional[str] = None):
        """
        Initialize Tool Runner
        
        Args:
            sandbox_dir: Directory for tool execution (default: temp directory)
        """
        if sandbox_dir:
            self.sandbox_dir = Path(sandbox_dir)
            self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.sandbox_dir = Path(tempfile.mkdtemp(prefix="argus_sandbox_"))
    
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
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
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
            
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "tool": tool,
                "success": result.returncode == 0,
            }
            
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"Tool execution timed out after {timeout} seconds",
                "returncode": -1,
                "tool": tool,
                "success": False,
                "timeout": True,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "tool": tool,
                "success": False,
                "error": str(e),
            }
    
    def cleanup(self):
        """Clean up sandbox directory"""
        import shutil
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)

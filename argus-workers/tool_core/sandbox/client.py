"""Docker-based sandbox client for isolated command execution.

SandboxClient spawns disposable Docker containers for running commands
in a secure, isolated environment with resource limits. Falls back to
subprocess execution when Docker is unavailable.

Typical usage:
    from tool_core.sandbox.client import SandboxClient

    client = SandboxClient(timeout=30)
    result = client.run_command(["curl", "http://example.com"])
    if result.returncode == 0:
        print(f"Output: {result.stdout}")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of a sandbox command execution.

    Attributes:
        returncode: Process exit code (None if execution failed before starting).
        stdout: Captured standard output text.
        stderr: Captured standard error text.
        error: Error message if execution failed (None on success).
        timed_out: True if the command was killed due to timeout.
    """

    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    timed_out: bool = False


class SandboxClient:
    """Spawns disposable Docker containers for isolated command execution.

    Each ``run_command()`` call creates a new ephemeral container that is
    automatically removed after execution. The container has:
    - No network access (``network_disabled=True``)
    - Read-only root filesystem (``read_only=True``)
    - 256 MB memory limit
    - 50 process limit (prevents fork bombs)
    - No privileges or capabilities

    When Docker is unavailable (not installed or daemon not reachable),
    automatically falls back to subprocess-based execution with locked-down
    environment variables.

    Args:
        image: Docker image name (default from SANDBOX_IMAGE env var or
            ``argus-sandbox:latest``).
        docker_host: Docker daemon URL (default from DOCKER_HOST env var).
        timeout: Default timeout in seconds for container execution.
    """

    def __init__(
        self,
        image: str | None = None,
        docker_host: str | None = None,
        timeout: int = 60,
    ):
        self.image = image or os.environ.get("SANDBOX_IMAGE", "argus-sandbox:latest")
        self.docker_host = docker_host or os.environ.get("DOCKER_HOST")
        self.timeout = timeout
        self._client: Any = None  # docker.DockerClient, lazily initialized

    @property
    def client(self) -> Any:
        """Lazily initialize the Docker client."""
        if self._client is None:
            import docker
            kwargs = {}
            if self.docker_host:
                kwargs["base_url"] = self.docker_host
            self._client = docker.from_env(**kwargs)
        return self._client

    @property
    def is_docker_available(self) -> bool:
        """Check if a Docker host is reachable via the Docker SDK.

        Does NOT check for the ``docker`` CLI binary — ``docker-py``
        communicates with the daemon via socket/TCP, not through the CLI.

        Returns:
            True if Docker daemon is reachable and responds to ping.
        """
        try:
            return self.client.ping()
        except Exception:
            return False

    def run_command(
        self,
        command: list[str],
        timeout: int = 30,
        input_data: str | None = None,
    ) -> SandboxResult:
        """Run a command inside a disposable sandbox container.

        Falls back to subprocess if Docker is unavailable.

        Args:
            command: Command and arguments as a list (e.g., ``["echo", "hello"]``).
            timeout: Max execution time in seconds.
            input_data: Optional stdin string to pass to the command.

        Returns:
            SandboxResult with returncode, stdout, stderr, or error.
            Access fields as attributes (``result.returncode``), not dict-style.
        """
        if self.is_docker_available:
            return self._run_docker(command, timeout, input_data)
        logger.warning(
            "Docker not available — falling back to subprocess sandbox. "
            "Install Docker for full isolation."
        )
        return self._run_subprocess(command, timeout, input_data)

    def _run_docker(
        self,
        command: list[str],
        timeout: int,
        input_data: str | None,
    ) -> SandboxResult:
        """Run command in ephemeral Docker container."""
        import docker

        payload = json.dumps({
            "command": command,
            "timeout": timeout,
            "input": input_data,
        })
        try:
            container_output = self.client.containers.run(
                image=self.image,
                command=["python3", "/usr/local/bin/sandbox_runner.py"],
                input=payload.encode(),
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": "size=64M"},
                mem_limit="256m",
                memswap_limit="256m",
                cpu_period=100000,
                cpu_quota=50000,
                pids_limit=50,
                auto_remove=True,
                detach=False,
                timeout=self.timeout,
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
            )
            result = json.loads(container_output.decode())
            return SandboxResult(
                returncode=result.get("returncode"),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                error=result.get("error"),
                timed_out=result.get("error") == "timeout",
            )
        except docker.errors.ContainerError as e:
            return SandboxResult(error=f"Container error: {e}")
        except json.JSONDecodeError:
            return SandboxResult(error="Failed to parse container output as JSON")
        except Exception as e:
            return SandboxResult(error=str(e))

    def _run_subprocess(
        self,
        command: list[str],
        timeout: int,
        input_data: str | None,
    ) -> SandboxResult:
        """Fallback: subprocess-based execution (less secure)."""
        import subprocess

        # Build locked-down environment
        env = os.environ.copy()
        blocked_keys = {
            "DATABASE_URL", "REDIS_URL",
            "OPENAI_API_KEY", "LLM_API_KEY", "LLM_API_KEYS",
            "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
            "AWS_ACCESS_KEY_ID", "AZURE_API_KEY", "GCP_API_KEY",
        }
        for k in blocked_keys:
            env.pop(k, None)

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_data,
                env=env,
            )
            return SandboxResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(error="timeout", timed_out=True)
        except FileNotFoundError:
            return SandboxResult(error=f"Command not found: {command[0]}")
        except Exception as e:
            return SandboxResult(error=str(e))

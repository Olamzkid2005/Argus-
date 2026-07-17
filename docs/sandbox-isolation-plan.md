# Sandbox Isolation Plan — Subprocess → Docker/Container

> **Objective:** Harden `chain_exploit_generator.py` and other subprocess-based tool execution against escape and resource exhaustion.
> **Status:** 📋 Plan defined — implementation requires architectural investment
> **Item reference:** Audit Item 4
> **Last updated:** 2026-07-17

---

## 1. Problem Statement

`chain_exploit_generator.py` uses `subprocess.run()` to verify generated exploit scripts. While `shell=False` and locked-down environment variables provide basic safety, there is **no OS-level containerization**. A malicious or buggy exploit script could:

- **Escape the process sandbox:** Access local filesystem, network, or other processes on the host
- **Exfiltrate data:** Read environment variables (even redacted, some may leak) or filesystem paths
- **Resource exhaustion:** Fork bomb, disk fill, network flood from the host
- **Persist:** Write files to disk that survive the verification step

The current defense (blocked env vars, `shell=False`) is defense-in-depth for accidental leakage — not protection against a determined attacker.

---

## 2. Design

### 2.1. Container Per Verification

Each `verify_chain_in_sandbox()` call spawns a **disposable Docker container**:

```
                                 ┌──────────────────────┐
                                 │   Argus Worker Host   │
                                 │                      │
  chain_exploit_generator.py ───►│  Docker SDK (docker) │
                                 │         │            │
                                 │         ▼            │
                                 │  ┌────────────────┐  │
                                 │  │ sandbox:verify │  │
                                 │  │ (ephemeral)     │  │
                                 │  │ - no network    │  │
                                 │  │ - read-only /   │  │
                                 │  │ - memory limit  │  │
                                 │  │ - CPU limit     │  │
                                 │  │ - timeout       │  │
                                 │  └────────────────┘  │
                                 │         │            │
                                 │         ▼            │
                                 │  ┌────────────────┐  │
                                 │  │ stdout/stderr  │  │
                                 │  │ (captured)     │  │
                                 │  └────────────────┘  │
                                 └──────────────────────┘
```

### 2.2. Sandbox Container Spec

```python
SANDBOX_IMAGE = "argus-sandbox:latest"

SANDBOX_CONFIG = {
    "image": SANDBOX_IMAGE,
    "network_disabled": True,              # No network access
    "read_only": True,                     # Read-only filesystem
    "tmpfs": {"/tmp": "size=64M"},         # Temporary writable space
    "mem_limit": "256m",                   # Max 256 MB RAM
    "memswap_limit": "256m",              # No swap
    "cpu_period": 100000,                  # CPU quota period (100ms)
    "cpu_quota": 50000,                    # Max 50% of one CPU
    "pids_limit": 50,                      # Max 50 processes (prevents fork bomb)
    "auto_remove": True,                   # Clean up after execution
    "environment": {
        "PYTHONUNBUFFERED": "1",
        # NO credentials passed to sandbox
    },
    "working_dir": "/workspace",
    "volumes": {
        # No host volumes mounted — completely isolated
    },
}
```

### 2.3. Dockerfile

```dockerfile
# sandbox/Dockerfile
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /workspace

COPY --chown=sandbox:sandbox sandbox_runner.py /usr/local/bin/
ENTRYPOINT ["python3", "/usr/local/bin/sandbox_runner.py"]
```

### 2.4. Sandbox Runner Script

```python
# sandbox/sandbox_runner.py
"""Runs inside the Docker sandbox container.

Reads a JSON command from stdin, executes it safely, and
writes JSON result to stdout.
"""
import json
import subprocess
import sys
import os

def main():
    payload = json.loads(sys.stdin.read())
    command = payload.get("command", [])
    timeout = payload.get("timeout", 30)
    
    if not command:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        print(json.dumps({
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }))
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "timeout", "timeout": timeout}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
```

---

## 3. Implementation Plan

### Phase 1: Docker SDK Integration

**Files to modify:**
- `argus-workers/chain_exploit_generator.py` — Replace `_verify_*_step()` methods with Docker-based sandbox
- `argus-workers/requirements.txt` — Add `docker>=7.0.0`

**New files:**
- `argus-workers/sandbox/Dockerfile` — Sandbox container image
- `argus-workers/sandbox/sandbox_runner.py` — Entrypoint script
- `argus-workers/sandbox/Makefile` — Build/push helpers
- `argus-workers/tests/test_sandbox.py` — Sandbox integration tests

### Phase 2: Configuration & Discovery

- Add Docker host discovery (socket, TCP, env var)
- Add configuration options (`SANDBOX_ENABLED`, `SANDBOX_IMAGE`, `SANDBOX_TIMEOUT`)
- Graceful fallback: if Docker is unavailable, use subprocess with warning

### Phase 3: CI Build

- Add CI job to build sandbox Docker image
- Publish to GitHub Container Registry or local registry
- Add sandbox integration tests to nightly CI

### Phase 4: Broader Adoption

- Extend sandbox to other subprocess usage:
  - `tool_runner.py` — Tool execution (nuclei, sqlmap, etc.)
  - `poc_generator.py` — PoC verification
  - `_browser_scan_worker.py` — Browser isolation

---

## 4. Code Changes

### 4.1. New SandboxClient Class

```python
# sandbox/client.py
"""Docker-based sandbox client for isolated command execution."""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

class SandboxClient:
    """Spawns disposable Docker containers for isolated command execution."""

    def __init__(
        self,
        image: str = "argus-sandbox:latest",
        docker_host: Optional[str] = None,
        timeout: int = 60,
    ):
        self.image = image
        self.docker_host = docker_host or os.environ.get("DOCKER_HOST")
        self.timeout = timeout
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import docker
            kwargs = {}
            if self.docker_host:
                kwargs["base_url"] = self.docker_host
            self._client = docker.from_env(**kwargs)
        return self._client

    def run_command(self, command: list[str], timeout: int = 30) -> dict:
        """Run a command inside a disposable sandbox container.

        Args:
            command: Command and arguments as a list.
            timeout: Max execution time in seconds.

        Returns:
            Dict with 'returncode', 'stdout', 'stderr', or 'error'.
        """
        payload = json.dumps({"command": command, "timeout": timeout})
        
        try:
            container = self.client.containers.run(
                image=self.image,
                command=["python3", "/usr/local/bin/sandbox_runner.py"],
                input=payload.encode(),
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": "size=64M"},
                mem_limit="256m",
                pids_limit=50,
                auto_remove=True,
                detach=False,
                timeout=self.timeout,
            )
            return json.loads(container.decode())
        except Exception as e:
            logger.warning("Sandbox execution failed: %s", e)
            return {"error": str(e)}
```

### 4.2. Modified chain_exploit_generator.py

```python
# In ChainExploitGenerator.verify_chain_in_sandbox():
def verify_chain_in_sandbox(self, script_data, target="", timeout=60):
    """Verify a generated chain exploit script in an isolated Docker sandbox."""
    
    from sandbox.client import SandboxClient
    
    sandbox = SandboxClient(timeout=timeout)
    script = script_data.get("script", "")
    chain_name = script_data.get("chain_name", "unknown")
    
    if not sandbox.client:
        logger.warning("Docker not available — falling back to subprocess sandbox")
        return self._verify_subprocess(script_data, target, timeout)
    
    steps = self._parse_script_steps(script)
    results = []
    
    for step in steps:
        content = step.get("content", "")
        if step["type"] == "curl":
            # Parse curl command into args
            import shlex
            args = shlex.split(content)
            result = sandbox.run_command(args, timeout=timeout)
        elif step["type"] == "python":
            result = sandbox.run_command(
                ["python3", "-c", content], timeout=timeout
            )
        else:
            result = sandbox.run_command(
                shlex.split(content), timeout=timeout
            )
        results.append(result)
    
    return {"verified": all(r.get("returncode") == 0 for r in results), "steps": results}
```

---

## 5. Security Considerations

| Concern | Mitigation |
|---------|------------|
| Container escape | Use `--security-opt no-new-privileges`, drop all capabilities, run as non-root |
| Network exfiltration | `--network none`, no network interfaces inside container |
| Disk exhaustion | Read-only rootfs, limited tmpfs, `--storage-opt size=512M` |
| Fork bomb | `--pids-limit=50`, prevents process chain explosion |
| Memory exhaustion | `--memory=256m --memory-swap=256m` (no swap) |
| CPU exhaustion | `--cpus=0.5`, limits to 1/2 CPU core |
| Timeout | Container automatically killed after timeout via `docker run --timeout` |
| Privilege escalation | `--security-opt=no-new-privileges:true`, drop `CAP_SYS_ADMIN` |
| Seccomp | Apply default Docker seccomp profile (blocks ~50 syscalls) |
| AppArmor/SELinux | Apply default Docker profile if available on host |

---

## 6. Fallback Mode

When Docker is unavailable (e.g., CI without Docker, restricted environments), the sandbox **gracefully falls back** to the existing subprocess-based verification with:

```python
def _verify_subprocess(self, script_data, target="", timeout=60):
    """Fallback: subprocess-based verification (less secure)."""
    logger.warning(
        "Sandbox unavailable — falling back to subprocess verification. "
        "Install Docker for full isolation."
    )
    # ... existing subprocess.run() logic from chain_exploit_generator.py
```

---

## 7. Test Plan

```python
# tests/test_sandbox.py

def test_sandbox_client_import():
    """SandboxClient should be importable."""
    from sandbox.client import SandboxClient
    assert SandboxClient

def test_sandbox_basic_command():
    """Basic echo command should work in sandbox."""
    from sandbox.client import SandboxClient
    client = SandboxClient()
    result = client.run_command(["echo", "hello"])
    assert result.get("returncode") == 0
    assert "hello" in result.get("stdout", "")

def test_sandbox_no_network():
    """Sandbox should not have network access."""
    from sandbox.client import SandboxClient
    client = SandboxClient()
    result = client.run_command(["curl", "http://google.com"])
    # Should fail (no network)
    assert result.get("returncode") != 0 or "error" in result

def test_sandbox_fork_bomb_protection():
    """Fork bomb should be prevented by PID limit."""
    from sandbox.client import SandboxClient
    client = SandboxClient()
    result = client.run_command(["sh", "-c", ":(){ :|:& };:"])
    assert result.get("returncode") != 0

def test_sandbox_read_only_rootfs():
    """Root filesystem should be read-only."""
    from sandbox.client import SandboxClient
    client = SandboxClient()
    result = client.run_command(["touch", "/test_file"])
    assert result.get("returncode") != 0
```

---

## 8. CI Integration

```yaml
# .github/workflows/sandbox.yml
name: Sandbox CI
on:
  schedule:
    - cron: "0 6 * * 1"  # Weekly Monday 06:00
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build sandbox image
        run: docker build -t argus-sandbox:latest argus-workers/sandbox/
      - name: Test sandbox
        run: |
          pip install docker pytest
          pytest argus-workers/tests/test_sandbox.py -v
```

---

## 9. Effort Estimate

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Phase 1: Docker SDK integration | 2-3 days | Docker installed on host |
| Phase 2: Config & discovery | 1 day | Phase 1 complete |
| Phase 3: CI build | 1 day | Docker registry access |
| Phase 4: Broader adoption | 3-5 days | Phases 1-3 complete |
| **Total** | **7-10 days** | |

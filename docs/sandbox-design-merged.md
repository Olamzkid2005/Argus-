# Sandbox Isolation — Merged Design

> **Reconciliation of:** `docs/sandbox-isolation-plan.md` (design doc) × `docs/STRENGTHENING_PLAN_5_GOALS.md` Item 2.1 (plan)
> **Location converged on:** `tool_core/sandbox/` (the plan's structural choice, since `tool_core/` already exists as the execution infrastructure package)
> **Date:** July 20, 2026
> **Status:** Design merged — ready for implementation as Item 2.1

---

## 1. What Each Design Contributed

| Design Doc (`sandbox-isolation-plan.md`) | Strengthening Plan (Item 2.1) | Merged Decision |
|---|---|---|
| `sandbox/client.py` → `SandboxClient` class | `tool_core/sandbox/container.py` | **`tool_core/sandbox/client.py`** — the design doc's `SandboxClient` is the better name (clearer API semantics) |
| `sandbox/Dockerfile` + `sandbox/sandbox_runner.py` | No specific image or runner specified | **Adopt** the design doc's Dockerfile and runner |
| `sandbox/Makefile` | No build helpers | **Adopt** the Makefile |
| Chain-exploit generator only (Phase 1) | Broader `tool_runner.py` adoption | **Phase: chain-exploit first, then broaden** |
| No seccomp module | `tool_core/sandbox/seccomp.py` | **Adopt** seccomp as Phase 3 enhancement |
| Graceful subprocess fallback | No fallback mentioned | **Adopt** the fallback mode |
| Detailed test plan (5 test functions) | No test plan | **Adopt** and extend |
| CI integration (GitHub Actions) | No CI plan | **Adopt** and extend |
| 7-10 days total | 5-7 days total | **5-7 days** (Phase 1+2; seccomp is incremental) |

---

## 2. Problem Statement (Unchanged)

`chain_exploit_generator.py` uses `subprocess.run()` to verify generated exploit scripts. While `shell=False` and locked-down environment variables provide basic safety, there is **no OS-level containerization**. A malicious or buggy exploit script could:

- **Escape the process sandbox:** Access local filesystem, network, or other processes on the host
- **Exfiltrate data:** Read environment variables (even redacted, some may leak) or filesystem paths
- **Resource exhaustion:** Fork bomb, disk fill, network flood from the host
- **Persist:** Write files to disk that survive the verification step

This also applies to other subprocess-based tools (nuclei, sqlmap, browser scanner) — the sandbox should eventually cover all of them.

The current defense (blocked env vars, `shell=False`) is defense-in-depth for accidental leakage — not protection against a determined attacker.

---

## 3. Architecture

```
tool_core/sandbox/
├── __init__.py          # Exports: SandboxClient, SandboxResult, is_available
├── client.py            # SandboxClient — Docker SDK wrapper
├── runner.py            # sandbox_runner.py (copied into container)
├── seccomp.py           # Optional: native seccomp profiles for no-Docker environments
├── Makefile             # Build/push helpers
└── Dockerfile           # Minimal sandbox container image
```

### 3.1. Container Per Execution

Each `SandboxClient.run_command()` call spawns a **disposable Docker container**:

```
  chain_exploit_generator.py ──►  SandboxClient.run_command()
                                         │
                                         ▼
                                   tool_core/sandbox/client.py
                                         │
                                         ▼
                                   Docker SDK (docker-py)
                                         │
                                         ▼
                                   ┌─────────────────────────┐
                                   │  argus-sandbox:latest   │
                                   │  (ephemeral container)  │
                                   │                         │
                                   │  - network_disabled     │
                                   │  - read_only rootfs     │
                                   │  - tmpfs /tmp (64M)     │
                                   │  - mem_limit 256M       │
                                   │  - pids_limit 50        │
                                   │  - auto_remove           │
                                   └─────────────────────────┘
                                         │
                                         ▼
                                   stdout/stderr/returncode
```

### 3.2. Container Spec

```python
SANDBOX_CONFIG = {
    "image": "argus-sandbox:latest",
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
    "security_opt": ["no-new-privileges:true"],
    "cap_drop": ["ALL"],
}
```

---

## 4. Implementation Phases

### Phase 1: MVP — chain_exploit_generator (3-4 days)

**Goal:** Replace `_verify_*_step()` methods in `chain_exploit_generator.py` with Docker-based sandbox. This is the highest-risk subprocess usage.

**Files to create:**
- `argus-workers/tool_core/sandbox/__init__.py` — Exports + `is_available()` check
- `argus-workers/tool_core/sandbox/client.py` — `SandboxClient` class (see Section 5)
- `argus-workers/tool_core/sandbox/Dockerfile` — Minimal sandbox container image
- `argus-workers/tool_core/sandbox/runner.py` — Entrypoint script that runs inside container
- `argus-workers/tool_core/sandbox/Makefile` — Build/push helpers
- `argus-workers/tests/test_sandbox.py` — Integration tests (see Section 7)

**Files to modify:**
- `argus-workers/chain_exploit_generator.py` — Replace `_verify_subprocess()` with `SandboxClient.run_command()`
- `argus-workers/requirements.txt` — Add `docker>=7.0.0`

**Configuration:**
```python
# tool_core/sandbox/__init__.py
SANDBOX_ENABLED = os.environ.get("SANDBOX_ENABLED", "true").lower() == "true"
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "argus-sandbox:latest")
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "60"))
```

**Fallback:** When Docker is unavailable, `SandboxClient.run_command()` calls `_run_subprocess()` with the existing subprocess-based approach, logging a warning.

### Phase 2: Broaden to ToolRunner (2-3 days)

**Goal:** Route all exploit/verification tools through the sandbox.

**Files to modify:**
- `argus-workers/tools/tool_runner.py` — Check `SANDBOX_ENABLED`, route exploit/verification tools through `SandboxClient`
- `argus-workers/tools/poc_generator.py` — Route PoC verification through sandbox
- `argus-workers/tools/_browser_scan_worker.py` — Optional: browser isolation

**Selection criteria:** Only route tools whose `ToolDefinition.exploit_categories` is non-empty (i.e., tools with exploit/verification/PoC purpose). Use `bool(tool.exploit_categories)` as the heuristic — if a tool has exploit categories defined, it should be sandboxed.

### Phase 3: Seccomp Enhancement (1-2 days, optional)

**Goal:** Provide native sandboxing for environments without Docker.

**Files to create:**
- `argus-workers/tool_core/sandbox/seccomp.py` — Seccomp profiles

**Implementation:** Uses `python-seccomp` to apply a restrictive syscall filter before `subprocess.run()`. The profile blocks:
- `clone(CLONE_NEWPID|CLONE_NEWNS)` — container escape
- `open()` with write flags on non-tmpfs paths
- `socket()` / `connect()` — network access
- `ptrace()` — process introspection

This is purely additive — the Docker-based sandbox in Phase 1 already covers the primary use case.

---

## 5. SandboxClient API

```python
# tool_core/sandbox/client.py

@dataclass
class SandboxResult:
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    timed_out: bool = False


class SandboxClient:
    """Spawns disposable Docker containers for isolated command execution.

    Gracefully falls back to subprocess when Docker is unavailable.
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
        self._client: docker.DockerClient | None = None

    @property
    def is_docker_available(self) -> bool:
        """Check if a Docker host is reachable via the Docker SDK.

        Does NOT check for the `docker` CLI binary — `docker-py` communicates
        with the daemon via socket/TCP, not through the CLI.
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
            command: Command and arguments as a list.
            timeout: Max execution time in seconds.
            input_data: Optional stdin string.

        Returns:
            SandboxResult with returncode, stdout, stderr, or error.
            Access fields as attributes (result.returncode), not dict-style.
        """
        if self.is_docker_available:
            return self._run_docker(command, timeout, input_data)
        logger.warning(
            "Docker not available — falling back to subprocess sandbox. "
            "Install Docker for full isolation."
        )
        return self._run_subprocess(command, timeout, input_data)

    def _run_docker(self, command: list[str], timeout: int, input_data: str | None) -> SandboxResult:
        """Run command in ephemeral Docker container."""
        import docker
        payload = json.dumps({
            "command": command,
            "timeout": timeout,
            "input": input_data,
        })
        try:
            container = self.client.containers.run(
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
            result = json.loads(container.decode())
            return SandboxResult(
                returncode=result.get("returncode"),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
            )
        except docker.errors.ContainerError as e:
            return SandboxResult(error=str(e))
        except Exception as e:
            return SandboxResult(error=str(e))

    def _run_subprocess(self, command: list[str], timeout: int, input_data: str | None) -> SandboxResult:
        """Fallback: subprocess-based execution (less secure)."""
        import subprocess
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_data,
            )
            return SandboxResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(error="timeout", timed_out=True)
        except Exception as e:
            return SandboxResult(error=str(e))
```

---

## 6. Dockerfile (from design doc, location updated)

```dockerfile
# tool_core/sandbox/Dockerfile
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /workspace

COPY --chown=sandbox:sandbox runner.py /usr/local/bin/sandbox_runner.py
ENTRYPOINT ["python3", "/usr/local/bin/sandbox_runner.py"]
```

---

## 7. Test Plan (extended from design doc)

```python
# tests/test_sandbox.py

class TestSandboxClient:

    def test_import(self):
        """SandboxClient should be importable."""
        from tool_core.sandbox.client import SandboxClient
        assert SandboxClient

    def test_basic_command(self):
        """Basic echo command should work in sandbox."""
        client = SandboxClient()
        result = client.run_command(["echo", "hello"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_no_network(self):
        """Sandbox should not have network access."""
        client = SandboxClient()
        result = client.run_command(["curl", "http://google.com"])
        assert result.returncode != 0 or result.error

    def test_fork_bomb_protection(self):
        """Fork bomb should be prevented by PID limit."""
        client = SandboxClient()
        result = client.run_command(["sh", "-c", ":(){ :|:& };:"])
        assert result.returncode != 0

    def test_read_only_rootfs(self):
        """Root filesystem should be read-only."""
        client = SandboxClient()
        result = client.run_command(["touch", "/test_file"])
        assert result.returncode != 0

    def test_memory_limit(self):
        """Memory allocation beyond limit should fail."""
        client = SandboxClient()
        result = client.run_command([
            "python3", "-c",
            "x = bytearray(300 * 1024 * 1024)"  # 300MB > 256MB limit
        ])
        assert result.returncode != 0 or "MemoryError" in result.stderr

    def test_timeout_enforced(self):
        """Infinite loop should be killed by timeout."""
        client = SandboxClient(timeout=5)
        result = client.run_command(["sleep", "30"], timeout=3)
        assert result.timed_out or result.error

    def test_stdin_passthrough(self):
        """Stdin should be passed through to the command."""
        client = SandboxClient()
        result = client.run_command(["cat"], input_data="hello stdin")
        assert "hello stdin" in result.stdout

    def test_fallback_subprocess(self):
        """When Docker is unavailable, subprocess fallback should work."""
        from unittest.mock import patch
        from tool_core.sandbox.client import SandboxClient
        client = SandboxClient()
        with patch.object(client, "is_docker_available", False):
            result = client.run_command(["echo", "fallback"])
            assert result.returncode == 0
            assert "fallback" in result.stdout

    def test_bridge_field_mapping(self):
        """Verify tool_core.sandbox.client.SandboxResult maps all fields from docker output."""
        from tool_core.sandbox.client import SandboxResult
        result = SandboxResult(returncode=0, stdout="ok", stderr="")
        assert result.returncode == 0
        assert result.stdout == "ok"
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
  pull_request:
    paths:
      - "argus-workers/tool_core/sandbox/**"
      - "argus-workers/tests/test_sandbox.py"

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build sandbox image
        run: docker build -t argus-sandbox:latest argus-workers/tool_core/sandbox/
      - name: Install dependencies
        run: pip install docker pytest
      - name: Test sandbox
        run: pytest argus-workers/tests/test_sandbox.py -v --timeout=60
```

---

## 9. Security Considerations (unchanged)

| Concern | Mitigation |
|---|---|
| Container escape | `--security-opt no-new-privileges`, drop all capabilities (`--cap-drop ALL`), run as non-root (UID 1000) |
| Network exfiltration | `--network none`, no network interfaces inside container |
| Disk exhaustion | Read-only rootfs, limited tmpfs (64M), no host volumes mounted |
| Fork bomb | `--pids-limit=50`, prevents process chain explosion |
| Memory exhaustion | `--memory=256m --memory-swap=256m` (no swap) |
| CPU exhaustion | `--cpus=0.5`, limits to 1/2 CPU core |
| Timeout | Container automatically killed via Docker timeout |
| Privilege escalation | `--security-opt=no-new-privileges:true`, drop `CAP_SYS_ADMIN` |
| Seccomp | Default Docker seccomp profile (blocks ~50 syscalls); custom profile in Phase 3 |
| AppArmor/SELinux | Apply default Docker profile if available on host |

---

## 10. Effort Estimate (Updated)

| Phase | Effort | Dependencies | Deliverables |
|---|---|---|---|
| **1. MVP — chain_exploit_generator sandbox** | 3-4 days | Docker on host | `client.py`, `Dockerfile`, `runner.py`, modified `chain_exploit_generator.py`, tests |
| **2. Broaden to ToolRunner** | 2-3 days | Phase 1 complete | Modified `tool_runner.py`, `poc_generator.py` |
| **3. Seccomp enhancement (optional)** | 1-2 days | None (additive) | `seccomp.py` with profiles |
| **Total** | **5-7 days** (MVP), **+2-3 for seccomp** | | |

---

## 11. Changes to the Strengthening Plan

The following updates should be applied to `docs/STRENGTHENING_PLAN_5_GOALS.md`:

- **Item 2.1 scope:** Adopt the merged architecture above. Reference `tool_core/sandbox/client.py` (not `container.py`). Phase as described.
- **Item 2.1 dependencies:** Still depends on Tier 0.3 (now complete: this document is the merged design).
- **Effort estimate:** 5-7 days (unchanged from original).
- **File paths in implementation table:** Update `tool_core/sandbox/container.py` → `tool_core/sandbox/client.py`.

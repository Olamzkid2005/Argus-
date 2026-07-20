"""Sandbox runner — runs inside the Docker sandbox container.

Reads a JSON payload from stdin with the command to execute, runs it
safely, and writes a JSON result to stdout. This is the entrypoint
for the argus-sandbox Docker image.

The runner:
- Receives JSON: {"command": [...], "timeout": 30, "input": "..."}
- Executes the command via subprocess with no shell=True
- Captures stdout/stderr/returncode
- Handles timeout, execution errors gracefully
- Writes JSON result: {"returncode": ..., "stdout": ..., "stderr": ...}
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    """Read payload from stdin, execute command, write result to stdout."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        result = {"error": f"Failed to read input: {e}"}
        print(json.dumps(result))
        sys.exit(1)

    command = payload.get("command", [])
    timeout = payload.get("timeout", 30)
    input_data = payload.get("input")

    if not command or not isinstance(command, list):
        print(json.dumps({"error": "No command provided or command is not a list"}))
        sys.exit(1)

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_data,
        )
        result = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        print(json.dumps(result))
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "timeout", "timeout": timeout}))
    except FileNotFoundError:
        print(json.dumps({"error": f"Command not found: {command[0]}"}))
    except PermissionError:
        print(json.dumps({"error": f"Permission denied: {command[0]}"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()

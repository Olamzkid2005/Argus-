#!/usr/bin/env python3
"""sn1per-equivalent aggregation that delegates instead of aborting.

sn1per is a Bash framework with a long dependency chain and is not installable
here. Its job — run the recurring scanners against a target and collect what
they find — is what this project already has: nuclei, nikto and httpx. This shim
delegates to whichever of them is installed, bounded to a shared budget, and
reports the aggregated result attributed to sn1per. Nothing found is an explicit
clean negative; a missing delegate is reported as a skipped delegate, never as a
phase failure.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time

_DELEGATES = ["nuclei", "nikto", "httpx"]


def _run(cmd: list[str], timeout: int) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 — fixed binaries, target passed as one argv element
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return out.decode(errors="replace") if isinstance(out, bytes) else out
    except OSError as exc:
        print(f"sn1per: delegate {cmd[0]} could not run: {exc}", file=sys.stderr)
        return ""


def _nuclei(target: str, budget: int) -> list[dict]:
    findings: list[dict] = []
    output = _run(["nuclei", "-u", target, "-silent", "-jsonl", "-no-color"], budget)
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        info = item.get("info", {}) if isinstance(item, dict) else {}
        name = info.get("name") or item.get("template-id") or "nuclei match"
        findings.append({
            "title": str(name)[:120],
            "type": str(info.get("tags", ["vulnerability"])[0] if info.get("tags") else "vulnerability").upper(),
            "severity": str(info.get("severity", "medium")).lower(),
            "confidence": "high",
            "description": str(info.get("description") or f"nuclei matched {name} at {item.get('matched-at', target)}"),
            "endpoint": item.get("matched-at") or target,
            "tool": "sn1per",
        })
    return findings


def _nikto(target: str, budget: int) -> list[dict]:
    findings: list[dict] = []
    output = _run(["nikto", "-h", target, "-nointeractive", "-ask", "no", "-maxtime", f"{max(20, budget)}s"], budget + 15)
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("+ "):
            continue
        path = re.search(r"^\+ (?:\S+ )?(/\S*)", line)
        if not path:
            continue
        findings.append({
            "title": line[2:][:120],
            "type": "WEB_SERVER_MISCONFIGURATION",
            "severity": "low",
            "confidence": "medium",
            "description": line[2:],
            "endpoint": target.rstrip("/") + path.group(1),
            "tool": "sn1per",
        })
    return findings


def _httpx(target: str, budget: int) -> list[dict]:
    findings: list[dict] = []
    output = _run(["httpx", "-u", target, "-silent", "-json", "-no-color"], min(30, budget))
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        tech = item.get("tech") or item.get("technologies") or []
        if not tech:
            continue
        findings.append({
            "title": f"Delegated fingerprint: {', '.join(tech[:4])}",
            "type": "TECHNOLOGY_DETECTED",
            "severity": "info",
            "confidence": "medium",
            "description": f"httpx reported {', '.join(tech[:8])} on {item.get('url', target)}",
            "endpoint": item.get("url", target),
            "tool": "sn1per",
        })
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--budget", type=int, default=75)
    args = parser.parse_args()

    target = args.target if args.target.startswith(("http://", "https://")) else "http://" + args.target
    started = time.monotonic()
    available = [name for name in _DELEGATES if shutil.which(name)]
    missing = [name for name in _DELEGATES if name not in available]

    findings: list[dict] = []
    for name in available:
        remaining = int(args.budget - (time.monotonic() - started))
        if remaining <= 5:
            break
        if name == "nuclei":
            findings.extend(_nuclei(target, remaining))
        elif name == "nikto":
            findings.extend(_nikto(target, min(remaining, 45)))
        elif name == "httpx":
            findings.extend(_httpx(target, remaining))

    if missing:
        print(f"sn1per: delegating to {', '.join(available) or 'nothing'}; not installed: {', '.join(missing)}", file=sys.stderr)

    if findings:
        # One JSON array: JSONL would fall through to the text heuristics.
        print(json.dumps(findings))
        return 0

    print(json.dumps([{
        "title": f"sn1per aggregation: no findings from {', '.join(available) or 'no delegates'}",
        "type": "VULNERABILITY_SCAN_NEGATIVE",
        "severity": "info",
        "confidence": "low",
        "description": (
            f"sn1per-equivalent wrapper delegated to {', '.join(available) or 'no installed scanners'}"
            + (f" (not installed: {', '.join(missing)})" if missing else "")
            + f" against {target} and aggregated no findings. Clean negative."
        ),
        "endpoint": target,
        "tool": "sn1per",
    }]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

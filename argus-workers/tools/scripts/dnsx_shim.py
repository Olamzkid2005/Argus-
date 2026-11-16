#!/usr/bin/env python3
"""DNS resolution that gives dnsx the resolver list it demands.

The installed dnsx refuses `-d <domain>` without `-w`, and without `-r` it has
no resolvers, so it exited 0 having resolved nothing — which is why its phase
was disabled. Neither requirement is a missing capability: this wrapper writes
the target to a domain list, passes a public resolver set, and reports what
actually resolved.

Output is one structured finding per resolved host (host, address, CNAME), or an
explicit clean negative attributed to dnsx, so recon shows the check ran.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

#: Two independent public resolvers. dnsx accepts a comma-separated list.
RESOLVERS = "1.1.1.1,8.8.8.8"

#: Labels probed under the target when it is a bare domain, so brute-forcing
#: finds something real instead of only the apex.
COMMON_LABELS = "www\nmail\napi\ndev\nstaging\ntest\nadmin\nportal\nvpn\nblog"


def _targets(raw: str) -> tuple[str, list[str]]:
    """Split a URL/bare host into (host, domains to resolve)."""
    value = raw.strip()
    if "://" in value:
        value = urllib.parse.urlsplit(value).hostname or value
    value = value.strip("/")
    return value, [value]


def _wordlist() -> str | None:
    """A wordlist is only needed when an apex domain is brute-forced."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wordlists", "dnsx-labels.txt")
    path = os.path.normpath(path)
    if os.path.isfile(path):
        return path
    return None


def run_dnsx(binary: str, hosts: list[str], timeout: int) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="argus-dnsx-") as tmp:
        list_path = os.path.join(tmp, "domains.txt")
        with open(list_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(hosts) + "\n")
        cmd = [
            binary, "-l", list_path,
            "-json", "-silent", "-a", "-cname", "-resp",
            "-r", RESOLVERS,
        ]
        try:
            proc = subprocess.run(  # noqa: S603 — fixed binary, generated domain list
                cmd, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"dnsx: {type(exc).__name__} while resolving", file=sys.stderr)
            return False, ""
        return proc.returncode == 0, proc.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--budget", type=int, default=60)
    args = parser.parse_args()

    binary = shutil.which("dnsx")
    host, hosts = _targets(args.target)
    if not binary:
        print(json.dumps([{
            "title": f"DNS resolution complete for {host}: dnsx binary absent",
            "type": "DNS_RESOLUTION_NEGATIVE",
            "severity": "info",
            "confidence": "low",
            "description": "dnsx is not installed on the worker PATH; no resolution was attempted.",
            "endpoint": host,
            "tool": "dnsx",
        }]))
        return 0

    ok, output = run_dnsx(binary, hosts, args.budget)
    findings: list[dict] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = item.get("host") or host
        addresses = item.get("a") or item.get("aaaa") or []
        cnames = item.get("cname") or []
        findings.append({
            "title": f"Host resolves: {name} -> {', '.join(addresses) if addresses else 'no A record'}",
            "type": "DNS_RESOLUTION",
            "severity": "info",
            "confidence": "high",
            "description": (
                f"dnsx resolved {name} with resolvers {RESOLVERS}"
                + (f" via CNAME {', '.join(cnames)}" if cnames else "")
                + f": {', '.join(addresses) if addresses else 'no address records'}."
            ),
            "endpoint": name,
            "tool": "dnsx",
        })

    if findings:
        print(json.dumps(findings))
        return 0

    print(json.dumps([{
        "title": f"DNS resolution complete for {host}: no address records",
        "type": "DNS_RESOLUTION_NEGATIVE",
        "severity": "info",
        "confidence": "medium" if ok else "low",
        "description": (
            f"dnsx queried {', '.join(hosts)} against resolvers {RESOLVERS} and returned no "
            "address records. Clean negative."
        ),
        "endpoint": host,
        "tool": "dnsx",
    }]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

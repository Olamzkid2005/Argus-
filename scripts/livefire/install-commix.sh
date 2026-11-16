#!/usr/bin/env bash
# Install commix into .livefire without root.
#
# commix is the command-injection tool the vuln_scan phase needs; without it the
# phase records a coverage gap for command_injection even though the registry
# lists the tool. It is a Python program with no build step.
#
# Usage: bash scripts/livefire/install-commix.sh
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS="$REPO/.livefire/tools"
BIN="$REPO/.livefire/bin"
mkdir -p "$TOOLS" "$BIN"

if [ ! -f "$TOOLS/commix/commix.py" ]; then
  curl -sL -o /tmp/commix.tar.gz https://github.com/commixproject/commix/archive/refs/heads/master.tar.gz
  mkdir -p "$TOOLS/commix"
  tar xzf /tmp/commix.tar.gz -C /tmp
  cp -r /tmp/commix-master/. "$TOOLS/commix/"
fi

printf '%s\n' '#!/bin/sh' '# Commix is a Python program; keep it importable from its own tree.' \
  'REPO="$(cd "$(dirname "$0")/../.." && pwd)"' \
  'cd "$REPO/.livefire/tools/commix" && exec python3 commix.py "$@"' > "$BIN/commix"
chmod +x "$BIN/commix"
"$BIN/commix" --version 2>/dev/null | tail -1

#!/usr/bin/env bash
# Run one real assessment against a public, deliberately vulnerable host.
#
# This is the same entry point an operator uses (`argus assess`), with the
# environment an unprivileged run needs: tools from .livefire/bin, the worker
# venv, an allowlist scope covering exactly the target host, and a wall clock
# for the streaming web scanners so a slow internet host cannot outlive the run.
#
# Usage: bash scripts/livefire/run-public-engagement.sh [target-url] [--refresh]
#   default target: http://testasp.vulnweb.com
#
# Artifacts: the engagement directory (report.md, engagement.db) is printed at
# the end; ARGUS_DATA_DIR defaults to .livefire/public-run/<host>.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

TARGET="${1:-http://testasp.vulnweb.com}"
FRESH="${2:-}"
HOST="$(python3 -c "import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).hostname or sys.argv[1])" "$TARGET")"

export PATH="$REPO/.livefire/bin:$REPO/argus-workers/venv/bin:$PATH"
export HOME="${ARGUS_PUBLIC_HOME:-$REPO/.livefire/public-run/$HOST}"
export ARGUS_DATA_DIR="${ARGUS_DATA_DIR:-$HOME/.argus}"
mkdir -p "$ARGUS_DATA_DIR"

export ARGUS_SCOPE_MODE=allowlist
export ARGUS_ALLOWED_TARGETS="$HOST"
export ARGUS_AUTO_APPROVE=1
export ARGUS_ALLOW_AMBIENT_LLM_ENV=0
export ARGUS_LLM_TRANSPORT="${ARGUS_LLM_TRANSPORT:-direct}"
export LLM_PROVIDER="${LLM_PROVIDER:-generic}"
export LLM_API_URL="${LLM_API_URL:-http://127.0.0.1:18081/v1/chat/completions}"
export LLM_API_KEY="${LLM_API_KEY:-livefire-stub}"
export LLM_MODEL="${LLM_MODEL:-gpt-4o-mini}"
# Streaming scanners (nuclei, dalfox, nikto, cloud sweeps) get this wall clock.
export ARGUS_TOOL_WALL_SECONDS="${ARGUS_TOOL_WALL_SECONDS:-90}"

if [ -d "$REPO/.livefire/tools/browser-libs/usr/lib/x86_64-linux-gnu" ]; then
  export LD_LIBRARY_PATH="$REPO/.livefire/tools/browser-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export FONTCONFIG_FILE="$REPO/.livefire/tools/browser-libs/etc/fonts/fonts.conf"
fi
if [ -d "$REPO/.livefire/tools/ms-playwright" ]; then
  export PLAYWRIGHT_BROWSERS_PATH="$REPO/.livefire/tools/ms-playwright"
fi
# nuclei ships no templates of its own; find whichever copy this host has.
for cand in "/workspace/homes/$(id -un)/nuclei-templates" /workspace/homes/*/nuclei-templates; do
  if [ -d "$cand" ]; then
    export ARGUS_NUCLEI_TEMPLATES="$cand"
    break
  fi
done

cd "$REPO/Argus-Tui/packages/opencode"
CACHE_ARGS=()
[ "$FRESH" = "--refresh" ] && CACHE_ARGS=(--no-cache)
exec bun ./bin/argus assess "$TARGET" "${CACHE_ARGS[@]}" --verbose

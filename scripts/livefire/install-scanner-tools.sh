#!/usr/bin/env bash
# Provision the vulnerability-discovery scanners this workspace can install
# without root, into the same venv the runner puts on PATH.
#
#   bash scripts/livefire/install-scanner-tools.sh
#
# sqlmap and arjun are pip packages. whatweb (Ruby) and sn1per (Bash framework)
# have no installable form in this image; their tool definitions point at the
# Python shims under argus-workers/tools/scripts/, which run the real tool when
# it exists and a native equivalent when it does not.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$REPO/argus-workers/venv"
export PATH="$REPO/.livefire/bin:$VENV/bin:$PATH"

if [ ! -x "$VENV/bin/python" ]; then
  echo "error: $VENV/bin/python missing — create the venv first (uv venv venv)" >&2
  exit 1
fi

uv pip install --python "$VENV/bin/python" -r "$REPO/argus-workers/requirements-tools.txt"

for tool in sqlmap arjun; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: $tool still not on PATH after install" >&2
    exit 1
  fi
  printf '%-8s %s\n' "$tool" "$(command -v "$tool")"
done

for shim in whatweb_shim.py sqlmap_shim.py arjun_shim.py sn1per_shim.py; do
  "$VENV/bin/python" -m py_compile "$REPO/argus-workers/tools/scripts/$shim"
  printf '%-20s compiles (python shim)\n' "$shim"
done

echo "scanner tools provisioned"

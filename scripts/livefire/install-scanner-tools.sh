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

for tool in sqlmap arjun semgrep; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: $tool still not on PATH after install" >&2
    exit 1
  fi
  printf '%-8s %s\n' "$tool" "$(command -v "$tool")"
done

# Go releases that have no package here. .livefire/bin is already on the
# runner's PATH; downloads are pinned and skipped when the binary is present.
BIN="$REPO/.livefire/bin"
mkdir -p "$BIN"

fetch_release() {
  local name="$1" url="$2" inner="$3"
  if [ -x "$BIN/$name" ]; then
    printf '%-10s already installed\n' "$name"
    return 0
  fi
  local tmp
  tmp="$(mktemp -d)"
  if ! curl -sSL --max-time 180 -o "$tmp/rel.zip" "$url"; then
    echo "warning: could not download $name ($url)" >&2
    rm -rf "$tmp"
    return 1
  fi
  unzip -o -q "$tmp/rel.zip" -d "$tmp/out"
  local found
  found="$(find "$tmp/out" -type f -name "$inner" | head -1)"
  if [ -z "$found" ]; then
    echo "warning: $name archive did not contain $inner" >&2
    rm -rf "$tmp"
    return 1
  fi
  install -m 0755 "$found" "$BIN/$name"
  rm -rf "$tmp"
  printf '%-10s installed from release\n' "$name"
}

fetch_release dnsx \
  https://github.com/projectdiscovery/dnsx/releases/download/v1.2.1/dnsx_1.2.1_linux_amd64.zip dnsx
fetch_release gospider \
  https://github.com/jaeles-project/gospider/releases/download/v1.1.6/gospider_v1.1.6_linux_x86_64.zip gospider

for shim in whatweb_shim.py sqlmap_shim.py arjun_shim.py sn1per_shim.py bucket_upload_shim.py recon_shim.py dnsx_shim.py; do
  "$VENV/bin/python" -m py_compile "$REPO/argus-workers/tools/scripts/$shim"
  printf '%-20s compiles (python shim)\n' "$shim"
done

echo "scanner tools provisioned"

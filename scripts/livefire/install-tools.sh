#!/usr/bin/env bash
# Install trivy and nmap without root, into .livefire/.
#
# trivy is a static release asset. nmap has no static build for Ubuntu, so the
# distribution packages are extracted into .livefire/tools/nmap with
# `dpkg-deb -x` (no root, nothing installed system-wide) and a wrapper points the
# loader and NMAPDIR at the extracted files. Raw-socket scans still need
# CAP_NET_RAW; unprivileged TCP connect scans (`-sT`) work as installed.
#
# Re-run with FORCE=1 to refresh both tools.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BIN="$ROOT/.livefire/bin"
NM="$ROOT/.livefire/tools/nmap"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$BIN" "$ROOT/.livefire/tools"
FORCE=${FORCE:-0}

# ── trivy ─────────────────────────────────────────────────────────────
if [ "$FORCE" = "1" ] || ! "$BIN/trivy" --version >/dev/null 2>&1; then
  tag=$(curl -sIL --max-time 60 -o /dev/null -w '%{url_effective}' \
    https://github.com/aquasecurity/trivy/releases/latest | sed 's#.*/tag/v##')
  [ -n "$tag" ] || { echo "could not resolve the latest trivy tag" >&2; exit 1; }
  url="https://github.com/aquasecurity/trivy/releases/download/v${tag}/trivy_${tag}_Linux-64bit.tar.gz"
  echo "installing trivy ${tag}"
  curl -fsSL --max-time 300 -o "$TMP/trivy.tgz" "$url"
  tar -xzf "$TMP/trivy.tgz" -C "$TMP" trivy
  install -m 0755 "$TMP/trivy" "$BIN/trivy"
else
  echo "trivy already installed: $("$BIN/trivy" --version | head -1)"
fi

# ── nmap (extracted Ubuntu packages) ──────────────────────────────────
# Versions from Ubuntu 24.04 (noble); nmap links libssh2, liblinear, liblua5.4,
# libblas and libgfortran, which this image does not all ship.
NOBLE="http://archive.ubuntu.com/ubuntu/pool"
DEBS=(
  # The binary package ships no /usr/share/nmap data; without nmap-common nmap
  # falls back to a stub services file and refuses --top-ports.
  "$NOBLE/universe/n/nmap/nmap-common_7.94+git20230807.3be01efb1+dfsg-3build2_all.deb"
  "$NOBLE/universe/n/nmap/nmap_7.94+git20230807.3be01efb1+dfsg-3build2_amd64.deb"
  "$NOBLE/main/libs/libssh2/libssh2-1t64_1.11.0-4.1build2_amd64.deb"
  "$NOBLE/universe/libl/liblinear/liblinear4_2.3.0+dfsg-5build1_amd64.deb"
  "$NOBLE/main/l/lua5.4/liblua5.4-0_5.4.6-3build2_amd64.deb"
  "$NOBLE/main/l/lapack/libblas3_3.12.0-3build1_amd64.deb"
  "$NOBLE/main/g/gcc-14/libgfortran5_14-20240412-0ubuntu1_amd64.deb"
)

if [ "$FORCE" = "1" ] || ! "$BIN/nmap" --version >/dev/null 2>&1; then
  rm -rf "$NM"
  mkdir -p "$NM"
  for url in "${DEBS[@]}"; do
    file="$TMP/$(basename "$url")"
    echo "extracting $(basename "$url")"
    curl -fsSL --max-time 300 -o "$file" "$url"
    dpkg-deb -x "$file" "$NM"
  done
  cat > "$BIN/nmap" <<'WRAPPER'
#!/bin/sh
# Extracted nmap: point the loader at the bundled libraries and NMAPDIR at the
# extracted data files so no system-wide install is needed.
SELF=$(readlink -f "$0")
ROOT=$(dirname "$(dirname "$SELF")")/tools/nmap
LD_LIBRARY_PATH="$ROOT/usr/lib/x86_64-linux-gnu:$ROOT/usr/lib/x86_64-linux-gnu/blas${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
NMAPDIR="$ROOT/usr/share/nmap"
export LD_LIBRARY_PATH NMAPDIR
exec "$ROOT/usr/bin/nmap" "$@"
WRAPPER
  chmod +x "$BIN/nmap"
else
  echo "nmap already installed: $("$BIN/nmap" --version | head -1)"
fi

# ── verify both actually run ──────────────────────────────────────────
"$BIN/trivy" --version | head -1
"$BIN/nmap" --version | head -1
echo "tools installed in $BIN"

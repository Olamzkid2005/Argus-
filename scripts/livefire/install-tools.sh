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

# ── headless browser for the playwright verifiers ────────────────────
# Chromium needs shared libraries and a fontconfig file this image does not
# ship. They are extracted unprivileged into tools/browser-libs; the worker's
# tool environment points LD_LIBRARY_PATH/FONTCONFIG_FILE at them and keeps the
# browser cache inside the workspace so a throw-away HOME does not lose it.
BROWSER_LIBS="$ROOT/.livefire/tools/browser-libs"
PW_BROWSERS="$ROOT/.livefire/tools/ms-playwright"
BROWSER_DEBS=(
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libasound2t64
  libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libnspr4 libnss3
  libxkbcommon0 libxi6 libxrender1 libpango-1.0-0 libcairo2 libxext6
  libdbus-1-3 libfreetype6 libfontconfig1 libthai0 libdatrie1 libgraphite2-3
  libharfbuzz0b libpixman-1-0 libfribidi0
)

if [ "$FORCE" = "1" ] || [ ! -x "$PW_BROWSERS/chromium_headless_shell-1255/chrome-headless-shell-linux64/chrome-headless-shell" ]; then
  echo "installing the playwright chromium build"
  PLAYWRIGHT_BROWSERS_PATH="$PW_BROWSERS" uv pip install --python "$ROOT/argus-workers/venv/bin/python" playwright
  PLAYWRIGHT_BROWSERS_PATH="$PW_BROWSERS" "$ROOT/argus-workers/venv/bin/python" -m playwright install chromium
fi

if [ "$FORCE" = "1" ] || [ ! -f "$BROWSER_LIBS/etc/fonts/fonts.conf" ]; then
  mkdir -p "$BROWSER_LIBS/etc/fonts"
  for pkg in "${BROWSER_DEBS[@]}" fonts-dejavu-core; do
    url=$(curl -sL --max-time 60 "https://packages.ubuntu.com/noble/amd64/$pkg/download" | grep -o 'http://[^"]*\.deb' | head -1)
    [ -n "$url" ] || url=$(curl -sL --max-time 60 "https://packages.ubuntu.com/noble/all/$pkg/download" | grep -o 'http://[^"]*\.deb' | head -1)
    if [ -z "$url" ]; then echo "could not resolve $pkg" >&2; continue; fi
    file="$TMP/$(basename "$url")"
    curl -fsSL --max-time 300 -o "$file" "$url" && dpkg-deb -x "$file" "$BROWSER_LIBS"
  done
  cat > "$BROWSER_LIBS/etc/fonts/fonts.conf" <<FONTS
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>$BROWSER_LIBS/usr/share/fonts</dir>
  <cachedir>/tmp/fontconfig-cache</cachedir>
</fontconfig>
FONTS
fi

# ── verify everything actually runs ──────────────────────────────────
"$BIN/trivy" --version | head -1
"$BIN/nmap" --version | head -1
LD_LIBRARY_PATH="$BROWSER_LIBS/usr/lib/x86_64-linux-gnu" \
  FONTCONFIG_FILE="$BROWSER_LIBS/etc/fonts/fonts.conf" \
  PLAYWRIGHT_BROWSERS_PATH="$PW_BROWSERS" \
  "$ROOT/argus-workers/venv/bin/python" - <<'BROWSER_TEST'
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()
    page.set_content("<title>argus</title>")
    assert page.title() == "argus"
    browser.close()
print("chromium: renders a page")
BROWSER_TEST

echo "tools installed in $BIN"

#!/usr/bin/env bash
# Argus — single point of installation.
#
#   ./scripts/argus-setup.sh              # everything the doctor gates on, plus the web pack
#   ./scripts/argus-setup.sh --core       # only the five tools `argus doctor` fails on
#   ./scripts/argus-setup.sh --check      # verify what is installed, install nothing
#   ./scripts/argus-setup.sh --force      # re-download tools that are already present
#
# Supported hosts:
#   Linux    — release binaries + the rootless nmap package extraction
#   macOS    — release binaries + `brew install nmap`
#   Windows  — release binaries via Git Bash + `winget`/`choco` or the nmap zip
#
# Installs, idempotently and without root:
#   * Bun dependencies for the TypeScript engine (Argus-Tui)
#   * the Python worker venv and both requirements files
#   * the five doctor-gated tools: nuclei, nmap, gitleaks, semgrep, trivy
#   * the web/recon pack: httpx, katana, ffuf, dalfox, sqlmap, nikto
#   * a local Redis where one can run, and a .env seeded from .env.example
#   * a final `argus doctor` run
#
# Binaries land in $ARGUS_TOOLCHAIN_BIN (default: <repo>/.livefire/bin), which
# start-argus.sh already puts on PATH — so no shell profile edits are needed.
#
# Versions below are pinned and must satisfy min_version in
# Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml.
#
# Written for bash 3.2 (the macOS system shell): no associative arrays, no
# `sort -V`, no `readlink -f`, no GNU-only flags.
set -euo pipefail

ARGUS_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ARGUS_TOOLCHAIN_BIN:-$ARGUS_HOME/.livefire/bin}"
VENV="$ARGUS_HOME/argus-workers/venv"
ARGUS_TUI="$ARGUS_HOME/Argus-Tui"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PACK="all"
MODE="install"
FORCE="${FORCE:-0}"

usage() {
  sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --core) PACK="core" ;;
    --all) PACK="all" ;;
    --check) MODE="check" ;;
    --force) FORCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# ── Pinned versions ────────────────────────────────────────────────────────────
NUCLEI_VERSION=3.11.1     # min 3.0.0
HTTPX_VERSION=1.12.0      # min 1.0.0
KATANA_VERSION=1.8.0      # min 1.0.0
FFUF_VERSION=2.3.0        # min 1.0.0
DALFOX_VERSION=2.11.0     # min 1.0.0
GITLEAKS_VERSION=8.30.1   # min 1.0.0
TRIVY_VERSION=0.76.2      # min 0.50.0
NMAP_WIN_VERSION=7.92     # last win32 zip release; newer versions are .exe only

# ── Output helpers ─────────────────────────────────────────────────────────────
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else B=""; G=""; Y=""; R=""; N=""; fi

step() { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
skip() { printf '  %s·%s %s\n' "$Y" "$N" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$R" "$N" "$*"; }
die()  { bad "$*"; exit 1; }

need() { command -v "$1" >/dev/null 2>&1; }

# version_ge A B → success when A >= B. Portable: BSD sort has no -V.
version_ge() {
  local a1 a2 a3 b1 b2 b3
  IFS=. read -r a1 a2 a3 <<EOF
$1
EOF
  IFS=. read -r b1 b2 b3 <<EOF
$2
EOF
  a1=${a1:-0}; a2=${a2:-0}; a3=${a3:-0}
  b1=${b1:-0}; b2=${b2:-0}; b3=${b3:-0}
  if [ "$a1" -gt "$b1" ]; then return 0; fi
  if [ "$a1" -lt "$b1" ]; then return 1; fi
  if [ "$a2" -gt "$b2" ]; then return 0; fi
  if [ "$a2" -lt "$b2" ]; then return 1; fi
  [ "$a3" -ge "$b3" ]
}

# version_cmd <tool> → the flag that prints its version. Flags differ per tool
# (ffuf -V, gitleaks version, nmap --version) and nmap prints a two-part
# version, so both the command and the pattern live here.
version_cmd() {
  case "$1" in
    nuclei)   echo "nuclei --version" ;;
    nmap)     echo "nmap --version" ;;
    gitleaks) echo "gitleaks version" ;;
    semgrep)  echo "semgrep --version" ;;
    trivy)    echo "trivy --version" ;;
    httpx)    echo "httpx -version" ;;
    katana)   echo "katana -version" ;;
    ffuf)     echo "ffuf -V" ;;
    dalfox)   echo "dalfox version" ;;
    sqlmap)   echo "sqlmap --version" ;;
    nikto)    echo "nikto -Version" ;;
    *)        echo "" ;;
  esac
}

tool_version() {
  local name="$1" cmd out
  cmd="$(version_cmd "$name")"
  [ -n "$cmd" ] || return 1
  need "$name" || return 1
  out="$(bash -c "$cmd" 2>&1 || true)"
  # Drop interpreter/warning noise (".../python3.12/site-packages/requests/...
  # RequestsDependencyWarning") so the first number left is the tool's own.
  printf '%s\n' "$out" \
    | grep -viE 'warning|site-packages|traceback|^[[:space:]]*\^' \
    | grep -oE '[0-9]+(\.[0-9]+)+' | head -1
}

# ── Platform ──────────────────────────────────────────────────────────────────
case "$(uname -s)" in
  Linux*)              OS=linux ;;
  Darwin*)             OS=darwin ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 2 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ARCH_GO="amd64"; ARCH_GITLEAKS="x64";  ARCH_TRIVY="64bit" ;;
  arm64|aarch64) ARCH_GO="arm64"; ARCH_GITLEAKS="arm64"; ARCH_TRIVY="ARM64" ;;
  *) echo "unsupported CPU architecture: $(uname -m)" >&2; exit 2 ;;
esac

EXE=""
[ "$OS" = "windows" ] && EXE=".exe"

# Trivy spells its platforms differently from everyone else.
TRIVY_OS="Linux"
[ "$OS" = "darwin" ] && TRIVY_OS="macOS"
[ "$OS" = "windows" ] && TRIVY_OS="windows"

mkdir -p "$BIN"
export PATH="$BIN:$PATH"
need curl >/dev/null 2>&1 || die "curl is required"

sha256_of() {
  if need sha256sum; then sha256sum "$1" | awk '{print $1}'
  elif need shasum; then shasum -a 256 "$1" | awk '{print $1}'
  else die "need sha256sum or shasum to verify downloads"; fi
}

fetch() {
  curl -fsSL --retry 2 --connect-timeout 20 --max-time 600 -o "$2" "$1" \
    || die "download failed: $1"
}

# verify_checksum <file> <checksums-url> <asset-name>
verify_checksum() {
  local file="$1" sums_url="$2" asset="$3" want got
  if ! fetch "$sums_url" "$TMP/checksums.txt" 2>/dev/null; then
    bad "no checksum manifest at $sums_url"
    return 1
  fi
  want="$(awk -v a="$asset" '$2==a || $2=="*"a {print $1}' "$TMP/checksums.txt" | head -1)"
  [ -n "$want" ] || { bad "no checksum entry for $asset"; return 1; }
  got="$(sha256_of "$file")"
  [ "$want" = "$got" ] || { bad "checksum mismatch for $asset"; return 1; }
  ok "checksum verified ($asset)"
}

extract_zip() { # <archive> <dest>
  mkdir -p "$2"
  if need unzip; then
    unzip -o -q "$1" -d "$2"
  elif need python3; then
    python3 -m zipfile -e "$1" "$2"
  elif need powershell.exe; then
    powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath '$(cygpath -w "$1")' -DestinationPath '$(cygpath -w "$2")' -Force" >/dev/null
  elif tar -tf "$1" >/dev/null 2>&1; then
    tar -xf "$1" -C "$2"          # bsdtar (macOS) reads zip
  else
    die "no unzip, python3, powershell or bsdtar available to extract $1"
  fi
}

# install_release <name> <repo> <version> <asset> <binary-in-archive> <checksums-file>
# Picks zip or tar.gz from the asset name, verifies the release checksum, then
# installs the binary into $BIN.
install_release() {
  local name="$1" repo="$2" version="$3" asset="$4" inner="$5" sums_file="$6"
  local url="https://github.com/$repo/releases/download/v$version/$asset"
  local sums="https://github.com/$repo/releases/download/v$version/$sums_file"

  fetch "$url" "$TMP/$asset"
  verify_checksum "$TMP/$asset" "$sums" "$asset" || die "refusing to install unverified $name"

  case "$asset" in
    *.zip)     extract_zip "$TMP/$asset" "$TMP/x-$name" ;;
    *.tar.gz)  mkdir -p "$TMP/x-$name"; tar -xzf "$TMP/$asset" -C "$TMP/x-$name" "$inner" ;;
    *)         die "unsupported archive type: $asset" ;;
  esac

  [ -f "$TMP/x-$name/$inner" ] || die "$name archive did not contain $inner"
  cp "$TMP/x-$name/$inner" "$BIN/$name$EXE"
  chmod +x "$BIN/$name$EXE"
  ok "$name $(tool_version "$name" || echo "$version") → $BIN/$name$EXE"
}

# Asset names differ per publisher, and so do their checksum manifests:
#   projectdiscovery (nuclei/httpx/katana)  <tool>_<ver>_<macOS|linux|windows>_<arch>.zip
#                                           nuclei_<ver>_checksums.txt, katana-<ver>-checksums.txt
#   ffuf                                    ffuf_<ver>_macOS_<arch>.tar.gz
#   dalfox                                  dalfox_<ver>_darwin_<arch>.tar.gz (also on Windows)
#   gitleaks                                gitleaks_<ver>_<darwin|windows>_<x64|arm64>
#   trivy                                   trivy_<ver>_<Linux|macOS|windows>-<64bit|ARM64>
PD_OS="$OS"
[ "$OS" = "darwin" ] && PD_OS="macOS"

install_tool() { # <name>
  local name="$1"
  case "$name" in
    nuclei)
      install_release nuclei projectdiscovery/nuclei "$NUCLEI_VERSION" \
        "nuclei_${NUCLEI_VERSION}_${PD_OS}_${ARCH_GO}.zip" "nuclei$EXE" \
        "nuclei_${NUCLEI_VERSION}_checksums.txt" ;;
    httpx)
      install_release httpx projectdiscovery/httpx "$HTTPX_VERSION" \
        "httpx_${HTTPX_VERSION}_${PD_OS}_${ARCH_GO}.zip" "httpx$EXE" \
        "httpx_${HTTPX_VERSION}_checksums.txt" ;;
    katana)
      install_release katana projectdiscovery/katana "$KATANA_VERSION" \
        "katana_${KATANA_VERSION}_${PD_OS}_${ARCH_GO}.zip" "katana$EXE" \
        "katana-${KATANA_VERSION}-checksums.txt" ;;
    ffuf)
      if [ "$OS" = "windows" ]; then
        install_release ffuf ffuf/ffuf "$FFUF_VERSION" \
          "ffuf_${FFUF_VERSION}_windows_${ARCH_GO}.zip" "ffuf.exe" \
          "ffuf_${FFUF_VERSION}_checksums.txt"
      else
        install_release ffuf ffuf/ffuf "$FFUF_VERSION" \
          "ffuf_${FFUF_VERSION}_${PD_OS}_${ARCH_GO}.tar.gz" "ffuf" \
          "ffuf_${FFUF_VERSION}_checksums.txt"
      fi ;;
    dalfox)
      # dalfox ships tar.gz for every platform, Windows included.
      install_release dalfox hahwul/dalfox "$DALFOX_VERSION" \
        "dalfox_${DALFOX_VERSION}_${OS}_${ARCH_GO}.tar.gz" "dalfox$EXE" \
        "dalfox_checksums.txt" ;;
    gitleaks)
      if [ "$OS" = "windows" ]; then
        install_release gitleaks gitleaks/gitleaks "$GITLEAKS_VERSION" \
          "gitleaks_${GITLEAKS_VERSION}_windows_${ARCH_GITLEAKS}.zip" "gitleaks.exe" \
          "gitleaks_${GITLEAKS_VERSION}_checksums.txt"
      else
        install_release gitleaks gitleaks/gitleaks "$GITLEAKS_VERSION" \
          "gitleaks_${GITLEAKS_VERSION}_${OS}_${ARCH_GITLEAKS}.tar.gz" "gitleaks" \
          "gitleaks_${GITLEAKS_VERSION}_checksums.txt"
      fi ;;
    trivy)
      if [ "$OS" = "windows" ]; then
        install_release trivy aquasecurity/trivy "$TRIVY_VERSION" \
          "trivy_${TRIVY_VERSION}_windows-${ARCH_TRIVY}.zip" "trivy.exe" \
          "trivy_${TRIVY_VERSION}_checksums.txt"
      else
        install_release trivy aquasecurity/trivy "$TRIVY_VERSION" \
          "trivy_${TRIVY_VERSION}_${TRIVY_OS}-${ARCH_TRIVY}.tar.gz" "trivy" \
          "trivy_${TRIVY_VERSION}_checksums.txt"
      fi ;;
    *) die "no download recipe for $name" ;;
  esac
}

# nmap is not a Go release: each platform has its own story.
install_nmap() {
  case "$OS" in
    linux)
      if [ -x "$ARGUS_HOME/scripts/livefire/install-tools.sh" ]; then
        # Rootless: Ubuntu packages extracted with dpkg-deb into .livefire/tools
        # plus a wrapper that sets LD_LIBRARY_PATH and NMAPDIR.
        "$ARGUS_HOME/scripts/livefire/install-tools.sh" >"$TMP/nmap.log" 2>&1 \
          || { tail -15 "$TMP/nmap.log"; die "nmap install failed"; }
        [ -x "$ARGUS_HOME/.livefire/bin/nmap" ] && [ "$ARGUS_HOME/.livefire/bin" != "$BIN" ] \
          && cp "$ARGUS_HOME/.livefire/bin/nmap" "$BIN/nmap"
        ok "nmap $(tool_version nmap || echo '?')"
      else
        die "install nmap with your package manager (apt-get install nmap)"
      fi ;;
    darwin)
      need brew || die "Homebrew is required to install nmap on macOS: https://brew.sh"
      brew install nmap >"$TMP/nmap.log" 2>&1 \
        || { tail -15 "$TMP/nmap.log"; die "brew install nmap failed"; }
      ln -sf "$(brew --prefix)/bin/nmap" "$BIN/nmap" 2>/dev/null || true
      ok "nmap $(tool_version nmap || echo '?')" ;;
    windows)
      if need winget; then
        winget install --id Insecure.Nmap -e --silent \
          --accept-source-agreements --accept-package-agreements >"$TMP/nmap.log" 2>&1 \
          || { tail -15 "$TMP/nmap.log"; die "winget install nmap failed"; }
      elif need choco; then
        choco install nmap -y --no-progress >"$TMP/nmap.log" 2>&1 \
          || { tail -15 "$TMP/nmap.log"; die "choco install nmap failed"; }
      else
        # Last resort: the official Windows zip (nmap stopped publishing these
        # after 7.92; newer releases are installer-only). nmap.org signs with
        # PGP rather than publishing sha256, so this is the one download the
        # script cannot checksum-verify.
        local zip="nmap-${NMAP_WIN_VERSION}-win32.zip"
        fetch "https://nmap.org/dist/$zip" "$TMP/$zip"
        skip "nmap.org publishes PGP signatures, not sha256 — download not checksum-verified"
        extract_zip "$TMP/$zip" "$TMP/nmap"
        local found
        found="$(find "$TMP/nmap" -maxdepth 3 -name nmap.exe 2>/dev/null | head -1)"
        [ -n "$found" ] || die "nmap.exe not found in $zip"
        cp "$found" "$BIN/nmap.exe"; chmod +x "$BIN/nmap.exe"
      fi
      # Package managers install outside Git Bash's PATH; link what we find.
      if ! need nmap; then
        for candidate in "/c/Program Files (x86)/Nmap/nmap.exe" "/c/Program Files/Nmap/nmap.exe"; do
          if [ -f "$candidate" ]; then cp "$candidate" "$BIN/nmap.exe"; chmod +x "$BIN/nmap.exe"; break; fi
        done
      fi
      tool_version nmap >/dev/null 2>&1 || bad "nmap installed but not on PATH — restart your shell"
      ok "nmap $(tool_version nmap || echo 'installed')" ;;
  esac
}

tool_ok() { # <name> <min-version>
  local name="$1" min="$2" v
  need "$name" || return 1
  v="$(tool_version "$name")" || return 1
  [ -n "$v" ] || return 1
  version_ge "$v" "$min"
}

# ── 1. Bun dependencies ───────────────────────────────────────────────────────
step "TypeScript engine dependencies"
if ! need bun; then
  bad "bun is not installed — install it with: curl -fsSL https://bun.sh/install | bash"
elif [ "$MODE" = "check" ]; then
  [ -d "$ARGUS_TUI/node_modules" ] && ok "Argus-Tui/node_modules present" || bad "Argus-Tui/node_modules missing"
elif [ -d "$ARGUS_TUI/node_modules" ] && [ "$FORCE" != "1" ]; then
  skip "Argus-Tui/node_modules present"
else
  ( cd "$ARGUS_TUI" && bun install ) >"$TMP/bun.log" 2>&1 \
    || { tail -20 "$TMP/bun.log"; die "bun install failed"; }
  ok "bun install ($(grep -oE '[0-9]+ packages installed' "$TMP/bun.log" | tail -1 || echo complete))"
fi

# ── 2. Python worker venv ─────────────────────────────────────────────────────
step "Python worker environment"
find_python() {
  local c
  for c in python3 python py; do
    if need "$c" && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}
if [ -x "$VENV/bin/python" ]; then VPY="$VENV/bin/python"
elif [ -x "$VENV/Scripts/python.exe" ]; then VPY="$VENV/Scripts/python.exe"
else VPY=""; fi

if [ -z "$VPY" ] && [ "$MODE" = "install" ]; then
  PY="$(find_python)" || die "Python 3.10+ is required"
  if need uv; then
    uv venv "$VENV" --python 3.12 >/dev/null 2>&1 || uv venv "$VENV" >/dev/null 2>&1 || "$PY" -m venv "$VENV"
  else
    "$PY" -m venv "$VENV"
  fi
  if [ -x "$VENV/bin/python" ]; then VPY="$VENV/bin/python"
  elif [ -x "$VENV/Scripts/python.exe" ]; then VPY="$VENV/Scripts/python.exe"
  else die "virtualenv creation failed at $VENV"; fi
fi

if [ -z "$VPY" ]; then
  bad "no venv at $VENV"
else
  ok "virtualenv python $("$VPY" --version 2>&1 | awk '{print $2}')"
  if [ "$MODE" = "install" ]; then
    if need uv; then PIP="uv pip install --python $VPY"
    else PIP="$VPY -m pip install"; fi
    for req in requirements.txt requirements-tools.txt; do
      echo "  installing $req"
      $PIP -r "$ARGUS_HOME/argus-workers/$req" >"$TMP/pip-$req.log" 2>&1 \
        || { tail -20 "$TMP/pip-$req.log"; die "pip install $req failed"; }
    done
    ok "python dependencies installed"
  fi
  # Console scripts the toolchain check looks for (bin/ on POSIX, Scripts/ on Windows).
  for script in semgrep sqlmap arjun; do
    for sdir in "$VENV/bin" "$VENV/Scripts"; do
      if [ -x "$sdir/$script" ]; then
        ln -sf "$sdir/$script" "$BIN/$script$([ "$sdir" = "$VENV/Scripts" ] && echo '.exe')" 2>/dev/null || true
        break
      fi
    done
  done
fi

# ── 3. Doctor-gated tools ─────────────────────────────────────────────────────
step "Core tools (nuclei, nmap, gitleaks, semgrep, trivy)"
for spec in "nuclei:3.0.0" "nmap:1.0.0" "gitleaks:1.0.0" "semgrep:1.0.0" "trivy:0.50.0"; do
  name="${spec%%:*}"; min="${spec##*:}"
  if tool_ok "$name" "$min"; then
    skip "$name $(tool_version "$name") already installed"
  elif [ "$MODE" = "check" ]; then
    bad "$name missing or older than $min"
  elif [ "$name" = "semgrep" ]; then
    need semgrep || die "semgrep did not install into the venv — run without --check to install python deps"
    ok "semgrep $(tool_version semgrep) from the worker venv"
  elif [ "$name" = "nmap" ]; then
    install_nmap
  else
    install_tool "$name"
  fi
done

# ── 4. Web / recon pack ───────────────────────────────────────────────────────
if [ "$PACK" = "all" ]; then
  step "Web and recon pack (httpx, katana, ffuf, dalfox, sqlmap, nikto)"
  for spec in "httpx:1.0.0" "katana:1.0.0" "ffuf:1.0.0" "dalfox:1.0.0" "sqlmap:1.0.0" "nikto:1.0.0"; do
    name="${spec%%:*}"; min="${spec##*:}"
    if tool_ok "$name" "$min"; then
      skip "$name $(tool_version "$name") already installed"
    elif [ "$MODE" = "check" ]; then
      bad "$name missing"
    elif [ "$name" = "sqlmap" ]; then
      skip "sqlmap comes from requirements-tools.txt (worker venv)"
    elif [ "$name" = "nikto" ]; then
      if [ "$OS" = "windows" ]; then
        skip "nikto has no native Windows build — install it under WSL if needed"
      elif [ -x "$ARGUS_HOME/scripts/livefire/install-nikto.sh" ]; then
        "$ARGUS_HOME/scripts/livefire/install-nikto.sh" >"$TMP/nikto.log" 2>&1 \
          || { tail -10 "$TMP/nikto.log"; bad "nikto install failed"; }
        ok "nikto installed"
      else
        bad "scripts/livefire/install-nikto.sh missing"
      fi
    else
      install_tool "$name"
    fi
  done
fi

# ── 5. Redis ──────────────────────────────────────────────────────────────────
missing=0
step "Redis"
if [ "$OS" = "windows" ]; then
  if need redis-cli && redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
    ok "redis responding on 127.0.0.1:6379"
  else
    bad "Redis has no native Windows build — run it with Docker: docker run -d -p 6379:6379 redis:7"
    if [ "$MODE" = "check" ]; then missing=1; fi
  fi
elif need redis-cli && redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
  ok "redis responding on 127.0.0.1:6379"
elif [ "$MODE" = "check" ]; then
  bad "redis not responding on 127.0.0.1:6379"; missing=1
else
  server=""
  for candidate in "$BIN/redis-server" "$VENV/bin/redis-server" \
      "$ARGUS_HOME/argus-workers/venv/lib/python3.12/site-packages/redislite/bin/redis-server"; do
    [ -x "$candidate" ] && { server="$candidate"; break; }
  done
  if [ -z "$server" ] && need redis-server; then server="$(command -v redis-server)"; fi
  if [ -z "$server" ]; then
    bad "no redis-server found — install redis (brew install redis / apt-get install redis-server)"
  else
    mkdir -p "$HOME/.argus/redis"
    "$server" --port 6379 --bind 127.0.0.1 --dir "$HOME/.argus/redis" --save '' --daemonize yes
    sleep 1
    if "$BIN/redis-cli" -p 6379 ping 2>/dev/null | grep -q PONG; then
      ok "redis started ($server)"
    else
      bad "redis failed to start"
    fi
  fi
fi

# ── 6. .env ───────────────────────────────────────────────────────────────────
step "Configuration"
if [ -f "$ARGUS_HOME/.env" ]; then
  ok ".env present"
elif [ -f "$ARGUS_HOME/.env.example" ] && [ "$MODE" = "install" ]; then
  cp "$ARGUS_HOME/.env.example" "$ARGUS_HOME/.env"
  ok ".env created from .env.example — set LLM_API_KEY to enable planning/analysis"
else
  bad ".env missing"
fi
if grep -qE '^LLM_API_KEY=.+' "$ARGUS_HOME/.env" 2>/dev/null; then
  ok "LLM_API_KEY configured"
else
  skip "LLM_API_KEY empty — non-LLM paths still run, planner stays deterministic"
fi

# ── 7. Verify ─────────────────────────────────────────────────────────────────
step "Verification"
for spec in "nuclei:3.0.0" "nmap:1.0.0" "gitleaks:1.0.0" "semgrep:1.0.0" "trivy:0.50.0"; do
  name="${spec%%:*}"; min="${spec##*:}"
  if tool_ok "$name" "$min"; then
    ok "$name $(tool_version "$name") ≥ $min"
  else
    bad "$name missing or < $min"; missing=1
  fi
done
if [ -n "$VPY" ] && "$VPY" -c "import yaml" >/dev/null 2>&1; then
  ok "worker python imports yaml (tool definitions load)"
else
  bad "worker python cannot import yaml — YAML tool definitions will be skipped"
fi

if [ "$MODE" = "install" ]; then
  step "argus doctor"
  ( cd "$ARGUS_HOME" && ./start-argus.sh doctor 2>&1 | tail -20 ) || true
fi

printf '\n%sNext:%s\n' "$B" "$N"
printf '  ./start-argus.sh doctor\n'
printf '  ./start-argus.sh assess <authorized-target>\n'
if [ "$missing" = "1" ]; then
  printf '\n%sSomething is still missing.%s Re-run: %s./scripts/argus-setup.sh --core%s\n' "$R" "$N" "$B" "$N"
  exit 1
fi

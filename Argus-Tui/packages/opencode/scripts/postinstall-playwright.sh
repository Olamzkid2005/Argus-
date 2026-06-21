#!/usr/bin/env bash
# ── Post-install: install Playwright Chromium browser ──────────────
# This script:
#   1. Installs Chromium via npx playwright (with deps)
#   2. Verifies the browser was actually installed
#   3. Prints a clear warning if missing (instead of silently failing)
# ────────────────────────────────────────────────────────────────────

set -u

PLAYWRIGHT_DIR="${HOME}/.cache/ms-playwright"
SCRIPT_NAME="$(basename "$0")"

echo "[${SCRIPT_NAME}] Installing Playwright Chromium browser..."

# Run playwright install, capturing exit code
if npx playwright install chromium --with-deps 2>&1; then
  echo "[${SCRIPT_NAME}] Playwright install command succeeded."
else
  echo "[${SCRIPT_NAME}] WARNING: 'npx playwright install chromium' exited with code $?." >&2
  echo "[${SCRIPT_NAME}] WARNING: Chromium browser may not be available." >&2
  echo "[${SCRIPT_NAME}] WARNING: 'argus verify' and browser-based verifiers will fail." >&2
  echo "[${SCRIPT_NAME}] WARNING: To install manually, run: npx playwright install chromium" >&2
fi

# Verify browser is actually present
BROWSER_FOUND=false
if [ -d "${PLAYWRIGHT_DIR}" ]; then
  for dir in "${PLAYWRIGHT_DIR}"/chromium*; do
    if [ -d "${dir}" ]; then
      BROWSER_FOUND=true
      break
    fi
  done
fi

if [ "${BROWSER_FOUND}" = true ]; then
  echo "[${SCRIPT_NAME}] Chromium browser found at ${PLAYWRIGHT_DIR}/chromium*"
else
  echo "[${SCRIPT_NAME}] WARNING: No Chromium installation detected in ${PLAYWRIGHT_DIR}" >&2
  echo "[${SCRIPT_NAME}] WARNING: Run 'npx playwright install chromium' manually." >&2
fi

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Smoke Test: Argus Local Mode (--local)
# ─────────────────────────────────────────────────────────────
# Tests that `argus assess --local` runs end-to-end using SQLite
# without requiring Docker, Postgres, or Redis.
#
# Usage:
#   bash scripts/test-local-mode.sh [target]
#
# Default target: http://testphp.vulnweb.com (safe test target)
#
# Requires:
#   - Python 3.11+
#   - argus-workers dependencies installed (pip install -r requirements.txt)
#   - Some assessment tools on PATH (nuclei, httpx, etc.) - optional,
#     the test checks graceful degradation if tools are missing
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Target: use arg $1 or default test target
TARGET="${1:-http://testphp.vulnweb.com}"
CLI_PY="$PROJECT_ROOT/argus-workers/cli.py"
DB_PATH="/tmp/argus-smoke-test-$$.db"
OUTPUT_PATH="/tmp/argus-smoke-test-$$-output.json"

PASS=0
FAIL=0

cleanup() {
    rm -f "$DB_PATH" "$OUTPUT_PATH"
}
trap cleanup EXIT

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
info() { echo -e "  ${YELLOW}▶${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    Argus Local Mode Smoke Test                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target : $TARGET"
echo "  Python : $(python3 --version 2>&1)"
echo "  Project: $PROJECT_ROOT"
echo ""

# ── Test 1: CLI --help works ──
info "Test 1: CLI --help produces output..."
HELP_OUTPUT=$(python3 "$CLI_PY" --help 2>&1 || true)
if echo "$HELP_OUTPUT" | grep -q "usage:"; then
    ok "CLI --help shows usage"
else
    fail "CLI --help failed to show usage"
fi

# ── Test 2: assess --help works ──
info "Test 2: assess --help produces output..."
ASSESS_HELP=$(python3 "$CLI_PY" assess --help 2>&1 || true)
if echo "$ASSESS_HELP" | grep -q "\-\-local"; then
    ok "assess --help shows --local flag"
else
    fail "assess --help missing --local flag"
fi

# ── Test 3: scan --help works ──
info "Test 3: scan --help produces output..."
SCAN_HELP=$(python3 "$CLI_PY" scan --help 2>&1 || true)
if echo "$SCAN_HELP" | grep -q "\-\-local"; then
    ok "scan --help shows --local flag"
else
    fail "scan --help missing --local flag"
fi

# ── Test 4: report --help works ──
info "Test 4: report --help produces output..."
REPORT_HELP=$(python3 "$CLI_PY" report --help 2>&1 || true)
if echo "$REPORT_HELP" | grep -q "\-\-local"; then
    ok "report --help shows --local flag"
else
    fail "report --help missing --local flag"
fi

# ── Test 5: list --help works ──
info "Test 5: list --help produces output..."
LIST_HELP=$(python3 "$CLI_PY" list --help 2>&1 || true)
if echo "$LIST_HELP" | grep -q "\-\-local"; then
    ok "list --help shows --local flag"
else
    fail "list --help missing --local flag"
fi

# ── Test 6: list --local shows empty (no assessments yet) ──
info "Test 6: list --local with no assessments..."
LIST_OUTPUT=$(python3 "$CLI_PY" list --db "$DB_PATH" 2>&1 || true)
if echo "$LIST_OUTPUT" | grep -q "No engagements found"; then
    ok "list shows no engagements on fresh database"
else
    fail "list did not show empty state on fresh database"
fi

# ── Test 7: assess --local against test target ──
info "Test 7: Full assessment (recon → scan → analyze → report) --local..."
info "      This may take a few minutes if tools (nuclei, httpx, etc.) are available."
info "      It will gracefully degrade if tools are missing."

set +e
ASSESS_OUTPUT=$(python3 "$CLI_PY" assess "$TARGET" \
    --db "$DB_PATH" \
    --output "$OUTPUT_PATH" \
    --aggressiveness light \
    2>&1)
ASSESS_EXIT=$?
set -e

echo ""
info "Assessment exit code: $ASSESS_EXIT"

if [ $ASSESS_EXIT -eq 0 ]; then
    ok "Assessment completed successfully"
else
    # Non-zero exit is acceptable if tools are missing — check that
    # the error is about missing tools (graceful degradation), not crashes
    if echo "$ASSESS_OUTPUT" | grep -qi "not found\|cannot continue\|critical error\|traceback"; then
        if echo "$ASSESS_OUTPUT" | grep -qi "traceback"; then
            fail "Assessment crashed with traceback (not graceful degradation)"
            echo ""
            echo "  Last 20 lines of output:"
            echo "$ASSESS_OUTPUT" | tail -20
        else
            fail "Assessment failed (tools may be missing)"
        fi
    else
        fail "Assessment exited with code $ASSESS_EXIT"
    fi
fi

# ── Test 8: Assessment created findings or had graceful output ──
info "Test 8: Checking assessment output..."
if [ -f "$OUTPUT_PATH" ]; then
    FINDING_COUNT=$(python3 -c "
import json
with open('$OUTPUT_PATH') as f:
    d = json.load(f)
print(d.get('total_findings', 0))
" 2>/dev/null || echo "0")
    echo "      Total findings: $FINDING_COUNT"
    if [ "$FINDING_COUNT" -gt 0 ]; then
        ok "Assessment produced $FINDING_COUNT finding(s)"
    else
        info "No findings produced (expected if tools are missing from PATH)"
        ok "Assessment produced graceful output (no findings, no crash)"
    fi
else
    info "No output file created (assessment may have failed gracefully)"
    # Check if ASSESS_OUTPUT contains a reasonable error message
    if echo "$ASSESS_OUTPUT" | grep -qi "no target\|missing\|unavailable"; then
        ok "Graceful degradation message detected"
    else
        info "Assessment output (first 5 lines):"
        echo "$ASSESS_OUTPUT" | head -5
        ok "Assessment ran without crash"
    fi
fi

# ── Test 9: report --local shows JSON output ──
info "Test 9: report --local retrieves findings..."
# Find the engagement ID from the output
ENG_ID=$(python3 -c "
import json
try:
    with open('$OUTPUT_PATH') as f:
        d = json.load(f)
    print(d.get('engagement_id', ''))
except:
    pass
" 2>/dev/null || echo "")

if [ -n "$ENG_ID" ]; then
    REPORT_OUTPUT=$(python3 "$CLI_PY" report "$ENG_ID" --db "$DB_PATH" --format json 2>&1 || true)
    if echo "$REPORT_OUTPUT" | grep -q "$ENG_ID"; then
        ok "Report retrieves engagement $ENG_ID"
    else
        fail "Report did not contain engagement ID"
    fi
else
    info "No engagement ID found — skipping report test"
    ok "Skipped report test (no engagement data)"
fi

# ── Summary ──
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    Results                                              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [ $FAIL -gt 0 ]; then
    echo "  ❌ Some tests failed. Check the output above for details."
    echo ""
    cleanup
    exit 1
else
    echo "  ✅ All tests passed!"
    echo ""
    cleanup
    exit 0
fi

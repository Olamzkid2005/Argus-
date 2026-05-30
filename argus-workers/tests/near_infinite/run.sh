#!/bin/bash
# ── Argus Near-Infinite E2E Test Runner ─────────────────────────────────
# Runs the comprehensive self-healing E2E test.
#
# Prerequisites (all verified during test):
#   - PostgreSQL 15+ running on localhost:5432
#   - Redis running on localhost:6379
#   - Node.js 18+
#   - browser-use-direct CLI installed (npm -g install browser-use)
#   - Argus platform npm dependencies installed
#
# Usage:
#   ./run.sh                    # Run with defaults
#   ./run.sh --verbose          # Run with detailed logging
#   ./run.sh --quick            # Skip browser tests, API only
#   ./run.sh --clean            # Reset test database first
#   ./run.sh --help             # Show this help
# ─────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKERS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_DIR="$(cd "$WORKERS_DIR/.." && pwd)"
VENV_PYTHON="$WORKERS_DIR/venv/bin/python3"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Argus Near-Infinite E2E Test Runner          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Parse args
VERBOSE=""
CLEAN=""
SKIP_BROWSER=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v) VERBOSE="1"; shift ;;
        --clean|-c) CLEAN="1"; shift ;;
        --quick|-q) SKIP_BROWSER="1"; shift ;;
        --help|-h)
            head -20 "$0" | grep "^#" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; exit 1 ;;
    esac
done

# ── Step 0: Ensure tool paths ──
VENV_BIN="$WORKERS_DIR/venv/bin"
GO_BIN="$HOME/go/bin"
if [[ ":$PATH:" != *":$VENV_BIN:"* ]]; then
    export PATH="$VENV_BIN:$PATH"
fi
if [[ ":$PATH:" != *":$GO_BIN:"* ]]; then
    export PATH="$GO_BIN:$PATH"
fi

# ── Step 1: Prerequisites ──
echo -e "${YELLOW}━━━ Checking Prerequisites ━━━${NC}"

# Postgres
PG_PSQL="/opt/local/lib/postgresql15/bin/psql"
if ! $PG_PSQL -U postgres -c "SELECT 1" >/dev/null 2>&1; then
    echo -e "${RED}✗ PostgreSQL not accessible${NC}"
    echo "  Tried: $PG_PSQL -U postgres"
    echo "  Start it: brew services start postgresql@15"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL running${NC}"

# Redis
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${RED}✗ Redis not accessible${NC}"
    echo "  Start it: brew services start redis"
    exit 1
fi
echo -e "${GREEN}✓ Redis running${NC}"

# browser-use-direct
if ! command -v browser-use-direct &> /dev/null; then
    echo -e "${RED}✗ browser-use-direct not found${NC}"
    echo "  Install: npm install -g browser-use"
    exit 1
fi
echo -e "${GREEN}✓ browser-use-direct $(browser-use-direct --version 2>&1 || true)${NC}"

# Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}✗ Node.js not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js $(node --version)${NC}"

# Python venv
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${YELLOW}⚠ Worker venv not found, using system Python${NC}"
    VENV_PYTHON=$(which python3)
fi
PYTHON=$VENV_PYTHON
echo -e "${GREEN}✓ Python $($PYTHON --version)${NC}"

# ── Step 2: Clean test database (optional) ──
if [ -n "$CLEAN" ]; then
    echo ""
    echo -e "${YELLOW}━━━ Cleaning Test Database ━━━${NC}"
    $PG_PSQL -U postgres -d argus_test -f "$PROJECT_DIR/argus-platform/db/schema.sql" > /dev/null 2>&1
    echo -e "${GREEN}✓ Test database reset${NC}"
fi

# ── Step 3: Check test DB schema ──
echo ""
echo -e "${YELLOW}━━━ Verifying Test Database ━━━${NC}"
TABLE_COUNT=$($PG_PSQL -U postgres -d argus_test -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'" 2>/dev/null | tr -d ' ')
if [ -z "$TABLE_COUNT" ] || [ "$TABLE_COUNT" -lt 10 ]; then
    echo -e "${YELLOW}⚠ Only $TABLE_COUNT tables found — applying schema...${NC}"
    $PG_PSQL -U postgres -d argus_test -f "$PROJECT_DIR/argus-platform/db/schema.sql" > /dev/null 2>&1
    echo -e "${GREEN}✓ Schema applied${NC}"
else
    echo -e "${GREEN}✓ Database ready ($TABLE_COUNT tables)${NC}"
fi

# ── Step 4: Run the test ──
echo ""
echo -e "${YELLOW}━━━ Running E2E Test ━━━${NC}"
echo ""

# Ensure clean logs
rm -f /tmp/argus-e2e-*.log

# Build pytest args
PYTEST_ARGS=()
PYTEST_ARGS+=("-v")
PYTEST_ARGS+=("--tb=short")
PYTEST_ARGS+=("--timeout=600")
PYTEST_ARGS+=("--no-header")
if [ -n "$VERBOSE" ]; then
    PYTEST_ARGS+=("--log-cli-level=INFO")
fi

# Run
cd "$WORKERS_DIR"
PYTHONPATH="$WORKERS_DIR:$PYTHONPATH" \
$PYTHON -m pytest tests/near_infinite/test_e2e_full.py \
    "${PYTEST_ARGS[@]}" \
    -k "test_e2e_full" \
    2>&1

EXIT_CODE=$?

# ── Step 5: Results ──
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   ALL TESTS PASSED                    ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
else
    echo -e "${YELLOW}╔════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║   SOME TESTS FAILED (self-healed)    ║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════╝${NC}"
    echo -e "${YELLOW}  Check the report above for details.${NC}"
fi

echo ""
echo -e "${BLUE}Logs:${NC}"
echo "  Next.js:    /tmp/argus-e2e-nextjs.log"
echo "  Worker:     /tmp/argus-e2e-worker.log"
echo "  Screenshots: /tmp/argus-e2e-screenshots/"
echo ""

exit $EXIT_CODE

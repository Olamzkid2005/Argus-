#!/bin/bash

# Argus V5 Startup Script
# Launches the V5 TypeScript CLI directly without Redis/Celery overhead.
#
# Usage:
#   ./start-argus.sh                  # Show argus commands
#   ./start-argus.sh doctor           # Health check
#   ./start-argus.sh assess <target>  # Full assessment
#   ./start-argus.sh test             # Run unit tests
#   ./start-argus.sh <command>        # Any argus command
#   ./start-argus.sh --help           # All available commands

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGUS_PKG="$SCRIPT_DIR/Argus-Tui/packages/opencode"

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[FAIL]${NC} $1"; }

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Argus V5 — Security AI Agent       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# ── Prerequisites ──
echo -e "${YELLOW}━━━ Checking Prerequisites ━━━${NC}"

if ! command -v bun >/dev/null 2>&1; then
    log_error "Bun is not installed. Install it: curl -fsSL https://bun.sh/install | bash"
    exit 1
fi
log_ok "Bun $(bun --version)"

# ── Install dependencies if needed ──
echo ""
echo -e "${YELLOW}━━━ Dependencies ━━━${NC}"

if [ ! -f "$ARGUS_PKG/node_modules/.package-lock.json" ] && [ ! -d "$ARGUS_PKG/node_modules" ]; then
    log_info "Installing dependencies..."
    cd "$SCRIPT_DIR/Argus-Tui" && bun install --ignore-scripts 2>&1 | tail -1
    log_ok "Dependencies installed"
else
    log_ok "Dependencies already satisfied"
fi

# ── Handle command ──
cd "$ARGUS_PKG"

case "${1:-}" in
    test)
        shift
        echo ""
        echo -e "${YELLOW}━━━ Running Unit Tests ━━━${NC}"
        bun test test/argus/ --timeout 30000 "$@"
        ;;
    doctor)
        shift
        echo ""
        echo -e "${YELLOW}━━━ Health Check ━━━${NC}"
        bun run src/argus/main.ts doctor "$@"
        ;;
    assess)
        shift
        if [ $# -eq 0 ]; then
            log_error "Usage: ./start-argus.sh assess <target> [--deterministic]"
            exit 1
        fi
        echo ""
        echo -e "${YELLOW}━━━ Assessment ━━━${NC}"
        bun run src/argus/main.ts assess "$@"
        ;;
    *)
        # Pass through to argus CLI
        bun run src/argus/main.ts "$@"
        ;;
esac

echo ""
log_info "Done."

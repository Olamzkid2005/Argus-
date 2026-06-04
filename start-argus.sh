#!/bin/bash

# ════════════════════════════════════════════════════════════════
#  Argus — Autonomous Security Assessment Platform
# ════════════════════════════════════════════════════════════════
#
# Launcher for the Argus security platform.
#
# Usage:
#   ./start-argus.sh                              # Run full test suite
#   ./start-argus.sh doctor                       # Health check
#   ./start-argus.sh assess <target>              # Run assessment
#   ./start-argus.sh --target example.com          # Test suite with custom target
#   ./start-argus.sh --doctor-only                 # Test suite: health only
#   ./start-argus.sh --help                       # Show full help
# ════════════════════════════════════════════════════════════════

set -o pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGUS_PKG="$SCRIPT_DIR/Argus-Tui/packages/opencode"

# ── Help ────────────────────────────────────────────────────────

show_help() {
  echo ""
  echo "Usage: ./start-argus.sh [command] [options]"
  echo ""
  echo "Commands:"
  echo "  (no args)     Run full multi-phase test suite"
  echo "  doctor        Run health checks (argus doctor)"
  echo "  assess <url>  Run assessment (argus assess <url>)"
  echo "  test          Run unit tests (bun test)"
  echo ""
  echo "Test Suite Options:"
  echo "  --target <domain>    Target for test suite (default: example.com)"
  echo "  --doctor-only        Skip assessment, health only"
  echo "  --assess-only        Skip health, assessment only"
  echo "  --max-retries <n>    Retry limit (default: 3)"
  echo "  --help               Show this help"
  echo ""
  exit 0
}

# ── Command dispatch ────────────────────────────────────────────

case "${1:-}" in
  --help|-h)
    show_help
    ;;
  doctor)
    shift
    cd "$ARGUS_PKG" || exit 1
    echo -e "${BLUE}[Argus] Running health checks...${NC}"
    bun run src/argus/main.ts doctor "$@"
    ;;
  assess)
    shift
    if [ $# -eq 0 ]; then
      echo -e "${RED}Usage: ./start-argus.sh assess <target>${NC}"
      exit 1
    fi
    cd "$ARGUS_PKG" || exit 1
    echo -e "${BLUE}[Argus] Running assessment against $1...${NC}"
    bun run src/argus/main.ts assess "$@"
    ;;
  test)
    shift
    cd "$ARGUS_PKG" || exit 1
    echo -e "${BLUE}[Argus] Running tests...${NC}"
    bun test test/argus/ --timeout 30000 "$@"
    ;;
  *)
    # Run full test suite (default behavior)
    exec "$SCRIPT_DIR/scripts/e2e-test.sh" "$@"
    ;;
esac

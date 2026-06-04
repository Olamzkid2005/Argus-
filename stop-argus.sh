#!/bin/bash

# ════════════════════════════════════════════════════════════════
#  Argus — Cleanup Script
# ════════════════════════════════════════════════════════════════
#
# The Argus CLI is stateless — no background daemons to stop.
# This script cleans up any stale processes from the v4 Python
# era and provides diagnostics.
#
# Usage:
#   ./stop-argus.sh                    # Cleanup stale processes
#   ./stop-argus.sh --help             # Show help
# ════════════════════════════════════════════════════════════════

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Argus — Cleanup                    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Clean up any stale v4 Python processes (if still running)
if pgrep -f "celery.*worker" >/dev/null 2>&1; then
    echo -e "${YELLOW}Stopping stale Celery workers (v4)...${NC}"
    pkill -f "celery.*worker" 2>/dev/null || true
    echo -e "${GREEN}✓ Done${NC}"
fi

# Clean up any leftover PID files
rm -f "$SCRIPT_DIR/logs/celery.pid" "$SCRIPT_DIR/logs/celery_beat.pid" 2>/dev/null || true

echo -e "${GREEN}✓ Argus V5 is stateless — nothing to stop.${NC}"
echo ""
echo "For V5 you can also:"
echo "  ./start-argus.sh doctor              # Health check"
echo "  ./start-argus.sh assess <target>     # Run assessment"
echo "  ./start-argus.sh test                # Run tests"
echo ""

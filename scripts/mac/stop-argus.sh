#!/bin/bash

# Argus CLI Stop Script
# Stops Celery workers and cleans up

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Stopping Argus Services              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f logs/celery.pid ]; then
    CELERY_PID=$(cat logs/celery.pid)
    echo -e "${YELLOW}Stopping Celery workers (PID: $CELERY_PID)...${NC}"
    if kill -0 $CELERY_PID 2>/dev/null; then
        kill $CELERY_PID 2>/dev/null || true
        sleep 2
        kill -9 $CELERY_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Celery workers stopped${NC}"
    fi
    rm -f logs/celery.pid
fi

echo -e "${YELLOW}Final cleanup...${NC}"
pkill -f "celery.*worker" 2>/dev/null || true
pkill -f "celery.*beat" 2>/dev/null || true

rm -f logs/celery.pid logs/celery_beat.pid 2>/dev/null || true

echo -e "${GREEN}✓ Cleanup complete${NC}"

echo ""
echo -e "${GREEN}All services stopped!${NC}"
echo ""

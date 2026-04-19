#!/bin/bash

# Argus Platform Stop Script
# Stops both Next.js dashboard and Python Celery workers

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Stopping Argus Platform Services    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Stop Next.js
if [ -f logs/nextjs.pid ]; then
    NEXTJS_PID=$(cat logs/nextjs.pid)
    echo -e "${YELLOW}Stopping Next.js (PID: $NEXTJS_PID)...${NC}"
    if kill $NEXTJS_PID 2>/dev/null; then
        echo -e "${GREEN}✓ Next.js stopped${NC}"
    else
        echo -e "${YELLOW}⚠ Next.js process not found (may have already stopped)${NC}"
    fi
    rm logs/nextjs.pid
else
    echo -e "${YELLOW}⚠ No Next.js PID file found${NC}"
fi

# Stop Celery
if [ -f logs/celery.pid ]; then
    CELERY_PID=$(cat logs/celery.pid)
    echo -e "${YELLOW}Stopping Celery workers (PID: $CELERY_PID)...${NC}"
    if kill $CELERY_PID 2>/dev/null; then
        echo -e "${GREEN}✓ Celery workers stopped${NC}"
    else
        echo -e "${YELLOW}⚠ Celery process not found (may have already stopped)${NC}"
    fi
    rm logs/celery.pid
else
    echo -e "${YELLOW}⚠ No Celery PID file found${NC}"
fi

# Kill any remaining node/celery processes (fallback)
echo -e "${YELLOW}Cleaning up any remaining processes...${NC}"
pkill -f "next dev" 2>/dev/null && echo -e "${GREEN}✓ Cleaned up Next.js processes${NC}" || true
pkill -f "celery.*worker" 2>/dev/null && echo -e "${GREEN}✓ Cleaned up Celery processes${NC}" || true

echo ""
echo -e "${GREEN}All services stopped!${NC}"
echo ""

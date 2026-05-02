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

# Stop Next.js (try PID file first, then fallback to pkill)
if [ -f logs/nextjs.pid ]; then
    NEXTJS_PID=$(cat logs/nextjs.pid)
    echo -e "${YELLOW}Stopping Next.js (PID: $NEXTJS_PID)...${NC}"
    if kill -0 $NEXTJS_PID 2>/dev/null; then
        kill $NEXTJS_PID 2>/dev/null || true
        sleep 1
        kill -9 $NEXTJS_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Next.js stopped${NC}"
    fi
    rm -f logs/nextjs.pid
fi

# Also kill any Next.js dev server processes
pkill -f "next-server" 2>/dev/null && echo -e "${GREEN}✓ Killed next-server processes${NC}" || true

# Stop Celery (try PID file first, then use pkill for all celery processes)
if [ -f logs/celery.pid ]; then
    CELERY_PID=$(cat logs/celery.pid)
    echo -e "${YELLOW}Stopping Celery workers (PID: $CELERY_PID)...${NC}"
    if kill -0 $CELERY_PID 2>/dev/null; then
        # Graceful shutdown first
        kill $CELERY_PID 2>/dev/null || true
        sleep 2
        # Force kill if still running
        pkill -f "celery.*worker" 2>/dev/null || true
        echo -e "${GREEN}✓ Celery workers stopped${NC}"
    fi
    rm -f logs/celery.pid
fi

# Stop Celery Beat (PID file or pkill)
if [ -f logs/celery_beat.pid ]; then
    BEAT_PID=$(cat logs/celery_beat.pid)
    echo -e "${YELLOW}Stopping Celery Beat (PID: $BEAT_PID)...${NC}"
    if kill -0 $BEAT_PID 2>/dev/null; then
        kill $BEAT_PID 2>/dev/null || true
        sleep 1
        kill -9 $BEAT_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Celery Beat stopped${NC}"
    fi
    rm -f logs/celery_beat.pid
fi

# Kill any remaining node/celery processes (fallback)
echo -e "${YELLOW}Final cleanup...${NC}"
pkill -f "next dev" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true  
pkill -f "celery.*worker" 2>/dev/null || true
pkill -f "celery.*beat" 2>/dev/null || true
pkill -f "python.*celery" 2>/dev/null || true
echo -e "${GREEN}✓ Cleanup complete${NC}"

echo ""
echo -e "${GREEN}All services stopped!${NC}"
echo ""

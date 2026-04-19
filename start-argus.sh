#!/bin/bash

# Argus Platform Startup Script
# Starts both Next.js dashboard and Python Celery workers

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Argus Pentest Platform Launcher     ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo ""

# Check if Redis is running
echo -e "${YELLOW}[1/4] Checking Redis...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis is running${NC}"
else
    echo -e "${RED}✗ Redis is not running. Please start Redis first:${NC}"
    echo -e "${RED}  sudo port load redis${NC}"
    exit 1
fi

# Check if PostgreSQL is accessible
echo -e "${YELLOW}[2/4] Checking PostgreSQL...${NC}"
if nc -z localhost 5432 > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL is accessible${NC}"
else
    echo -e "${RED}✗ PostgreSQL is not accessible. Please start PostgreSQL first:${NC}"
    echo -e "${RED}  sudo port load postgresql15-server${NC}"
    exit 1
fi

# Create log directory
mkdir -p logs

# Start Next.js dashboard in background
echo -e "${YELLOW}[3/4] Starting Next.js dashboard...${NC}"
cd argus-platform
npm run dev > ../logs/nextjs.log 2>&1 &
NEXTJS_PID=$!
cd ..
echo -e "${GREEN}✓ Next.js started (PID: $NEXTJS_PID)${NC}"
echo -e "  Logs: logs/nextjs.log"

# Wait a moment for Next.js to initialize
sleep 2

# Start Python Celery workers in background
echo -e "${YELLOW}[4/4] Starting Celery workers...${NC}"
cd argus-workers

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}✗ Virtual environment not found. Creating one...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

celery -A celery_app worker --loglevel=info --concurrency=4 > ../logs/celery.log 2>&1 &
CELERY_PID=$!
cd ..
echo -e "${GREEN}✓ Celery workers started (PID: $CELERY_PID)${NC}"
echo -e "  Logs: logs/celery.log"

# Save PIDs to file for cleanup
echo "$NEXTJS_PID" > logs/nextjs.pid
echo "$CELERY_PID" > logs/celery.pid

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Argus Platform is Running!        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Dashboard:${NC}  http://localhost:3000"
echo -e "${BLUE}Next.js Logs:${NC} tail -f logs/nextjs.log"
echo -e "${BLUE}Celery Logs:${NC}  tail -f logs/celery.log"
echo ""
echo -e "${YELLOW}To stop all services, run:${NC} ./stop-argus.sh"
echo ""

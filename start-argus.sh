#!/bin/bash

# Argus Platform Startup Script
# Starts both Next.js dashboard and Python Celery workers
#
# Usage: ./start-argus.sh
#        ./start-argus.sh --force    # Kill existing processes first

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Helper functions ──

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[FAIL]${NC} $1"; }

# Exit with error message and cleanup
die() {
    log_error "$1"
    echo ""
    echo -e "${YELLOW}Run ./stop-argus.sh to clean up, then try again.${NC}"
    exit 1
}

# Check if a port is already in use
check_port() {
    local port=$1
    local name=$2
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        if [ "$FORCE" = "1" ]; then
            log_warn "$name port $port is in use — killing existing process..."
            lsof -Pi :$port -sTCP:LISTEN -t | xargs kill -9 2>/dev/null
            sleep 1
        else
            log_error "$name is already running on port $port"
            log_info "Use ./start-argus.sh --force to restart anyway"
            exit 1
        fi
    fi
}

# Check if a process is running by pattern
check_process() {
    local pattern=$1
    local name=$2
    if pgrep -f "$pattern" >/dev/null 2>&1; then
        if [ "$FORCE" = "1" ]; then
            log_warn "$name already running — stopping first..."
            pkill -f "$pattern" 2>/dev/null
            sleep 2
        else
            log_error "$name is already running"
            log_info "Use ./start-argus.sh --force to restart anyway"
            exit 1
        fi
    fi
}

# Wait for a service to be healthy
wait_for_service() {
    local url=$1
    local name=$2
    local timeout=${3:-30}
    local interval=${4:-1}
    local elapsed=0
    
    log_info "Waiting for $name to be ready..."
    while [ $elapsed -lt $timeout ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200\|302\|401"; then
            log_ok "$name is ready"
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
    done
    log_error "$name did not become ready within ${timeout}s"
    return 1
}

# ── Parse args ──

FORCE=0
if [ "$1" = "--force" ] || [ "$1" = "-f" ]; then
    FORCE=1
    log_warn "Force mode: will kill existing processes"
fi

# ── Banner ──

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Argus Pentest Platform Launcher     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Check prerequisites ──

echo -e "${YELLOW}━━━ Checking Prerequisites ━━━${NC}"

# Node.js
if ! command -v node >/dev/null 2>&1; then
    die "Node.js is not installed or not in PATH"
fi
NODE_VERSION=$(node --version)
log_ok "Node.js $NODE_VERSION"

# Python 3
if ! command -v python3 >/dev/null 2>&1; then
    die "Python 3 is not installed or not in PATH"
fi
PYTHON_VERSION=$(python3 --version)
log_ok "$PYTHON_VERSION"

# Redis
echo -n "  Checking Redis... "
if redis-cli ping >/dev/null 2>&1 || /opt/local/bin/redis-cli ping >/dev/null 2>&1; then
    log_ok "running"
elif pgrep -x redis-server >/dev/null 2>&1; then
    log_ok "running"
else
    log_warn "not running, attempting to start..."
    redis-server --daemonize yes 2>/dev/null || true
    sleep 2
    if redis-cli ping >/dev/null 2>&1; then
        log_ok "started"
    else
        die "Could not start Redis. Install it with: brew install redis"
    fi
fi

# PostgreSQL
echo -n "  Checking PostgreSQL... "
if nc -z localhost 5432 >/dev/null 2>&1 || /opt/local/bin/nc -z localhost 5432 >/dev/null 2>&1; then
    log_ok "accessible on port 5432"
else
    log_warn "may not be accessible on port 5432"
    log_info "If PostgreSQL is not running, start it with: brew services start postgresql"
fi

# ── Step 2: Pre-flight checks ──

echo ""
echo -e "${YELLOW}━━━ Pre-flight Checks ━━━${NC}"

# Check if already running
check_port 3000 "Next.js"
check_process "celery.*worker" "Celery"

# Ensure log directory exists
mkdir -p logs || die "Cannot create logs directory"
log_ok "Log directory ready"

# ── Step 3: Start Next.js ──

echo ""
echo -e "${YELLOW}━━━ Starting Next.js Dashboard ━━━${NC}"

cd argus-platform || die "argus-platform directory not found"

# Check node_modules
if [ ! -d "node_modules" ]; then
    log_warn "node_modules missing — running npm install..."
    npm install || die "npm install failed"
fi

# Clear corrupted build cache if it exists
if [ -d ".next" ]; then
    log_info "Clearing Next.js build cache..."
    rm -rf .next node_modules/.cache 2>/dev/null || true
fi

npm run dev > ../logs/nextjs.log 2>&1 &
NEXTJS_PID=$!
cd ..

# Wait for Next.js to actually start
sleep 3
if ! kill -0 $NEXTJS_PID 2>/dev/null; then
    die "Next.js failed to start. Check logs/nextjs.log"
fi

log_ok "Next.js started (PID: $NEXTJS_PID)"
log_info "Logs: logs/nextjs.log"

# Health check
if ! wait_for_service "http://localhost:3000" "Next.js" 30 2; then
    die "Next.js health check failed. Check logs/nextjs.log"
fi

# ── Step 4: Load environment ──

echo ""
echo -e "${YELLOW}━━━ Loading Environment ━━━${NC}"

if [ -f "argus-platform/.env.local" ]; then
    # Safer env loading — handles spaces and special chars better than xargs
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        case "$line" in
            \#*|'') continue ;;
        esac
        export "$line"
    done < "argus-platform/.env.local"
    log_ok "Environment loaded from .env.local"
else
    log_warn ".env.local not found — services may fail"
fi

# Verify critical env vars
if [ -z "$DATABASE_URL" ]; then
    log_warn "DATABASE_URL is not set"
fi
if [ -z "$REDIS_URL" ]; then
    export REDIS_URL="redis://localhost:6379"
    log_info "Using default REDIS_URL=$REDIS_URL"
fi

# ── Step 5: Start Celery ──

echo ""
echo -e "${YELLOW}━━━ Starting Celery Workers ━━━${NC}"

cd argus-workers || die "argus-workers directory not found"

# Check virtual environment
if [ ! -d "venv" ]; then
    log_warn "Virtual environment not found. Creating one..."
    python3 -m venv venv || die "Failed to create Python venv"
fi

source venv/bin/activate || die "Failed to activate Python venv"

# Check requirements — skip pip install if core deps are already available.
# This avoids rebuild failures (e.g. pydantic-core on Python 3.14) when deps
# were previously installed successfully.
if [ -f "requirements.txt" ]; then
    log_info "Checking Python dependencies..."
    if python3 -c "import celery, redis, psycopg2" 2>/dev/null; then
        log_ok "Python dependencies already satisfied"
    else
        log_warn "Missing dependencies — attempting install..."
        if pip install -q -r requirements.txt 2>/dev/null; then
            log_ok "Python dependencies installed"
        else
            log_warn "pip install had issues (some packages may need Rust/build tools)"
            log_warn "Trying again without pydantic constraints..."
            pip install -q celery redis psycopg2-binary requests httpx jinja2 pyyaml 2>/dev/null || true
            if python3 -c "import celery, redis, psycopg2" 2>/dev/null; then
                log_ok "Core Python dependencies ready"
            else
                die "Critical Python dependencies missing. Check logs/celery.log"
            fi
        fi
    fi
else
    log_warn "requirements.txt not found"
fi

# Verify Celery can import tasks (catches import errors early)
log_info "Verifying Celery task imports..."
if ! python3 -c "from celery_app import app; print('Tasks:', len(app.tasks))" 2>/dev/null; then
    log_warn "Celery import check had issues (may still work at runtime)"
fi

# Start Celery with PYTHONPATH so forked workers can find local modules
export PYTHONPATH="$PWD:$PYTHONPATH"
export SSL_CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null || echo '')"
# Remove stale env vars that might override Redis-stored settings
# The LLMClient prefers env vars over Redis, so unset to force Redis lookup
unset OPENAI_API_KEY 2>/dev/null || true
unset LLM_API_KEY 2>/dev/null || true
celery -A celery_app worker --loglevel=info --concurrency=4 -Q celery,recon,scan,analyze,report,repo_scan > ../logs/celery.log 2>&1 &
CELERY_PID=$!
cd ..

sleep 3
if ! kill -0 $CELERY_PID 2>/dev/null; then
    die "Celery failed to start. Check logs/celery.log"
fi

log_ok "Celery workers started (PID: $CELERY_PID)"
log_info "Logs: logs/celery.log"

# ── Start Celery Beat (for scheduled engagements) ──
export PYTHONPATH="$PWD/argus-workers:$PYTHONPATH"
celery -A celery_app beat --loglevel=info --pidfile=/tmp/celerybeat.pid > logs/celery_beat.log 2>&1 &
BEAT_PID=$!
echo "$BEAT_PID" > logs/celery_beat.pid

sleep 2
if kill -0 $BEAT_PID 2>/dev/null; then
    log_ok "Celery Beat started (PID: $BEAT_PID)"
    log_info "Logs: logs/celery_beat.log"
else
    log_warn "Celery Beat failed to start. Check logs/celery_beat.log"
fi

# Quick Celery health check — see if it connected to Redis
sleep 2
if grep -q "Connected to redis" logs/celery.log 2>/dev/null; then
    log_ok "Celery connected to Redis"
else
    log_warn "Celery Redis connection not confirmed yet (check logs/celery.log)"
fi

# ── Step 5.5: Verify Celery can execute tasks (orchestrator health check) ──

echo ""
echo -e "${YELLOW}━━━ Verifying Worker Task Execution ━━━${NC}"

# Dispatch a ping task and wait for result
log_info "Dispatching health-check ping task..."
PING_RESULT=$(cd argus-workers && PYTHONPATH="$PWD:$PYTHONPATH" python3 -c "
from celery_app import app
import time, json, sys

result = app.send_task('tasks.health.ping', countdown=1)
task_id = result.id

# Wait up to 15 seconds for result
for i in range(15):
    time.sleep(1)
    res = app.AsyncResult(task_id)
    if res.ready():
        if res.successful():
            data = res.get()
            print(json.dumps(data))
            sys.exit(0)
        else:
            print('FAILED: ' + str(res.result))
            sys.exit(1)

print('TIMEOUT')
sys.exit(1)
" 2>&1)

PING_EXIT=$?

if [ $PING_EXIT -eq 0 ] && echo "$PING_RESULT" | grep -q '"status": "ok"' 2>/dev/null; then
    WORKER_HOST=$(echo "$PING_RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('worker','unknown'))" 2>/dev/null || echo "unknown")
    log_ok "Celery worker executed ping task successfully (worker: $WORKER_HOST)"
else
    log_warn "Celery task execution check failed or timed out"
    log_info "The worker may still be initializing. Check logs/celery.log"
fi

# ── Step 6: Save state ──

echo "$NEXTJS_PID" > logs/nextjs.pid
echo "$CELERY_PID" > logs/celery.pid
echo "$BEAT_PID" > logs/celery_beat.pid

# ── Done ──

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

#!/bin/bash

# Argus CLI Startup Script
# Starts Redis, Celery workers, and launches the Argus CLI
#
# Usage: ./start-argus.sh
#        ./start-argus.sh --no-tui      # Plain CLI mode
#        ./start-argus.sh --target x.com # Scan immediately

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[FAIL]${NC} $1"; }

die() {
    log_error "$1"
    echo -e "${YELLOW}Run ./stop-argus.sh to clean up.${NC}"
    exit 1
}

CLI_ARGS=""
if [ "$1" = "--no-tui" ]; then
    CLI_ARGS="--no-tui"
elif [ "$1" = "--target" ] && [ -n "$2" ]; then
    CLI_ARGS="--target $2"
fi

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Argus Security AI Agent            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}━━━ Checking Prerequisites ━━━${NC}"

if ! command -v python3 >/dev/null 2>&1; then
    die "Python 3 is not installed"
fi
log_ok "$(python3 --version)"

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

mkdir -p logs || die "Cannot create logs directory"
log_ok "Log directory ready"

echo ""
echo -e "${YELLOW}━━━ Starting Celery Workers ━━━${NC}"

cd argus-workers || die "argus-workers directory not found"

if [ ! -d "venv" ]; then
    log_warn "Virtual environment not found. Creating one..."
    python3 -m venv venv || die "Failed to create Python venv"
fi

source venv/bin/activate || die "Failed to activate Python venv"

if [ -f "requirements.txt" ]; then
    log_info "Checking Python dependencies..."
    if python3 -c "import celery, redis, psycopg2" 2>/dev/null; then
        log_ok "Python dependencies already satisfied"
    else
        log_warn "Missing dependencies — installing..."
        pip install -q -r requirements.txt 2>/dev/null || pip install -q celery redis psycopg2-binary requests httpx jinja2 pyyaml 2>/dev/null || true
    fi
fi

export PYTHONPATH="$PWD:$PYTHONPATH"
if [ -f ".env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            \#*|'') continue ;;
        esac
        export "$line"
    done < ".env"
fi

celery -A celery_app worker \
  --loglevel=info \
  --concurrency=4 \
  --prefetch-multiplier=1 \
  -Q celery,recon,scan,analyze,report,repo_scan > "$SCRIPT_DIR/logs/celery.log" 2>&1 &
CELERY_PID=$!
cd "$SCRIPT_DIR"

sleep 3
if ! kill -0 $CELERY_PID 2>/dev/null; then
    die "Celery failed to start. Check logs/celery.log"
fi
echo "$CELERY_PID" > logs/celery.pid
log_ok "Celery workers started (PID: $CELERY_PID)"

echo ""
echo -e "${YELLOW}━━━ Launching Argus CLI ━━━${NC}"

ARGUS_CLI_DIR="$SCRIPT_DIR/argus-cli"

if ! python3 -c "import argus_cli" 2>/dev/null; then
    log_warn "argus-cli not installed — installing..."
    pip install -e "$ARGUS_CLI_DIR" 2>/dev/null || die "Failed to install argus-cli"
fi

echo ""

python3 -m argus_cli $CLI_ARGS

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Argus CLI session ended            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
log_info "Run ./stop-argus.sh to stop background services."

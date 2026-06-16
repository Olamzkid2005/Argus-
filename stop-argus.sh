#!/bin/bash

# ════════════════════════════════════════════════════════════════
#  Argus — Cleanup Script
# ════════════════════════════════════════════════════════════════
#
# Stops running Argus TUI and CLI processes, and cleans up stale
# processes from the v4 Python era.
#
# Usage:
#   ./stop-argus.sh                    # Stop all Argus processes
#   ./stop-argus.sh tui                # Stop only the TUI
#   ./stop-argus.sh cli                # Stop only the CLI
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
PID_DIR="$SCRIPT_DIR/.pid"

# ── Help ────────────────────────────────────────────────────────

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "Usage: ./stop-argus.sh [target]"
  echo ""
  echo "Targets:"
  echo "  (no target)    Stop all Argus processes (TUI, CLI, stale v4)"
  echo "  tui            Stop only the Argus TUI"
  echo "  cli            Stop only the Argus CLI"
  echo "  --help         Show this help"
  exit 0
fi

# ── Helpers ─────────────────────────────────────────────────────

stop_by_pidfile() {
  local name="$1"
  local label="$2"
  local pid_file="$PID_DIR/${name}.pid"
  local found=false

  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo -e "${YELLOW}Stopping $label (PID: $pid)...${NC}"
      kill "$pid" 2>/dev/null || true
      # Give it a moment, then force
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        echo -e "${RED}✓ $label force-stopped${NC}"
      else
        echo -e "${GREEN}✓ $label stopped${NC}"
      fi
      found=true
    fi
    rm -f "$pid_file"
  fi

  # Also search by process pattern — match the specific Argus entry points
  local pattern
  if [ "$name" = "tui" ]; then
    pattern="bun.*src/argus/index\\.ts"
  elif [ "$name" = "cli" ]; then
    pattern="bun.*packages/cli/src/index\\.ts"
  else
    pattern="bun.*${name}"
  fi
  local pids
  pids=$(pgrep -f "$pattern" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo -e "${YELLOW}Stopping stray $label process(es): $pids...${NC}"
    kill $pids 2>/dev/null || true
    sleep 1
    kill -9 $(pgrep -f "$pattern" 2>/dev/null) 2>/dev/null || true
    echo -e "${GREEN}✓ Stray $label process(es) stopped${NC}"
    found=true
  fi

  if [ "$found" = false ]; then
    echo -e "${BLUE}No running $label found.${NC}"
  fi
}

# ── Determine what to stop ──

STOP_ALL=true
STOP_TUI=false
STOP_CLI=false

case "${1:-}" in
  repl|tui)
    STOP_ALL=false
    STOP_TUI=true
    ;;
  cli)
    STOP_ALL=false
    STOP_CLI=true
    ;;
  *)
    STOP_ALL=true
    ;;
esac

# ── Stop processes ──

if [ "$STOP_ALL" = true ] || [ "$STOP_TUI" = true ]; then
  stop_by_pidfile "tui" "Argus TUI"
fi

if [ "$STOP_ALL" = true ] || [ "$STOP_CLI" = true ]; then
  stop_by_pidfile "cli" "Argus CLI"
fi

# ── Clean up any stale v4 Python processes ──

if [ "$STOP_ALL" = true ]; then
  if pgrep -f "celery.*worker" >/dev/null 2>&1; then
    echo -e "${YELLOW}Stopping stale Celery workers (v4)...${NC}"
    pkill -f "celery.*worker" 2>/dev/null || true
    echo -e "${GREEN}✓ Done${NC}"
  fi

  # Clean up any leftover PID files from v4 era
  rm -f "$SCRIPT_DIR/logs/celery.pid" "$SCRIPT_DIR/logs/celery_beat.pid" 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}✓ Cleanup complete.${NC}"
echo ""
echo "To start Argus components:"
echo "  ./start-argus.sh tui              # Interactive TUI"
echo "  ./start-argus.sh assess <target>  # Run assessment"
echo "  ./start-argus.sh cli <handler>    # CLI handler"
echo "  ./start-argus.sh doctor           # Health check"
echo ""

# Clean up pid dir if empty
rmdir "$PID_DIR" 2>/dev/null || true

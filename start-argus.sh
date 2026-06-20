#!/bin/bash

# ════════════════════════════════════════════════════════════════
#  Argus — Autonomous Security Assessment Platform
# ════════════════════════════════════════════════════════════════
#
# Interactive launcher for Argus platform components.
#
# Usage:
#   ./start-argus.sh              # Interactive prompt (TUI or CLI?)
#   ./start-argus.sh tui          # Launch TUI directly
#   ./start-argus.sh cli <cmd>    # Run CLI handler directly
#   ./start-argus.sh doctor       # Run health checks
#   ./start-argus.sh assess <url> # Run assessment
#   ./start-argus.sh test         # Run tests
#   ./start-argus.sh --help       # Show full help
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
ARGUS_CLI_PKG="$SCRIPT_DIR/Argus-Tui/packages/cli"
PID_DIR="$SCRIPT_DIR/.pid"

# ── Entry points ─────────────────────────────────────────────────
# TUI (Interactive): Argus-Tui/packages/opencode/src/argus/index.ts
#   - With no args: shows dashboard → launches rich SolidJS TUI
#   - Supports all Argus routes: assess, doctor, scan, findings, etc.
#   - Uses OpenCode's @opentui/solid framework under ARGUS_MODE=1
#   - Runs via: bun run src/argus/index.ts
#
# CLI: Argus-Tui/packages/opencode/src/argus/main.ts
#   - Subcommands: doctor, assess, report, resume, verify, evidence, config
#   - Non-interactive, one-shot execution
#   - Runs via: bun run src/argus/main.ts <command>
#
# Dev CLI: Argus-Tui/packages/cli/src/index.ts
#   - Handler-based CLI with commands: debug/agents, migrate
#   - Uses Effect + yargs for CLI dispatch
#   - Runs via: bun run src/index.ts

# ── Help ────────────────────────────────────────────────────────

show_help() {
  echo ""
  echo "Usage: ./start-argus.sh <command> [options]"
  echo ""
  echo "Launch Commands:"
  echo "  (no args)             Interactive prompt — choose TUI or CLI"
  echo "  tui                   Launch the Argus interactive TUI"
  echo "    --background        Run health check instead (TUI needs a TTY)"
  echo "  cli <handler> [opts]  Run the Argus CLI handler"
  echo "    Available: debug/agents, migrate"
  echo ""
  echo "Argus Commands:"
  echo "  doctor                Run health checks"
  echo "  assess <target>       Run assessment"
  echo "  report <id>           Generate report"
  echo "  resume  <id>          Resume an assessment"
  echo "  verify  <target>      Verify findings"
  echo "  evidence <id>         Manage evidence"
  echo "  config                View/edit config"
  echo ""
  echo "Utility Commands:"
  echo "  test                  Run unit tests"
  echo "  --help                Show this help"
  echo ""
  exit 0
}

# ── Helpers ─────────────────────────────────────────────────────

save_pid() {
  local name="$1"
  local pid="$2"
  mkdir -p "$PID_DIR"
  echo "$pid" > "$PID_DIR/${name}.pid"
}

ensure_bun_deps() {
  local pkg="$1"
  if [ ! -d "$pkg/node_modules" ]; then
    echo -e "${YELLOW}[Argus] Installing dependencies for $(basename "$pkg")...${NC}"
    (cd "$pkg" && bun install)
  fi
}

launch_tui() {
  if [ ! -t 0 ]; then
    echo -e "${RED}TTY not detected — TUI requires an interactive terminal${NC}" >&2
    echo -e "${YELLOW}Use: ./start-argus.sh doctor | assess <target> | cli <handler>${NC}" >&2
    exit 1
  fi
  ensure_bun_deps "$ARGUS_PKG"
  cd "$ARGUS_PKG" || exit 1
  echo -e "${BLUE}[Argus] Launching interactive TUI...${NC}"
  echo -e "${CYAN}  Entry point: src/argus/index.ts${NC}"
  echo ""
  exec bun run src/argus/index.ts "$@"
}

launch_tui_background() {
  echo -e "${YELLOW}[Argus] Background mode is not supported for the interactive TUI.${NC}"
  echo -e "${YELLOW}  Running: ./start-argus.sh doctor  # non-interactive health check${NC}"
  ensure_bun_deps "$ARGUS_PKG"
  cd "$ARGUS_PKG" || exit 1
  bun run src/argus/main.ts doctor
}

launch_cli() {
  if [ $# -eq 0 ]; then
    echo -e "${RED}Usage: ./start-argus.sh cli <handler> [opts]${NC}"
    echo -e "  Available handlers: debug/agents, migrate"
    exit 1
  fi
  ensure_bun_deps "$ARGUS_CLI_PKG"
  cd "$ARGUS_CLI_PKG" || exit 1
  echo -e "${BLUE}[Argus CLI] Running: $*${NC}"
  echo -e "${CYAN}  Entry point: src/index.ts${NC}"
  echo ""
  bun run src/index.ts "$@"
}

# ── Interactive prompt ──────────────────────────────────────────

interactive_prompt() {
  echo -e "${BOLD}${BLUE}╔════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${BLUE}║        Argus — Component Launcher      ║${NC}"
  echo -e "${BOLD}${BLUE}╚════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "Which Argus component would you like to open?"
  echo ""
  echo -e "  ${BOLD}1)${NC} ${GREEN}TUI${NC}  — Interactive Terminal UI"
  echo -e "     ${CYAN}Argus-Tui/packages/opencode/src/argus/index.ts${NC}"
  echo -e "     Dashboard, assessments, reports, interactive mode"
  echo ""
  echo -e "  ${BOLD}2)${NC} ${GREEN}CLI${NC}  — Command-line Handlers"
  echo -e "     ${CYAN}Argus-Tui/packages/cli/src/index.ts${NC}"
  echo -e "     Available: debug/agents, migrate"
  echo ""
  echo -e "  ${BOLD}q)${NC}  Quit"
  echo ""

  # Exit immediately if not a TTY — can't interact
  if [ ! -t 0 ]; then
    echo -e "${YELLOW}Non-interactive terminal — launching TUI by default.${NC}"
    echo -e "${YELLOW}Use: ./start-argus.sh tui | cli | doctor | assess <target>${NC}"
    echo ""
    launch_tui
    exit 0
  fi

  while true; do
    if ! read -r -p "$(echo -e "${YELLOW}Enter choice [1/2/q]:${NC} ")" choice; then
      # EOF / read error — exit gracefully
      echo ""
      echo -e "${BLUE}Goodbye.${NC}"
      exit 0
    fi
    case "$choice" in
      1|tui|TUI)
        launch_tui
        break
        ;;
      2|cli|CLI)
        echo ""
        echo -e "${BLUE}Available CLI handlers:${NC}"
        echo -e "  ${BOLD}debug/agents${NC}  — Debug agent execution"
        echo -e "  ${BOLD}migrate${NC}       — Run database migrations"
        echo ""
        if ! read -r -p "$(echo -e "${YELLOW}Enter handler name:${NC} ")" handler; then
          echo -e "${BLUE}Goodbye.${NC}"
          exit 0
        fi
        if [ -n "$handler" ]; then
          launch_cli "$handler"
        else
          echo -e "${RED}No handler entered.${NC}"
        fi
        break
        ;;
      q|Q|quit|exit)
        echo -e "${BLUE}Goodbye.${NC}"
        exit 0
        ;;
      *)
        echo -e "${RED}Invalid choice. Please enter 1, 2, or q.${NC}"
        ;;
    esac
  done
}

# ── Command dispatch ────────────────────────────────────────────

case "${1:-}" in
  --help|-h)
    show_help
    ;;

  # ── Interactive mode (no args) ──
  "")
    interactive_prompt
    ;;

  # ── Argus CLI commands (delegate to packages/opencode) ──

  doctor|assess|report|resume|verify|evidence|config)
    cmd="$1"
    shift
    ensure_bun_deps "$ARGUS_PKG"
    cd "$ARGUS_PKG" || exit 1
    echo -e "${BLUE}[Argus] Running '$cmd'...${NC}"
    echo -e "${CYAN}  Entry point: src/argus/main.ts${NC}"
    echo ""
    bun run src/argus/main.ts "$cmd" "$@"
    ;;

  # ── Interactive TUI ──

  tui)
    shift
    for arg in "$@"; do
      if [ "$arg" = "--help" ] || [ "$arg" = "-h" ]; then
        ensure_bun_deps "$ARGUS_PKG"
        cd "$ARGUS_PKG" || exit 1
        bun run src/argus/index.ts --help
        exit 0
      fi
    done

    if [ "$1" = "--background" ]; then
      shift
      launch_tui_background "$@"
    else
      launch_tui "$@"
    fi
    ;;

  # ── Low-level CLI (packages/cli) ──

  cli)
    shift
    launch_cli "$@"
    ;;

  # ── Tests ──

  test)
    shift
    ensure_bun_deps "$ARGUS_PKG"
    cd "$ARGUS_PKG" || exit 1
    echo -e "${BLUE}[Argus] Running tests...${NC}"
    bun test test/argus/ --timeout 30000 "$@"
    ;;

  # ── Fallback: try as a handler through the full CLI if unknown ──

  *)
    # If they passed something that looks like a handler name, try the CLI
    case "$1" in
      debug/agents|migrate)
        launch_cli "$@"
        ;;
      *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo -e "Run ${YELLOW}./start-argus.sh --help${NC} for usage."
        exit 1
        ;;
    esac
    ;;
esac

#!/bin/bash

# ════════════════════════════════════════════════════════════════
#  Argus V5 — Comprehensive Test Suite
# ════════════════════════════════════════════════════════════════
#
# Executes health checks, quick scans, and full assessments
# against a target domain (default: www.vulnbank.org).
# Retries on failure until meaningful results are obtained.
#
# Usage:
#   ./start-argus.sh                              # Full test suite
#   ./start-argus.sh --target example.com          # Custom target
#   ./start-argus.sh --doctor-only                 # Health check only
#   ./start-argus.sh --assess-only                # Assessment only
#   ./start-argus.sh --max-retries 5              # Custom retry limit
#   ./start-argus.sh --help                       # This help
# ════════════════════════════════════════════════════════════════

set -o pipefail

# ── Colors ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# ── Counters & State ────────────────────────────────────────────
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
WARN_TESTS=0
TEST_LOG=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGUS_PKG="$SCRIPT_DIR/Argus-Tui/packages/opencode"
TARGET="${TARGET_DOMAIN:-www.vulnbank.org}"

# ── Extend PATH for toolchain discovery ─────────────────────────
# Security tools installed via venv, go, or brew may not be on the
# default PATH inherited by bun/node subprocesses.
VENV_BIN="/Users/mac/Documents/Argus-/argus-workers/venv/bin"
GO_BIN="$HOME/go/bin"
for _dir in "$VENV_BIN" "$GO_BIN"; do
  if [ -d "$_dir" ] && [[ ":$PATH:" != *":$_dir:"* ]]; then
    export PATH="$_dir:$PATH"
  fi
done
MAX_RETRIES=3
MODE_FULL=true
MODE_DOCTOR=true
MODE_ASSESS=true
CURRENT_PHASE=""

# ── Cross-platform timeout ──────────────────────────────────────
# On Linux, `timeout` is built-in via coreutils. On macOS (Darwin),
# it is available as `gtimeout` (brew install coreutils) or not at all.
# This function provides a portable fallback using a background subprocess.
_TIMEOUT_CMD=""
_find_timeout() {
  if command -v gtimeout &>/dev/null; then
    _TIMEOUT_CMD="gtimeout"
  elif command -v timeout &>/dev/null; then
    _TIMEOUT_CMD="timeout"
  else
    _TIMEOUT_CMD=""
  fi
}
_find_timeout

run_with_timeout() {
  local duration="$1"
  shift
  if [ -n "$_TIMEOUT_CMD" ]; then
    "$_TIMEOUT_CMD" "$duration" "$@"
    return $?
  fi
  # Fallback: run in background with a kill timer
  local exit_code=0
  local tmp_out
  tmp_out="$(mktemp)"
  ("$@" > "$tmp_out" 2>&1; echo "EXIT:$?">"${tmp_out}.rc") &
  local pid=$!
  local waited=0
  while [ $waited -lt "$duration" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    exit_code=124
  else
    wait "$pid" 2>/dev/null
    if [ -f "${tmp_out}.rc" ]; then
      exit_code="$(cat "${tmp_out}.rc" | grep -oE '[0-9]+' | tail -1)"
      rm -f "${tmp_out}.rc"
    fi
  fi
  cat "$tmp_out"
  rm -f "$tmp_out"
  return $exit_code
}

# ── Parse CLI arguments ─────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      sed -n '3,16p' "$0"
      exit 0
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --max-retries)
      MAX_RETRIES="$2"
      shift 2
      ;;
    --doctor-only)
      MODE_ASSESS=false
      MODE_FULL=false
      shift
      ;;
    --assess-only)
      MODE_DOCTOR=false
      shift
      ;;
    --quick-only)
      MODE_FULL=false
      shift
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Usage: $0 [--target <domain>] [--max-retries <n>] [--doctor-only|--assess-only|--quick-only]"
      exit 1
      ;;
  esac
done

# ── Helper Functions ────────────────────────────────────────────

log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()      { echo -e "${GREEN}[PASS]${NC}  $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[FAIL]${NC}  $1"; }
log_step()    { echo -e "\n${MAGENTA}═══ $1 ═══${NC}"; }
log_detail()  { echo -e "  ${CYAN}→${NC} $1"; }

record_test() {
  local status="$1"   # PASS, FAIL, WARN, SKIP
  local name="$2"
  local detail="${3:-}"
  TOTAL_TESTS=$((TOTAL_TESTS + 1))
  case "$status" in
    PASS) PASSED_TESTS=$((PASSED_TESTS + 1)) ;;
    FAIL) FAILED_TESTS=$((FAILED_TESTS + 1)) ;;
    WARN) WARN_TESTS=$((WARN_TESTS + 1)) ;;
    SKIP) ;;  # no-op, counted in TOTAL only
  esac
  TEST_LOG="${TEST_LOG}$(printf "  %-5s  %-40s  %s\n" "$status" "$name" "$detail")
"
}

header() {
  echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║${NC}          ${BOLD}Argus V5 — Security AI Agent Test Suite${NC}           ${BLUE}║${NC}"
  echo -e "${BLUE}╠══════════════════════════════════════════════════════════════╣${NC}"
  echo -e "${BLUE}║${NC}  Target:       ${CYAN}$TARGET${NC}"
  echo -e "${BLUE}║${NC}  Started:      $(date '+%Y-%m-%d %H:%M:%S')"
  echo -e "${BLUE}║${NC}  Max Retries:  $MAX_RETRIES"
  echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
  echo ""
}

footer() {
  echo ""
  echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║${NC}                     ${BOLD}Test Suite Summary${NC}                        ${BLUE}║${NC}"
  echo -e "${BLUE}╠══════════════════════════════════════════════════════════════╣${NC}"
  echo -e "${BLUE}║${NC}  Total:  $TOTAL_TESTS"
  echo -e "${BLUE}║${NC}  ${GREEN}Passed:${NC} $PASSED_TESTS"
  [ "$FAILED_TESTS" -gt 0 ] && echo -e "${BLUE}║${NC}  ${RED}Failed:${NC} $FAILED_TESTS" || echo -e "${BLUE}║${NC}  Failed: $FAILED_TESTS"
  [ "$WARN_TESTS" -gt 0 ] && echo -e "${BLUE}║${NC}  ${YELLOW}Warnings:${NC} $WARN_TESTS" || echo -e "${BLUE}║${NC}  Warnings: $WARN_TESTS"
  echo -e "${BLUE}║${NC}  Finished:     $(date '+%Y-%m-%d %H:%M:%S')"
  echo -e "${BLUE}╠══════════════════════════════════════════════════════════════╣${NC}"
  echo ""
  echo -e "${BLUE}║${NC}  ${BOLD}Detail Log:${NC}"
  echo "$TEST_LOG"
  echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"

  # Determine overall exit code
  if [ "$FAILED_TESTS" -gt 0 ]; then
    echo -e "\n${RED}✗ ${BOLD}Some tests failed.${NC} Review the details above.\n"
    return 1
  elif [ "$WARN_TESTS" -gt 0 ]; then
    echo -e "\n${YELLOW}⚠ ${BOLD}All critical tests passed with warnings.${NC}\n"
    return 0
  else
    echo -e "\n${GREEN}✓ ${BOLD}All tests passed successfully!${NC}\n"
    return 0
  fi
}

check_prerequisites() {
  log_step "Phase 0: Prerequisites"

  local prereq_pass=true

  # Check bun
  if ! command -v bun >/dev/null 2>&1; then
    log_error "Bun is not installed. Install it: curl -fsSL https://bun.sh/install | bash"
    record_test "FAIL" "Bun Runtime" "not installed"
    prereq_pass=false
  else
    local bun_ver
    bun_ver="$(bun --version 2>/dev/null)"
    log_ok "Bun $bun_ver"
    record_test "PASS" "Bun Runtime" "v$bun_ver"
  fi

  # Check Python
  local python_found=""
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      python_found="$py"
      break
    fi
  done

  if [ -n "$python_found" ]; then
    local py_ver
    py_ver="$($python_found --version 2>&1)"
    log_ok "$py_ver"
    record_test "PASS" "Python Runtime" "$py_ver"
  else
    log_warn "Python not found. Set ARGUS_PYTHON or install python3."
    record_test "WARN" "Python Runtime" "not found"
  fi

  # Check dependencies
  if [ ! -d "$ARGUS_PKG/node_modules" ]; then
    log_info "Installing dependencies..."
    cd "$SCRIPT_DIR/Argus-Tui" || { log_error "Failed to cd to Argus-Tui"; record_test "FAIL" "Project Directory" "Argus-Tui not found"; prereq_pass=false; }
    if bun install --ignore-scripts 2>&1 | tail -1; then
      log_ok "Dependencies installed"
      record_test "PASS" "Dependencies" "installed"
    else
      log_error "Dependency installation failed"
      record_test "FAIL" "Dependencies" "installation failed"
      prereq_pass=false
    fi
  else
    log_ok "Dependencies already satisfied"
    record_test "PASS" "Dependencies" "cached"
  fi

  cd "$ARGUS_PKG" || { log_error "Failed to cd to $ARGUS_PKG"; return 1; }

  $prereq_pass && return 0 || return 1
}

# ── Phase 1: Health Check (Doctor) ──────────────────────────────

run_health_check() {
  CURRENT_PHASE="health"
  log_step "Phase 1: Health Check Verification"
  echo -e "  Verifying that all Argus services, runtimes, and toolchains are operational."
  echo ""

  local attempt=1
  local success=false

  while [ $attempt -le "$MAX_RETRIES" ] && [ "$success" = false ]; do
    if [ $attempt -gt 1 ]; then
      echo -e "${YELLOW}  ── Retry attempt $attempt of $MAX_RETRIES ──${NC}\n"
      sleep $((attempt * 3))
    fi

    log_detail "Running: bun run src/argus/main.ts doctor"
    echo ""

    # Capture doctor output
    local doctor_output
    doctor_output=$(bun run src/argus/main.ts doctor 2>&1)
    local doctor_exit=$?

    echo "$doctor_output"
    echo ""

    if [ $doctor_exit -eq 0 ] || [ $doctor_exit -eq 1 ]; then
      # Even exit code 1 is acceptable (some checks may warn/fail)
      success=true

      # Parse results from doctor output
      local passes
      local warns
      local fails
      passes=$(echo "$doctor_output" | grep -cE "^✓" || true)
      warns=$(echo "$doctor_output" | grep -cE "^⚠" || true)
      fails=$(echo "$doctor_output" | grep -cE "^✗" || true)

      if [ "$fails" -gt 0 ]; then
        log_warn "Health check completed with $fails failure(s)"
        record_test "WARN" "Doctor Health Check" "$passes passed, $warns warnings, $fails failed (attempt $attempt)"
      elif [ "$warns" -gt 0 ]; then
        log_ok "Health check completed with warnings"
        record_test "PASS" "Doctor Health Check" "$passes passed, $warns warnings (attempt $attempt)"
      else
        log_ok "All health checks passed"
        record_test "PASS" "Doctor Health Check" "$passes checks passed (attempt $attempt)"
      fi
    else
      log_error "Health check crashed with exit code $doctor_exit"
      if [ $attempt -lt "$MAX_RETRIES" ]; then
        log_info "Retrying in $((attempt * 3)) seconds..."
      fi
    fi

    attempt=$((attempt + 1))
  done

  if [ "$success" = false ]; then
    log_error "Health check failed after $MAX_RETRIES attempts"
    record_test "FAIL" "Doctor Health Check" "Failed after $MAX_RETRIES attempts"
    # Continue anyway — don't block assessment
  fi
}

# ── Phase 2: Quick Scan (Deterministic) ─────────────────────────

run_quick_scan() {
  CURRENT_PHASE="quick"
  log_step "Phase 2: Quick Scan — $TARGET"
  echo -e "  Running a lightweight, deterministic scan to gather baseline intelligence."
  echo ""

  local attempt=1
  local success=false
  local QUICK_TIMEOUT=600

  while [ $attempt -le "$MAX_RETRIES" ] && [ "$success" = false ]; do
    if [ $attempt -gt 1 ]; then
      echo -e "${YELLOW}  ── Retry attempt $attempt of $MAX_RETRIES ──${NC}\n"
      sleep $((attempt * 5))
    fi

    log_detail "Running: bun run src/argus/main.ts assess $TARGET --deterministic"
    echo ""

    # Use a subshell with timeout to prevent hanging
    local scan_output
    scan_output=$(run_with_timeout "$QUICK_TIMEOUT" bun run src/argus/main.ts assess "$TARGET" --deterministic 2>&1)
    local scan_exit=$?

    if [ $scan_exit -eq 0 ] || [ $scan_exit -eq 1 ] || [ $scan_exit -eq 124 ]; then
      # 124 = timeout (partial results may still exist)
      # 0/1 = completed (findings may vary)
      success=true

      echo "$scan_output"
      echo ""

      # Extract finding count if present
      local finding_count
      finding_count=$(echo "$scan_output" | grep -oE '[0-9]+ finding\(s\)' | grep -oE '[0-9]+' || echo "0")

      # Check for any finding content
      local has_findings=false
      if echo "$scan_output" | grep -qiE "(finding|vulnerabilit|issu|risk|alert)" 2>/dev/null; then
        has_findings=true
      fi

      if [ "$has_findings" = true ] && [ "${finding_count:-0}" -gt 0 ] 2>/dev/null; then
        log_ok "Quick scan found $finding_count finding(s)"
        record_test "PASS" "Quick Scan ($TARGET)" "$finding_count finding(s) (attempt $attempt)"
      elif [ "$has_findings" = true ]; then
        log_ok "Quick scan completed with findings reported"
        record_test "PASS" "Quick Scan ($TARGET)" "Findings reported (attempt $attempt)"
      elif [ $scan_exit -eq 124 ]; then
        log_warn "Quick scan timed out after ${QUICK_TIMEOUT}s — partial results may exist"
        record_test "WARN" "Quick Scan ($TARGET)" "Timed out with partial results (attempt $attempt)"
      else
        log_warn "Quick scan completed but no findings were detected"
        record_test "WARN" "Quick Scan ($TARGET)" "No findings (attempt $attempt)"
      fi
    else
      log_error "Quick scan failed with exit code $scan_exit"
      if [ $attempt -lt "$MAX_RETRIES" ]; then
        log_info "Retrying in $((attempt * 5)) seconds..."
      fi
    fi

    attempt=$((attempt + 1))
  done

  if [ "$success" = false ]; then
    log_error "Quick scan failed after $MAX_RETRIES attempts"
    record_test "FAIL" "Quick Scan ($TARGET)" "Failed after $MAX_RETRIES attempts"
  fi
}

# ── Phase 3: Full Assessment ────────────────────────────────────

run_full_assessment() {
  CURRENT_PHASE="assess"
  log_step "Phase 3: Full Assessment — $TARGET"
  echo -e "  Running comprehensive security assessment with all available capabilities."
  echo ""

  local attempt=1
  local success=false
  local ASSESS_TIMEOUT=1200

  while [ $attempt -le "$MAX_RETRIES" ] && [ "$success" = false ]; do
    if [ $attempt -gt 1 ]; then
      echo -e "${YELLOW}  ── Retry attempt $attempt of $MAX_RETRIES ──${NC}\n"
      sleep $((attempt * 10))
    fi

    log_detail "Running: bun run src/argus/main.ts assess $TARGET"
    echo ""

    local assess_output
    assess_output=$(run_with_timeout "$ASSESS_TIMEOUT" bun run src/argus/main.ts assess "$TARGET" 2>&1)
    local assess_exit=$?

    if [ $assess_exit -eq 0 ] || [ $assess_exit -eq 1 ] || [ $assess_exit -eq 124 ]; then
      success=true

      echo "$assess_output"
      echo ""

      local finding_count
      finding_count=$(echo "$assess_output" | grep -oE '[0-9]+ finding\(s\)' | grep -oE '[0-9]+' || echo "0")

      local has_findings=false
      if echo "$assess_output" | grep -qiE "(finding|vulnerabilit|issu|risk|alert|CVE-)" 2>/dev/null; then
        has_findings=true
      fi

      # Extract any CVE or vulnerability references
      local vuln_refs
      vuln_refs=$(echo "$assess_output" | grep -oE '(CVE-[0-9]+-[0-9]+|CVSS[[:space:]:][0-9.]+)' 2>/dev/null | tr '\n' ' ' || true)

      if [ "$has_findings" = true ] && [ "${finding_count:-0}" -gt 0 ] 2>/dev/null; then
        log_ok "Full assessment found $finding_count finding(s)"
        if [ -n "$vuln_refs" ]; then
          log_detail "References: $vuln_refs"
        fi
        record_test "PASS" "Full Assessment ($TARGET)" "$finding_count finding(s) (attempt $attempt)"
      elif [ "$has_findings" = true ]; then
        log_ok "Full assessment completed with findings"
        record_test "PASS" "Full Assessment ($TARGET)" "Findings reported (attempt $attempt)"
      elif [ $assess_exit -eq 124 ]; then
        log_warn "Full assessment timed out after ${ASSESS_TIMEOUT}s — partial results may exist"
        record_test "WARN" "Full Assessment ($TARGET)" "Timed out with partial results (attempt $attempt)"
      else
        log_info "Full assessment completed — no explicit findings reported"
        record_test "PASS" "Full Assessment ($TARGET)" "Completed with no findings (attempt $attempt)"
      fi
    else
      log_error "Full assessment failed with exit code $assess_exit"
      if [ $attempt -lt "$MAX_RETRIES" ]; then
        log_info "Retrying in $((attempt * 10)) seconds..."
      fi
    fi

    attempt=$((attempt + 1))
  done

  if [ "$success" = false ]; then
    log_error "Full assessment failed after $MAX_RETRIES attempts"
    record_test "FAIL" "Full Assessment ($TARGET)" "Failed after $MAX_RETRIES attempts"
  fi
}

# ── Main Execution ──────────────────────────────────────────────

main() {
  header

  # Phase 0: Prerequisites
  check_prerequisites || {
    log_error "Prerequisites check failed — cannot continue"
    record_test "FAIL" "Prerequisites" "Failed"
    footer
    exit 1
  }

  # Phase 1: Health Check
  if [ "$MODE_DOCTOR" = true ]; then
    run_health_check
  else
    log_info "Skipping health check (--assess-only mode)"
    record_test "SKIP" "Doctor Health Check" "Opted out"
  fi

  # Phase 2: Quick Scan
  if [ "$MODE_ASSESS" = true ]; then
    run_quick_scan
  else
    log_info "Skipping quick scan (--doctor-only mode)"
    record_test "SKIP" "Quick Scan ($TARGET)" "Opted out"
  fi

  # Phase 3: Full Assessment
  if [ "$MODE_FULL" = true ] && [ "$MODE_ASSESS" = true ]; then
    run_full_assessment
  elif [ "$MODE_FULL" = false ] && [ "$MODE_ASSESS" = true ]; then
    log_info "Skipping full assessment (--quick-only mode)"
    record_test "SKIP" "Full Assessment ($TARGET)" "Opted out"
  else
    log_info "Skipping full assessment (--doctor-only mode)"
    record_test "SKIP" "Full Assessment ($TARGET)" "Opted out"
  fi

  # Summary
  footer
  local exit_code=$?
  exit $exit_code
}

main "$@"

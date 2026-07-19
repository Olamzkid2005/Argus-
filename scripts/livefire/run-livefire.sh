#!/usr/bin/env bash
# ==============================================================================
# run-livefire.sh — Argus Live-Fire Validation Runner
#
# Orchestrates a full end-to-end validation run of Argus against a target
# (default: Juice Shop v17.1.1 on localhost:3001). Creates the engagement,
# dispatches recon → scan → analyze → report phases, monitors progression,
# captures logs, and runs post-mortem analysis.
#
# Usage:
#   chmod +x run-livefire.sh
#   ./run-livefire.sh                              # Default: Juice Shop
#   TARGET_URL=http://127.0.0.1:3001 ./run-livefire.sh  # Custom target
#
# Requirements:
#   - docker compose (with postgres, redis, worker containers running)
#   - Python 3.10+ with argus-workers dependencies installed
#   - juice-shop target running (or custom TARGET_URL)
#   - DATABASE_URL and REDIS_URL environment variables set for dispatch_task.py
# ==============================================================================

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
ENGAGEMENT_ID="${ENGAGEMENT_ID:-a1b2c3d4-1111-4000-8000-000000000001}"
TARGET_URL="${TARGET_URL:-http://127.0.0.1:3001}"
TARGET_LABEL="${TARGET_LABEL:-juice-shop}"
RUN_ID="livefire-${TARGET_LABEL}-$(date +%Y%m%d-%H%M%S)"
LOG_DIR="./livefire-runs/${RUN_ID}"
DISPATCH_SCRIPT="${DISPATCH_SCRIPT:-../../argus-workers/dispatch_task.py}"
MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-1800}"  # 30 min max
POLL_INTERVAL="${POLL_INTERVAL:-10}"           # seconds between state checks

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── Helpers ────────────────────────────────────────────────────────────────
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[FAIL]${NC}  $*"; }
header()  { echo ""; echo "══════════════════════════════════════════════════"; echo "  $*"; echo "══════════════════════════════════════════════════"; }

db_query() {
  docker compose exec -T postgres psql -U argus_user -d argus_pentest -t -A -c "$1" 2>/dev/null || echo "ERROR"
}

# ── Pre-flight Checks ──────────────────────────────────────────────────────
preflight() {
  header "Pre-flight Checks"

  # 1. Verify target is reachable
  info "Checking target ${TARGET_URL}..."
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${TARGET_URL}" 2>/dev/null || echo "000")
  if [ "${HTTP_CODE}" = "000" ]; then
    fail "Target ${TARGET_URL} is unreachable. Is the target running?"
    info "Start it with: docker compose --profile e2e up -d juice-shop"
    return 1
  fi
  ok "Target reachable (HTTP ${HTTP_CODE})"

  # 2. Verify database is accessible
  info "Checking PostgreSQL..."
  DB_OK=$(db_query "SELECT 1;" 2>/dev/null || echo "")
  if [ -z "${DB_OK}" ]; then
    fail "PostgreSQL is not accessible. Is it running?"
    info "Start with: docker compose up -d postgres"
    return 1
  fi
  ok "PostgreSQL accessible"

  # 3. Verify dispatch_task.py exists
  if [ ! -f "${DISPATCH_SCRIPT}" ]; then
    fail "dispatch_task.py not found at ${DISPATCH_SCRIPT}"
    info "Set DISPATCH_SCRIPT env var to the correct path"
    return 1
  fi
  ok "dispatch_task.py found"

  # 4. Verify worker and juice-shop containers are running
  WORKER_RUNNING=$(docker compose ps --status running -q worker 2>/dev/null || echo "")
  JUICE_RUNNING=$(docker compose ps --status running -q juice-shop 2>/dev/null || echo "")
  if [ -z "${WORKER_RUNNING}" ] && [ "${TARGET_URL}" = "http://127.0.0.1:3001" ]; then
    warn "Worker container not running — logs won't be captured via docker compose"
  fi
  if [ -z "${JUICE_RUNNING}" ] && [ "${TARGET_URL}" = "http://127.0.0.1:3001" ]; then
    warn "juice-shop container not running — is it started with docker compose --profile e2e?"
  fi

  return 0
}

# ── Step 1: Reset Engagement ───────────────────────────────────────────────
reset_engagement() {
  header "Step 1/6: Reset Engagement State"

  info "Deleting existing findings for engagement ${ENGAGEMENT_ID}..."
  db_query "DELETE FROM findings WHERE engagement_id = '${ENGAGEMENT_ID}';" > /dev/null 2>&1 || true
  ok "Findings cleared"

  info "Resetting engagement state to 'created'..."
  db_query "UPDATE engagements SET status = 'created', started_at = NULL, completed_at = NULL WHERE id = '${ENGAGEMENT_ID}';" > /dev/null 2>&1 || true
  ok "Engagement reset to 'created'"

  info "Enabling FINDING_VERIFICATION feature flag..."
  db_query "INSERT INTO feature_flags (flag_name, enabled, description) VALUES ('FINDING_VERIFICATION', true, 'Live-fire validation run') ON CONFLICT (flag_name) DO UPDATE SET enabled = true;" > /dev/null 2>&1 || true
  ok "Feature flags set"

  # Verify reset
  STATE=$(db_query "SELECT status FROM engagements WHERE id = '${ENGAGEMENT_ID}';")
  if [ "${STATE}" != "created" ]; then
    fail "Engagement state is '${STATE}', expected 'created'"
    info "You may need to create the engagement first — see README.md"
    return 1
  fi
  ok "Engagement confirmed in 'created' state"
}

# ── Step 2: Start Log Capture ──────────────────────────────────────────────
start_log_capture() {
  header "Step 2/6: Start Log Capture"

  mkdir -p "${LOG_DIR}"
  info "Log directory: ${LOG_DIR}"

  # Try to capture docker compose logs (non-blocking)
  if docker compose ps --status running -q worker > /dev/null 2>&1; then
    docker compose logs -f worker > "${LOG_DIR}/worker.log" 2>&1 &
    LOGS_PID=$!
    info "Worker log capture started (PID: ${LOGS_PID})"
  else
    warn "Worker container not running — logs will not be captured automatically"
    LOGS_PID=""
  fi

  # Capture target logs if available
  if docker compose ps --status running -q juice-shop > /dev/null 2>&1; then
    docker compose logs juice-shop > "${LOG_DIR}/target.log" 2>&1 &
    TARGET_LOGS_PID=$!
    info "Target log capture started (PID: ${TARGET_LOGS_PID})"
  else
    TARGET_LOGS_PID=""
  fi

  # Snapshot initial resource usage
  docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" worker juice-shop 2>/dev/null > "${LOG_DIR}/resource-baseline.csv" || true
  info "Resource baseline captured"
}

# ── Step 3: Build and Dispatch Job Payload ─────────────────────────────────
dispatch_recon() {
  header "Step 3/6: Dispatch Recon Phase"

  # Build the job JSON with the correct engagement ID and target
  JOB_FILE="${LOG_DIR}/job-payload.json"

  cat > "${JOB_FILE}" << PAYLOAD
{
  "type": "recon",
  "engagement_id": "${ENGAGEMENT_ID}",
  "target": "${TARGET_URL}",
  "budget": {
    "max_tools": 30,
    "llm_budget_usd": 2.00,
    "scan_mode": "standard",
    "prev_engagement_id": null
  },
  "aggressiveness": "moderate",
  "agent_mode": true,
  "scan_mode": "standard",
  "bug_bounty_mode": false,
  "auth_config": {},
  "dual_auth_config": null,
  "trace_id": "livetrace-${RUN_ID##*-}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "scope": {
    "mode": "allowlist",
    "allowed_targets": ["127.0.0.1:3001", "localhost:3001"],
    "blocked_targets": ["*"]
  }
}
PAYLOAD

  info "Job payload written to ${JOB_FILE}"

  info "Setting ARGUS_AUTONOMOUS=1 for full scope enforcement..."
  # ARGUS_AUTONOMOUS=1 enables the fail-closed scope guard (item 1 from the audit).
  # Without it, scope_mode defaults to 'warn' and out-of-scope targets are logged
  # but not blocked. The scope block in the payload is now threaded through
  # JobMessage → Celery task → Orchestrator → execute_scan_tools(), so the
  # allowlist is properly enforced.
  # Note: export is needed here because the var must survive the pipe to Python.
  export ARGUS_AUTONOMOUS=1
  
  info "Dispatching recon task via Celery..."
  # Run dispatch_task.py, capturing result
  DISPATCH_OUTPUT=$(cat "${JOB_FILE}" | python "${DISPATCH_SCRIPT}" 2>&1) || {
    DISPATCH_EXIT=$?
    fail "dispatch_task.py failed (exit ${DISPATCH_EXIT}): ${DISPATCH_OUTPUT}"
    return 1
  }

  echo "${DISPATCH_OUTPUT}" > "${LOG_DIR}/dispatch-result.json"
  TASK_ID=$(echo "${DISPATCH_OUTPUT}" | python -c "import sys,json; print(json.load(sys.stdin).get('task_id','unknown'))" 2>/dev/null || echo "unknown")
  ok "Recon task dispatched (Task ID: ${TASK_ID})"
}

# ── Step 4: Monitor Engagement Progression ─────────────────────────────────
monitor_engagement() {
  header "Step 4/6: Monitor Engagement Progression"

  START_TIME=$SECONDS
  LAST_STATE=""
  STATE_COUNTER=0

  info "Polling engagement state every ${POLL_INTERVAL}s (max ${MAX_WAIT_SECONDS}s)..."
  echo ""
  printf "  %-25s %-15s %-10s\n" "State" "Findings" "Elapsed"
  printf "  %-25s %-15s %-10s\n" "─────────────────────" "───────────────" "──────────"

  while [ $((SECONDS - START_TIME)) -lt ${MAX_WAIT_SECONDS} ]; do
    STATE=$(db_query "SELECT status FROM engagements WHERE id = '${ENGAGEMENT_ID}';" 2>/dev/null || echo "unknown")
    FINDINGS=$(db_query "SELECT COUNT(*) FROM findings WHERE engagement_id = '${ENGAGEMENT_ID}';" 2>/dev/null || echo "?")
    ELAPSED=$((SECONDS - START_TIME))

    # Log state transitions
    if [ "${STATE}" != "${LAST_STATE}" ] && [ -n "${LAST_STATE}" ]; then
      echo ""
      info "Transition: ${LAST_STATE} → ${STATE}"
      echo ""
      LAST_STATE="${STATE}"
      # Snapshot resource usage at transition
      docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" worker juice-shop 2>/dev/null >> "${LOG_DIR}/resource-trace.csv" || true
    fi
    if [ -z "${LAST_STATE}" ]; then
      LAST_STATE="${STATE}"
    fi

    printf "  %-25s %-15s %-10s\n" "${STATE}" "${FINDINGS}" "${ELAPSED}s"

    # Terminal states
    if [ "${STATE}" = "complete" ] || [ "${STATE}" = "failed" ]; then
      echo ""
      if [ "${STATE}" = "complete" ]; then
        ok "Engagement reached terminal state: ${STATE}"
      else
        fail "Engagement reached terminal state: ${STATE}"
      fi
      break
    fi

    sleep "${POLL_INTERVAL}"
  done

  TOTAL_TIME=$((SECONDS - START_TIME))
  info "Monitoring duration: ${TOTAL_TIME}s"

  if [ ${TOTAL_TIME} -ge ${MAX_WAIT_SECONDS} ]; then
    warn "Max wait time (${MAX_WAIT_SECONDS}s) exceeded — engagement may still be running"
    warn "Final state: ${STATE} (use 'docker compose logs worker' to check status)"
  fi
}

# ── Step 5: Stop Log Capture ───────────────────────────────────────────────
stop_log_capture() {
  header "Step 5/6: Stop Log Capture"

  if [ -n "${LOGS_PID:-}" ]; then
    kill "${LOGS_PID}" 2>/dev/null || true
    wait "${LOGS_PID}" 2>/dev/null || true
    ok "Worker log capture stopped"
  fi

  if [ -n "${TARGET_LOGS_PID:-}" ]; then
    kill "${TARGET_LOGS_PID}" 2>/dev/null || true
    wait "${TARGET_LOGS_PID}" 2>/dev/null || true
    ok "Target log capture stopped"
  fi

  # Snapshot final resource usage
  docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" worker juice-shop 2>/dev/null > "${LOG_DIR}/resource-final.csv" || true
  ok "Final resource snapshot captured"
}

# ── Step 6: Post-Mortem Analysis ───────────────────────────────────────────
post_mortem() {
  header "Step 6/6: Post-Mortem Analysis"

  # Run post-mortem SQL queries
  info "Running post-mortem SQL queries..."
  # Use unquoted heredoc so ENGAGEMENT_ID shell variable is substituted
  docker compose exec -T postgres psql -U argus_user -d argus_pentest > "${LOG_DIR}/post-mortem.txt" 2>&1 <<SQL
\x on
-- 1. Engagement summary
SELECT 
  id, target_url, status, 
  created_at, started_at, completed_at,
  EXTRACT(EPOCH FROM (completed_at - created_at))::int as duration_seconds
FROM engagements 
WHERE id = '${ENGAGEMENT_ID}';

-- 2. Findings severity distribution
SELECT 
  severity, 
  COUNT(*) as count,
  ROUND(AVG(confidence)::numeric, 2) as avg_confidence,
  COUNT(*) FILTER (WHERE verified = true) as verified
FROM findings 
WHERE engagement_id = '${ENGAGEMENT_ID}' 
GROUP BY severity 
ORDER BY 
  CASE severity 
    WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 
    WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 4 
    ELSE 5 
  END;

-- 3. Findings by type (top 20)
SELECT type, COUNT(*) as count 
FROM findings 
WHERE engagement_id = '${ENGAGEMENT_ID}' 
GROUP BY type 
ORDER BY count DESC 
LIMIT 20;

-- 4. Tool productivity
SELECT source_tool, COUNT(*) as findings_count 
FROM findings 
WHERE engagement_id = '${ENGAGEMENT_ID}' 
GROUP BY source_tool 
ORDER BY findings_count DESC;

-- 5. Verification summary
SELECT 
  COUNT(*) as total,
  COUNT(*) FILTER (WHERE verified = true) as confirmed,
  COUNT(*) FILTER (WHERE verified = false AND confidence > 0) as unconfirmed,
  ROUND(AVG(confidence)::numeric, 2) as avg_confidence
FROM findings 
WHERE engagement_id = '${ENGAGEMENT_ID}';
\x off
SQL

  ok "Post-mortem written to ${LOG_DIR}/post-mortem.txt"

  # Extract key events from worker log
  if [ -f "${LOG_DIR}/worker.log" ]; then
    info "Extracting key events from worker log..."
    grep -E "Swarm:|verification|completed|failed|error|traceback|timeout|circuit|blocked|violation|activated" "${LOG_DIR}/worker.log" \
      > "${LOG_DIR}/key-events.log" 2>/dev/null || true
    ok "Key events extracted to ${LOG_DIR}/key-events.log"
  fi

  # Count key metrics
  SWARM_COUNT=$(grep -c "Swarm:" "${LOG_DIR}/key-events.log" 2>/dev/null || echo 0)
  ERROR_COUNT=$(grep -ciE "error|traceback|failed" "${LOG_DIR}/key-events.log" 2>/dev/null || echo 0)
  VERIFIED_COUNT=$(grep -c "verified" "${LOG_DIR}/key-events.log" 2>/dev/null || echo 0)

  # Print summary
  echo ""
  info "=== Run Summary ==="
  echo "  Run ID:        ${RUN_ID}"
  echo "  Target:        ${TARGET_URL}"
  echo "  Engagement:    ${ENGAGEMENT_ID}"
  echo "  Log dir:       ${LOG_DIR}"
  echo "  Swarm events:  ${SWARM_COUNT}"
  echo "  Errors:        ${ERROR_COUNT}"
  echo "  Verifications: ${VERIFIED_COUNT}"
  echo ""
  info "Key files:"
  echo "  Worker log:       ${LOG_DIR}/worker.log"
  echo "  Target log:       ${LOG_DIR}/target.log"
  echo "  Post-mortem:      ${LOG_DIR}/post-mortem.txt"
  echo "  Key events:       ${LOG_DIR}/key-events.log"
  echo "  Resource traces:  ${LOG_DIR}/resource-trace.csv"
}

# ── Cleanup ────────────────────────────────────────────────────────────────
cleanup() {
  # Stop any background processes on exit
  if [ -n "${LOGS_PID:-}" ]; then
    kill "${LOGS_PID}" 2>/dev/null || true
  fi
  if [ -n "${TARGET_LOGS_PID:-}" ]; then
    kill "${TARGET_LOGS_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

# ── Main ───────────────────────────────────────────────────────────────────
main() {
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║              Argus Live-Fire Validation Runner               ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Run ID:       ${RUN_ID}"
  echo "  Target:       ${TARGET_URL}"
  echo "  Engagement:   ${ENGAGEMENT_ID}"
  echo "  Log dir:      ${LOG_DIR}"
  echo "  Max wait:     ${MAX_WAIT_SECONDS}s"
  echo ""

  # Run through all steps
  preflight || { fail "Pre-flight checks failed — aborting"; exit 1; }
  reset_engagement || { fail "Failed to reset engagement — aborting"; exit 1; }
  start_log_capture
  dispatch_recon || { fail "Failed to dispatch recon — aborting"; exit 1; }
  monitor_engagement
  stop_log_capture
  post_mortem

  # Final status
  FINAL_STATE=$(db_query "SELECT status FROM engagements WHERE id = '${ENGAGEMENT_ID}';" 2>/dev/null || echo "unknown")
  TOTAL_FINDINGS=$(db_query "SELECT COUNT(*) FROM findings WHERE engagement_id = '${ENGAGEMENT_ID}';" 2>/dev/null || echo "?")
  DURATION=$((SECONDS / 60))

  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║                     Run Complete                             ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Final state:    ${FINAL_STATE}"
  echo "  Total findings: ${TOTAL_FINDINGS}"
  echo "  Duration:       ${DURATION} min"
  echo "  Log directory:  ${LOG_DIR}"
  echo ""

  if [ "${FINAL_STATE}" = "complete" ]; then
    ok "Engagement completed successfully!"
  else
    warn "Engagement ended in state: ${FINAL_STATE}"
    warn "Check ${LOG_DIR}/worker.log for details"
  fi
}

main "$@"
